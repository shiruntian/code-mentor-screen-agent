"""模型接入接口：目录、保存 Key（加密）、切换、连通性测试。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_id
from app.core.config import settings
from app.core.errors import NotFoundError, ValidationError
from app.core.security import decrypt_secret, encrypt_secret, mask_secret
from app.db.base import get_db
from app.db.models import ProviderConfig
from app.llm.registry import PROVIDERS, default_vision_model, provider_catalog
from app.llm.service import list_ollama_models, list_provider_models, test_connection
from app.schemas.api import ProviderActivate, ProviderModelsQuery, ProviderTest, ProviderUpsert

router = APIRouter(prefix="/providers", tags=["providers"])


def _serialize(cfg: ProviderConfig | None, provider: str) -> dict[str, Any]:
    info = PROVIDERS[provider]
    return {
        "provider": provider,
        "label": info.label,
        "configured": cfg is not None,
        "has_key": bool(cfg and cfg.api_key_enc),
        "api_key_mask": (cfg.api_key_mask if cfg else "") or "",
        "base_url": (cfg.base_url if cfg else "") or info.base_url,
        "model": (cfg.model if cfg else "") or (info.models[0].id if info.models else ""),
        "vision_model": (cfg.vision_model if cfg else "") or default_vision_model(provider) or "",
        "is_active": bool(cfg and cfg.is_active),
        "needs_key": info.needs_key,
        "updated_at": cfg.updated_at.isoformat() if cfg and cfg.updated_at else None,
    }


@router.get("")
async def list_providers(
    session: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict[str, Any]:
    rows = (
        await session.execute(select(ProviderConfig).where(ProviderConfig.user_id == user_id))
    ).scalars().all()
    by_provider = {r.provider: r for r in rows}
    return {
        "catalog": provider_catalog(),
        "configs": [_serialize(by_provider.get(p), p) for p in PROVIDERS],
        "active": next((r.provider for r in rows if r.is_active), None),
    }


def _apply_payload(cfg: ProviderConfig, payload: ProviderUpsert | ProviderActivate) -> None:
    """把请求里的配置字段合并到 ORM 对象上（Key 加密存储，空串表示清除）。"""
    if payload.api_key is not None:
        key = payload.api_key.strip()
        if key and not key.startswith("•") and "****" not in key:
            cfg.api_key_enc = encrypt_secret(key)
            cfg.api_key_mask = mask_secret(key)
        elif key == "":
            cfg.api_key_enc = None
            cfg.api_key_mask = None

    if payload.base_url:
        cfg.base_url = payload.base_url.strip().rstrip("/")
    if payload.model:
        cfg.model = payload.model.strip()
    if payload.vision_model is not None:
        cfg.vision_model = payload.vision_model.strip() or None
    embedding_model = getattr(payload, "embedding_model", None)
    if embedding_model is not None:
        cfg.embedding_model = embedding_model.strip() or None


@router.put("/{provider}")
async def upsert_provider(
    provider: str,
    payload: ProviderUpsert,
    session: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict[str, Any]:
    if provider not in PROVIDERS:
        raise NotFoundError(f"未知的模型供应商: {provider}")
    info = PROVIDERS[provider]

    cfg = (
        await session.execute(
            select(ProviderConfig).where(
                ProviderConfig.user_id == user_id, ProviderConfig.provider == provider
            )
        )
    ).scalars().first()
    if cfg is None:
        cfg = ProviderConfig(user_id=user_id, provider=provider)
        session.add(cfg)

    _apply_payload(cfg, payload)

    if payload.is_active:
        await _activate(session, user_id, provider, cfg)

    await session.commit()
    await session.refresh(cfg)
    return _serialize(cfg, provider)


async def _activate(
    session: AsyncSession, user_id: int, provider: str, cfg: ProviderConfig
) -> None:
    others = (
        await session.execute(
            select(ProviderConfig).where(
                ProviderConfig.user_id == user_id, ProviderConfig.provider != provider
            )
        )
    ).scalars().all()
    for row in others:
        row.is_active = False
    cfg.is_active = True


@router.post("/{provider}/activate")
async def activate_provider(
    provider: str,
    payload: ProviderActivate | None = None,
    session: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict[str, Any]:
    """启用供应商；body 里带 Key 时会先落库再启用，支持「一步接入」。"""
    if provider not in PROVIDERS:
        raise NotFoundError(f"未知的模型供应商: {provider}")
    info = PROVIDERS[provider]
    cfg = (
        await session.execute(
            select(ProviderConfig).where(
                ProviderConfig.user_id == user_id, ProviderConfig.provider == provider
            )
        )
    ).scalars().first()
    if cfg is None:
        cfg = ProviderConfig(user_id=user_id, provider=provider)
        session.add(cfg)
        await session.flush()

    if payload is not None:
        _apply_payload(cfg, payload)

    if info.needs_key and not cfg.api_key_enc:
        cfg.model = cfg.model or (info.models[0].id if info.models else None)
        raise ValidationError(
            f"{info.label} 还没有保存 API Key",
            hint="前端「设为当前模型」会连同输入框里的 Key 一起提交；如果你用的是 curl / 脚本，"
            "请先 PUT /api/providers/{provider} 保存 Key 再启用",
        )
    await _activate(session, user_id, provider, cfg)
    await session.commit()
    await session.refresh(cfg)
    return _serialize(cfg, provider)


@router.delete("/{provider}/key")
async def clear_key(
    provider: str,
    session: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict[str, Any]:
    cfg = (
        await session.execute(
            select(ProviderConfig).where(
                ProviderConfig.user_id == user_id, ProviderConfig.provider == provider
            )
        )
    ).scalars().first()
    if cfg is None:
        raise NotFoundError("该供应商尚未配置")
    cfg.api_key_enc = None
    cfg.api_key_mask = None
    await session.commit()
    return _serialize(cfg, provider)


@router.post("/{provider}/models")
async def provider_models(
    provider: str,
    payload: ProviderModelsQuery | None = None,
    session: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict[str, Any]:
    """拉取该供应商真实可用的模型列表（运行时向 /models 查询，带 60s 缓存）。"""
    if provider not in PROVIDERS:
        raise NotFoundError(f"未知的模型供应商: {provider}")
    info = PROVIDERS[provider]
    cfg = (
        await session.execute(
            select(ProviderConfig).where(
                ProviderConfig.user_id == user_id, ProviderConfig.provider == provider
            )
        )
    ).scalars().first()

    api_key = (payload.api_key or "").strip() if payload else ""
    if not api_key and cfg is not None:
        api_key = decrypt_secret(cfg.api_key_enc)
    base_url = (payload.base_url if payload else None) or (cfg.base_url if cfg else None) or info.base_url
    refresh = bool(payload.refresh) if payload else False

    result = await list_provider_models(
        provider, base_url=base_url, api_key=api_key, refresh=refresh
    )
    result["provider"] = provider
    result["base_url"] = base_url
    return result


@router.post("/{provider}/test")
async def test_provider(
    provider: str,
    payload: ProviderTest,
    session: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict[str, Any]:
    if provider not in PROVIDERS:
        raise NotFoundError(f"未知的模型供应商: {provider}")
    info = PROVIDERS[provider]
    cfg = (
        await session.execute(
            select(ProviderConfig).where(
                ProviderConfig.user_id == user_id, ProviderConfig.provider == provider
            )
        )
    ).scalars().first()
    api_key = (payload.api_key or "").strip()
    if not api_key and cfg is not None:
        api_key = decrypt_secret(cfg.api_key_enc)
    result = await test_connection(
        provider=provider,
        base_url=payload.base_url or (cfg.base_url if cfg else info.base_url),
        api_key=api_key,
        model=payload.model or (cfg.model if cfg else "") or (info.models[0].id if info.models else ""),
    )
    result["provider"] = provider
    return result


@router.get("/ollama/models")
async def ollama_models() -> dict[str, Any]:
    models = await list_ollama_models()
    return {"ok": bool(models), "models": models, "base_url": "http://127.0.0.1:11434"}


@router.get("/defaults")
async def defaults() -> dict[str, Any]:
    return {
        "default_provider": "deepseek",
        "default_model": "deepseek-chat",
        "qdrant_mode": settings.qdrant_mode,
    }