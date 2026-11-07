"""长期记忆接口。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_id
from app.core.errors import NotFoundError
from app.core.state import state
from app.db.base import get_db
from app.db.models import MemoryItem
from app.memory.service import (
    add_memory,
    clear_memories,
    delete_memory,
    list_memories,
    memory_stats,
    recall_memories,
)
from app.schemas.api import MemoryCreate, MemoryRecall

router = APIRouter(prefix="/memory", tags=["memory"])


def _serialize(m: MemoryItem) -> dict[str, Any]:
    return {
        "id": m.id,
        "kind": m.kind,
        "content": m.content,
        "tags": m.tags,
        "importance": m.importance,
        "access_count": m.access_count,
        "indexed": m.indexed,
        "source_conversation": m.source_conversation,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


@router.get("")
async def list_memory(
    session: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict[str, Any]:
    items = await list_memories(session, user_id)
    stats = await memory_stats(session, user_id)
    return {"items": [_serialize(m) for m in items], "stats": stats}


@router.post("")
async def create_memory(
    payload: MemoryCreate,
    session: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict[str, Any]:
    item = await add_memory(
        session,
        state.store,
        user_id=user_id,
        content=payload.content,
        kind=payload.kind,
        tags=payload.tags,
        importance=payload.importance,
    )
    return _serialize(item)


@router.delete("/{memory_id}")
async def remove_memory(
    memory_id: int,
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    ok = await delete_memory(session, state.store, memory_id)
    if not ok:
        raise NotFoundError("记忆不存在")
    return {"ok": True, "deleted": memory_id}


@router.delete("")
async def clear_all(
    session: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict[str, Any]:
    count = await clear_memories(session, user_id)
    return {"ok": True, "deleted": count}


@router.post("/recall")
async def recall(
    payload: MemoryRecall,
    session: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict[str, Any]:
    items = await recall_memories(
        session, state.store, user_id=user_id, query=payload.query, top_k=payload.top_k
    )
    return {"query": payload.query, "items": items, "count": len(items)}


@router.get("/search")
async def search_memory(
    q: str,
    session: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict[str, Any]:
    rows = (
        await session.execute(
            select(MemoryItem)
            .where(MemoryItem.user_id == user_id, MemoryItem.content.contains(q))
            .limit(50)
        )
    ).scalars().all()
    return {"items": [_serialize(m) for m in rows]}