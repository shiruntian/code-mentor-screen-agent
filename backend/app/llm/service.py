"""模型解析与构建：把数据库里的配置变成真正可调用的 LangChain ChatModel。"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any

import httpx
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import LLMNotConfiguredError
from app.core.logging import get_logger
from app.core.security import decrypt_secret
from app.db.models import ProviderConfig
from app.llm.registry import PROVIDERS, default_vision_model, get_provider

logger = get_logger(__name__)


@dataclass(slots=True)
class ResolvedModel:
    provider: str
    model: str
    base_url: str
    api_key: str
    vision_model: str | None = None
    supports_vision: bool = False
    label: str = ""

    def describe(self) -> dict[str, Any]:
        info = PROVIDERS.get(self.provider)
        return {
            "provider": self.provider,
            "provider_label": info.label if info else self.provider,
            "model": self.model,
            "vision_model": self.vision_model,
            "supports_vision": self.supports_vision,
            "base_url": self.base_url,
        }


async def get_provider_config(
    session: AsyncSession, provider: str, user_id: int = 1
) -> ProviderConfig | None:
    return (
        await session.execute(
            select(ProviderConfig).where(
                ProviderConfig.user_id == user_id, ProviderConfig.provider == provider
            )
        )
    ).scalar_one_or_none()


async def get_active_config(session: AsyncSession, user_id: int = 1) -> ProviderConfig | None:
    return (
        await session.execute(
            select(ProviderConfig).where(
                ProviderConfig.user_id == user_id, ProviderConfig.is_active.is_(True)
            )
        )
    ).scalars().first()


async def resolve_model(
    session: AsyncSession,
    *,
    provider: str | None = None,
    model: str | None = None,
    need_vision: bool = False,
    user_id: int = 1,
) -> ResolvedModel:
    """解析出本次请求实际要用的模型；缺 Key 时给出可执行的错误提示。"""
    cfg: ProviderConfig | None = None
    if provider:
        cfg = await get_provider_config(session, provider, user_id)
    if cfg is None:
        cfg = await get_active_config(session, user_id)
    if cfg is None:
        raise LLMNotConfiguredError(
            "还没有配置任何模型，请先到「设置 → 模型接入」填写 API Key 或选择本地 Ollama",
            hint="本地模型可以用 Ollama（provider=ollama），无需 Key",
        )

    info = get_provider(cfg.provider)
    api_key = decrypt_secret(cfg.api_key_enc)
    chosen_model = model or cfg.model or (info.models[0].id if info.models else "")
    vision_model = cfg.vision_model or default_vision_model(cfg.provider)

    if info.needs_key and not api_key:
        if cfg.api_key_enc:
            # 有密文却解不开：通常是 data/.fernet.key 被换掉/删掉了
            raise LLMNotConfiguredError(
                f"{info.label} 已保存的 API Key 无法解密（本地密钥文件 data/.fernet.key 可能被重置）",
                hint="重新填写一次 Key 并保存即可恢复；已保存的 Key 不会因为重启丢失，只会因为密钥文件被替换而失效",
            )
        raise LLMNotConfiguredError(
            f"{info.label} 尚未填写 API Key",
            hint=f"在「设置 → 模型接入」中填入 Key 后会自动加密保存在本地。申请地址：{info.doc}",
        )

    supports_vision = bool(vision_model)
    if need_vision and not supports_vision:
        raise LLMNotConfiguredError(
            f"当前模型 {chosen_model} 不支持图片输入",
            hint="请切换到支持视觉的模型，例如通义千问的 qwen-vl-max / OpenAI 的 gpt-4o / Ollama 的 qwen2.5vl；"
            "也可以在「模型接入」里把视觉模型填成你账户下真实存在的多模态模型名",
        )

    return ResolvedModel(
        provider=cfg.provider,
        model=chosen_model,
        base_url=cfg.base_url or info.base_url,
        api_key=api_key,
        vision_model=vision_model,
        supports_vision=supports_vision,
        label=info.label,
    )


_CLIENT_CACHE: dict[tuple, BaseChatModel] = {}
_CLIENT_CACHE_MAX = 24


def _client_key(
    resolved: ResolvedModel,
    model_name: str,
    streaming: bool,
    temperature: float,
    thinking: bool | None,
    max_tokens: int | None = None,
    json_mode: bool = False,
) -> tuple:
    import hashlib

    key_hash = hashlib.blake2b((resolved.api_key or "").encode(), digest_size=8).hexdigest()
    return (
        resolved.provider,
        resolved.base_url,
        key_hash,
        model_name,
        streaming,
        round(float(temperature), 3),
        thinking,
        max_tokens,
        json_mode,
    )


def build_chat_model(
    resolved: ResolvedModel,
    *,
    model_override: str | None = None,
    streaming: bool = True,
    temperature: float = 0.3,
    tools: list[Any] | None = None,
    max_tokens: int | None = None,
    json_mode: bool = False,
    thinking: bool | None = None,
) -> BaseChatModel:
    """构造 ChatModel（带进程内缓存，复用连接池）；tools 非空时自动绑定工具。

    缓存很关键：每轮对话会用到 planner / actor / answer 三个模型实例，
    如果每次都 new 一个，就要重复做 TCP+TLS 握手，单跳多几百毫秒。
    """
    model_name = model_override or resolved.model
    cache_key = _client_key(
        resolved, model_name, streaming, temperature, thinking, max_tokens, json_mode
    )

    llm = _CLIENT_CACHE.get(cache_key)
    if llm is None:
        kwargs: dict[str, Any] = {
            "model": model_name,
            "api_key": resolved.api_key or "EMPTY",
            "base_url": resolved.base_url,
            "streaming": streaming,
            "timeout": 120,
            "max_retries": 1,
        }
        # 推理模型通常不接受 temperature
        if not any(tag in model_name.lower() for tag in ("reasoner", "r1", "o1", "o3")):
            kwargs["temperature"] = temperature
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        extra: dict[str, Any] = {}
        if json_mode:
            extra["response_format"] = {"type": "json_object"}
        if extra:
            kwargs["model_kwargs"] = extra
        if thinking is False and resolved.provider == "qwen" and "qwen3" in model_name.lower():
            # DashScope 兼容模式：关掉思维链，单跳能快一个数量级。
            # 必须走 extra_body，否则会被当成 SDK 方法参数（unexpected keyword argument）。
            kwargs["extra_body"] = {"enable_thinking": False}
        llm = ChatOpenAI(**kwargs)

        if len(_CLIENT_CACHE) >= _CLIENT_CACHE_MAX:
            _CLIENT_CACHE.pop(next(iter(_CLIENT_CACHE)))
        _CLIENT_CACHE[cache_key] = llm

    if tools:
        return llm.bind_tools(tools)
    return llm


def clear_client_cache() -> None:
    _CLIENT_CACHE.clear()


def friendly_error(exc: BaseException) -> str:
    """把各家 SDK 的花式报错翻译成学习者能看懂的一句话。"""
    text = f"{exc.__class__.__name__}: {exc}"
    lowered = text.lower()
    if "401" in text or "authentication" in lowered or "invalid_api_key" in lowered or "invalid api key" in lowered:
        return "API Key 无效或已失效，请到「设置 → 模型接入」重新填写并点「测试连接」"
    if "402" in text or "insufficient" in lowered or "balance" in lowered:
        return "模型账户余额不足或额度用尽，请充值或换一个模型"
    if "429" in text or "rate limit" in lowered or "too many requests" in lowered:
        return "触发限流（请求过于频繁），等几秒再试，或换个小一点的模型"
    if "timeout" in lowered or "timed out" in lowered:
        return "模型响应超时，可能是网络较慢或提示词太长，请重试一次"
    if "connection" in lowered or "connect" in lowered or "name or service" in lowered:
        return "连不上模型服务，请检查 Base URL、网络代理，或确认本地 Ollama 已启动"
    if "404" in text or "model_not_found" in lowered:
        return "模型名不存在，请在设置里重新选择模型（或先 ollama pull 下载）"
    if "400" in text:
        return f"请求被模型服务拒绝：{str(exc)[:160]}"
    return f"模型调用失败：{str(exc)[:200]}"


_VISION_HINTS = ("vl", "vision", "gpt-4o", "omni", "llava", "multimodal", "-4v", "4.5v", "internvl")


def looks_like_vision_model(model_id: str) -> bool:
    """服务端返回的模型名里没有能力字段，只能按命名习惯猜多模态。"""
    lowered = (model_id or "").lower()
    return any(hint in lowered for hint in _VISION_HINTS)


_MODEL_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_MODEL_TTL = 60.0


async def list_provider_models(
    provider: str, base_url: str, api_key: str, *, refresh: bool = False
) -> dict[str, Any]:
    """向供应商的 /models 拉取真实可用模型，与内置推荐合并。

    这样厂商上新模型（例如 DeepSeek 的 V4 系列）不需要改代码就能出现在下拉框里；
    拉不到时回退到内置推荐，并在 message 里说明原因。
    """
    info = PROVIDERS.get(provider)
    curated = [asdict(m) for m in info.all_models()] if info else []
    root = (base_url or (info.base_url if info else "")).rstrip("/")

    cache_key = f"{provider}|{root}"
    cached = _MODEL_CACHE.get(cache_key)
    if cached and not refresh and time.time() - cached[0] < _MODEL_TTL:
        return dict(cached[1])

    remote: list[str] = []
    error = ""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            if provider == "ollama":
                base = root[: -len("/v1")] if root.endswith("/v1") else root
                resp = await client.get(f"{base}/api/tags")
                if resp.status_code >= 400:
                    error = f"HTTP {resp.status_code}"
                else:
                    remote = [m.get("name", "") for m in resp.json().get("models", []) if m.get("name")]
            else:
                headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
                resp = await client.get(f"{root}/models", headers=headers)
                if resp.status_code >= 400:
                    error = f"HTTP {resp.status_code}"
                    if resp.status_code in (401, 403):
                        error += "（Key 无效或未填写）"
                else:
                    payload = resp.json()
                    rows = payload.get("data") or payload.get("models") or []
                    remote = [str(m.get("id") or m.get("name")) for m in rows if (m.get("id") or m.get("name"))]
    except Exception as exc:  # noqa: BLE001
        error = f"{exc.__class__.__name__}: {exc}"[:160]

    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for model in curated:
        model_id = model["id"]
        seen.add(model_id)
        merged.append({**model, "curated": True})
    for model_id in remote:
        if model_id in seen:
            continue
        seen.add(model_id)
        merged.append(
            {
                "id": model_id,
                "label": model_id,
                "vision": looks_like_vision_model(model_id),
                "reasoning": any(k in model_id.lower() for k in ("reasoner", "r1", "thinking", "o1", "o3")),
                "note": "服务端返回",
                "curated": False,
            }
        )

    result: dict[str, Any] = {
        "ok": bool(remote),
        "source": "remote" if remote else "fallback",
        "models": merged,
        "count": len(remote),
        "message": (
            f"已从服务端获取 {len(remote)} 个模型"
            if remote
            else f"未能获取服务端模型列表（{error or '无返回'}），先展示内置推荐；可直接手动填写模型名"
        ),
    }
    _MODEL_CACHE[cache_key] = (time.time(), result)
    return dict(result)


async def list_ollama_models(base_url: str = "http://127.0.0.1:11434") -> list[str]:
    """探测本地 Ollama 已安装模型。"""
    root = base_url.rstrip("/")
    if root.endswith("/v1"):
        root = root[: -len("/v1")]
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.get(f"{root}/api/tags")
            resp.raise_for_status()
            data = resp.json()
        return [m.get("name", "") for m in data.get("models", []) if m.get("name")]
    except Exception as exc:  # noqa: BLE001
        logger.info("Ollama 探测失败: %s", exc)
        return []


async def test_connection(
    *, provider: str, base_url: str, api_key: str, model: str
) -> dict[str, Any]:
    """给前端「测试连接」按钮用：真的发一次最小请求。"""
    root = (base_url or "").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            if provider == "ollama":
                base = root[: -len("/v1")] if root.endswith("/v1") else root
                resp = await client.get(f"{base}/api/tags")
                resp.raise_for_status()
                models = [m.get("name") for m in resp.json().get("models", [])]
                return {"ok": True, "message": f"Ollama 在线，已安装 {len(models)} 个模型", "models": models}
            headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
            resp = await client.post(
                f"{root}/chat/completions",
                headers=headers,
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 8,
                    "stream": False,
                },
            )
            if resp.status_code >= 400:
                return {
                    "ok": False,
                    "message": f"HTTP {resp.status_code}: {resp.text[:200]}",
                }
            return {"ok": True, "message": "连接成功，模型可用"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": f"连接失败：{exc}"}