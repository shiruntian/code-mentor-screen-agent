"""运行参数设置（内存生效 + 持久化到 app_settings）。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_id
from app.core.config import settings
from app.core.state import state
from app.db.base import get_db
from app.db.models import AppSetting
from app.schemas.api import SettingsUpdate

router = APIRouter(prefix="/settings", tags=["settings"])

RUNTIME_FIELDS = (
    "agent_max_iterations",
    "screen_interval_ms",
    "screen_mode",
    "env_download_dir",
    "env_install_root",
    "editor_install_root",
    "screen_capture_ms",
    "screen_skip_unchanged",
    "screen_max_steps",
    "screen_dry_run",
    "short_term_window",
    "screen_ime_guard",
    "screen_type_mode",
    "agent_tool_rounds",
    "agent_budget_s",
    "agent_fast_lane",
    "planner_max_tokens",
    "llm_disable_thinking",
    "agent_screen_tool",
    "agent_fs_tool",
    "fs_roots",
    "fs_max_entries",
    "fs_allow_all_drives",
    "fs_search_budget_s",
    "screen_retro",
    "screen_share_chat_model",
    "screen_model_override",
    "screen_ask_opacity",
    "screen_ask_theme",
    "screen_ask_tint",
    "screen_ask_accent",
    "screen_image_max_width",
    "screen_image_quality",
    "screen_zoom_max",
    "screen_panic_hotkey",
    "screen_panic_enabled",
)


def current_settings() -> dict[str, Any]:
    return {
        "agent_max_iterations": settings.agent_max_iterations,
        "agent_tool_rounds": settings.agent_tool_rounds,
        "agent_budget_s": settings.agent_budget_s,
        "agent_fast_lane": settings.agent_fast_lane,
        "planner_max_tokens": settings.planner_max_tokens,
        "llm_disable_thinking": settings.llm_disable_thinking,
        "agent_screen_tool": settings.agent_screen_tool,
        "agent_fs_tool": settings.agent_fs_tool,
        "fs_roots": settings.fs_roots,
        "fs_max_entries": settings.fs_max_entries,
        "fs_allow_all_drives": settings.fs_allow_all_drives,
        "fs_search_budget_s": settings.fs_search_budget_s,
        "screen_retro": settings.screen_retro,
        "screen_share_chat_model": settings.screen_share_chat_model,
        "screen_model_override": settings.screen_model_override,
        "screen_ask_opacity": settings.screen_ask_opacity,
        "screen_ask_theme": settings.screen_ask_theme,
        "screen_ask_tint": settings.screen_ask_tint,
        "screen_ask_accent": settings.screen_ask_accent,
        "screen_image_max_width": settings.screen_image_max_width,
        "screen_image_quality": settings.screen_image_quality,
        "screen_zoom_max": settings.screen_zoom_max,
        "screen_panic_hotkey": settings.screen_panic_hotkey,
        "screen_panic_enabled": settings.screen_panic_enabled,
        "screen_interval_ms": settings.screen_interval_ms,
        "screen_mode": settings.screen_mode,
        "env_download_dir": settings.env_download_dir,
        "env_install_root": settings.env_install_root,
        "editor_install_root": settings.editor_install_root,
        "screen_capture_ms": settings.screen_capture_ms,
        "screen_skip_unchanged": settings.screen_skip_unchanged,
        "screen_ime_guard": settings.screen_ime_guard,
        "screen_type_mode": settings.screen_type_mode,
        "screen_max_steps": settings.screen_max_steps,
        "screen_dry_run": settings.screen_dry_run,
        "short_term_window": settings.short_term_window,
        "embedding_provider": settings.embedding_provider,
        "embedding_dim": settings.embedding_dim,
        "qdrant_mode": settings.qdrant_mode,
        "python_sandbox_timeout": settings.python_sandbox_timeout,
    }


@router.get("")
async def get_settings(session: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    row = await session.get(AppSetting, "runtime")
    vector = await state.store.stats() if state.store is not None else {}
    return {"runtime": current_settings(), "vector": vector, "persisted": (row.value if row else None)}


@router.put("")
async def update_settings(
    payload: SettingsUpdate,
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    for field in RUNTIME_FIELDS:
        value = getattr(payload, field)
        if value is not None:
            setattr(settings, field, value)
    row = await session.get(AppSetting, "runtime")
    data = {k: getattr(settings, k) for k in RUNTIME_FIELDS}
    if row is None:
        row = AppSetting(key="runtime", value=data)
        session.add(row)
    else:
        row.value = data
    await session.commit()
    return {"ok": True, "runtime": current_settings()}


@router.get("/embedding")
async def embedding_info() -> dict[str, Any]:
    from app.rag.embeddings import build_embedder

    info = {"provider": settings.embedding_provider, "dim": settings.embedding_dim}
    if state.store is not None:
        info.update(await state.store.stats())
    else:
        info["embedder"] = build_embedder({"provider": settings.embedding_provider, "dim": settings.embedding_dim}).name
    return info