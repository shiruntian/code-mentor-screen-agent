"""模型供应商注册表：国内外主流云厂商 + 本地（Ollama / vLLM）+ 自定义 OpenAI 兼容端点。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class ModelInfo:
    id: str
    label: str
    vision: bool = False
    reasoning: bool = False
    note: str = ""


@dataclass(slots=True)
class ProviderInfo:
    id: str
    label: str
    base_url: str
    models: list[ModelInfo] = field(default_factory=list)
    vision_models: list[ModelInfo] = field(default_factory=list)
    needs_key: bool = True
    local: bool = False
    doc: str = ""
    embedding_model: str | None = None

    def all_models(self) -> list[ModelInfo]:
        seen: dict[str, ModelInfo] = {}
        for m in [*self.models, *self.vision_models]:
            seen[m.id] = m
        return list(seen.values())

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "base_url": self.base_url,
            "needs_key": self.needs_key,
            "local": self.local,
            "doc": self.doc,
            "embedding_model": self.embedding_model,
            "models": [asdict(m) for m in self.models],
            "vision_models": [asdict(m) for m in self.vision_models],
        }


PROVIDERS: dict[str, ProviderInfo] = {
    "deepseek": ProviderInfo(
        id="deepseek",
        label="DeepSeek 深度求索",
        base_url="https://api.deepseek.com/v1",
        models=[
            ModelInfo("deepseek-chat", "DeepSeek-V3 通用对话", note="性价比高，适合日常学习问答"),
            ModelInfo("deepseek-coder", "DeepSeek-Coder", note="代码补全与解释"),
            ModelInfo("deepseek-reasoner", "DeepSeek-R1 推理", reasoning=True, note="数学/算法推理更强"),
        ],
        doc="https://platform.deepseek.com/api_keys",
    ),
    "qwen": ProviderInfo(
        id="qwen",
        label="通义千问 DashScope",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        models=[
            ModelInfo("qwen3-max", "Qwen3-Max", note="旗舰，综合能力最强"),
            ModelInfo("qwen-plus", "Qwen-Plus", note="均衡，中文理解好"),
            ModelInfo("qwen-turbo", "Qwen-Turbo", note="响应快，适合轻量问答"),
            ModelInfo("qwen3-coder-plus", "Qwen3-Coder", note="代码专用，写代码/改 bug 更强"),
        ],
        vision_models=[
            ModelInfo("qwen3-vl-plus", "Qwen3-VL-Plus 多模态", vision=True, note="截图/界面识别首选"),
            ModelInfo("qwen-vl-max-latest", "Qwen-VL-Max 多模态", vision=True, note="读图/读代码截图"),
            ModelInfo("qwen-vl-plus", "Qwen-VL-Plus 多模态", vision=True),
        ],
        embedding_model="text-embedding-v3",
        doc="https://bailian.console.aliyun.com/",
    ),
    "zhipu": ProviderInfo(
        id="zhipu",
        label="智谱 GLM",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        models=[
            ModelInfo("glm-4.6", "GLM-4.6", note="最新旗舰，代码与推理强"),
            ModelInfo("glm-4.5-air", "GLM-4.5-Air", note="轻量快速"),
            ModelInfo("glm-4-flash", "GLM-4-Flash", note="免费额度，适合练手"),
        ],
        vision_models=[
            ModelInfo("glm-4.5v", "GLM-4.5V 多模态", vision=True, note="看图/看界面"),
            ModelInfo("glm-4v-plus", "GLM-4V-Plus 多模态", vision=True),
        ],
        doc="https://docs.bigmodel.cn/cn/guide/develop/http/introduction",
    ),
    "moonshot": ProviderInfo(
        id="moonshot",
        label="月之暗面 Kimi",
        base_url="https://api.moonshot.cn/v1",
        models=[
            ModelInfo("kimi-k2-0905-preview", "Kimi K2", note="长上下文，代码能力好"),
            ModelInfo("kimi-k2-turbo-preview", "Kimi K2 Turbo", note="更快版本"),
            ModelInfo("moonshot-v1-128k", "Moonshot v1 128K", note="超长文档"),
        ],
        vision_models=[
            ModelInfo("moonshot-v1-8k-vision-preview", "Moonshot v1 视觉", vision=True),
        ],
        doc="https://platform.moonshot.cn/console/api-keys",
    ),
    "ark": ProviderInfo(
        id="ark",
        label="火山方舟 豆包",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        models=[
            ModelInfo("doubao-seed-1-6-250615", "豆包 Seed 1.6", note="综合能力强"),
            ModelInfo("doubao-1-5-pro-32k-250115", "豆包 1.5 Pro", note="均衡"),
        ],
        vision_models=[
            ModelInfo("doubao-seed-1-6-vision-250815", "豆包 Seed 视觉版", vision=True, note="界面识别"),
        ],
        doc="https://console.volcengine.com/ark",
    ),
    "siliconflow": ProviderInfo(
        id="siliconflow",
        label="硅基流动 SiliconFlow",
        base_url="https://api.siliconflow.cn/v1",
        models=[
            ModelInfo("deepseek-ai/DeepSeek-V3", "DeepSeek V3（托管）", note="国内直连，速度快"),
            ModelInfo("Qwen/Qwen3-32B", "Qwen3 32B（托管）"),
            ModelInfo("THUDM/GLM-4-9B-0414", "GLM-4 9B（托管）"),
        ],
        vision_models=[
            ModelInfo("Qwen/Qwen2.5-VL-72B-Instruct", "Qwen2.5-VL 72B", vision=True),
        ],
        doc="https://cloud.siliconflow.cn/account/ak",
    ),
    "openrouter": ProviderInfo(
        id="openrouter",
        label="OpenRouter（聚合多厂商）",
        base_url="https://openrouter.ai/api/v1",
        models=[
            ModelInfo("openai/gpt-4o-mini", "GPT-4o mini", vision=True),
            ModelInfo("anthropic/claude-sonnet-4", "Claude Sonnet 4"),
            ModelInfo("google/gemini-2.5-pro", "Gemini 2.5 Pro", vision=True),
            ModelInfo("deepseek/deepseek-chat", "DeepSeek V3"),
        ],
        vision_models=[
            ModelInfo("openai/gpt-4o", "GPT-4o", vision=True),
            ModelInfo("google/gemini-2.5-flash", "Gemini 2.5 Flash", vision=True),
        ],
        doc="https://openrouter.ai/keys",
    ),
    "groq": ProviderInfo(
        id="groq",
        label="Groq（超快推理）",
        base_url="https://api.groq.com/openai/v1",
        models=[
            ModelInfo("llama-3.3-70b-versatile", "Llama 3.3 70B", note="速度快，延迟低"),
            ModelInfo("qwen/qwen3-32b", "Qwen3 32B"),
        ],
        vision_models=[
            ModelInfo("meta-llama/llama-4-scout-17b-16e-instruct", "Llama 4 Scout", vision=True),
        ],
        doc="https://console.groq.com/keys",
    ),
    "openai": ProviderInfo(
        id="openai",
        label="OpenAI 兼容",
        base_url="https://api.openai.com/v1",
        models=[
            ModelInfo("gpt-4o-mini", "GPT-4o mini", vision=True),
            ModelInfo("gpt-4o", "GPT-4o", vision=True),
        ],
        vision_models=[
            ModelInfo("gpt-4o", "GPT-4o (视觉)", vision=True),
        ],
        embedding_model="text-embedding-3-small",
        doc="https://platform.openai.com/api-keys",
    ),
    "ollama": ProviderInfo(
        id="ollama",
        label="Ollama 本地模型",
        base_url="http://127.0.0.1:11434/v1",
        models=[
            ModelInfo("qwen2.5:7b", "Qwen2.5 7B", note="需先 ollama pull qwen2.5:7b"),
            ModelInfo("deepseek-r1:7b", "DeepSeek-R1 7B", reasoning=True),
            ModelInfo("llama3.1:8b", "Llama 3.1 8B"),
        ],
        vision_models=[ModelInfo("qwen2.5vl:7b", "Qwen2.5-VL 7B", vision=True)],
        needs_key=False,
        local=True,
        embedding_model="nomic-embed-text",
        doc="https://ollama.com/download",
    ),
    "custom": ProviderInfo(
        id="custom",
        label="自定义 OpenAI 兼容端点",
        base_url="http://127.0.0.1:1234/v1",
        models=[ModelInfo("local-model", "自定义模型")],
        needs_key=False,
        doc="任何兼容 /chat/completions 的服务：LM Studio、vLLM、one-api…",
    ),
}

DEFAULT_PROVIDER = "deepseek"
DEFAULT_MODEL = "deepseek-chat"


def get_provider(provider_id: str) -> ProviderInfo:
    info = PROVIDERS.get(provider_id)
    if info is None:
        raise KeyError(f"未知的模型供应商: {provider_id}")
    return info


def is_vision_model(provider_id: str, model: str) -> bool:
    info = PROVIDERS.get(provider_id)
    if not info:
        return False
    return any(m.id == model and m.vision for m in info.all_models())


def default_vision_model(provider_id: str) -> str | None:
    info = PROVIDERS.get(provider_id)
    if not info or not info.vision_models:
        return None
    return info.vision_models[0].id


def provider_catalog() -> list[dict[str, Any]]:
    return [p.to_dict() for p in PROVIDERS.values()]