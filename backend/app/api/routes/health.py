"""健康检查与运行状态。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.tools.builtin import TOOL_META
from app.core.config import settings
from app.core.state import state
from app.db import base as db_base
from app.db.base import get_db
from app.db.models import Conversation, KnowledgeDoc, MemoryItem
from app.llm.registry import provider_catalog

router = APIRouter(tags=["system"])


@router.get("/health")
async def health(session: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    db_ok = True
    try:
        await session.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        db_ok = False

    counts = {"conversations": 0, "memories": 0, "documents": 0}
    try:
        counts["conversations"] = int(
            (await session.execute(select(func.count(Conversation.id)))).scalar_one()
        )
        counts["memories"] = int(
            (await session.execute(select(func.count(MemoryItem.id)))).scalar_one()
        )
        counts["documents"] = int(
            (await session.execute(select(func.count(KnowledgeDoc.id)))).scalar_one()
        )
    except Exception:  # noqa: BLE001
        pass

    vector = await state.store.stats() if state.store is not None else {"error": "未初始化"}

    return {
        "ok": db_ok,
        "app": settings.app_name,
        "version": settings.app_version,
        "uptime_s": state.uptime(),
        "database": {
            "ok": db_ok,
            "url": (db_base.ACTIVE_URL or "").split("@")[-1].split("://")[-1],
            "counts": counts,
        },
        "vector": vector,
        "tools": [{"name": k, **v} for k, v in TOOL_META.items()],
        "providers": [p["id"] for p in provider_catalog()],
    }