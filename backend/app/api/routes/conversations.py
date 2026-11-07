"""会话管理：新建、重命名、删除、消息读取、Agent 轨迹。"""

from __future__ import annotations

from typing import Any, Any

from fastapi import APIRouter, Depends
from sqlalchemy import delete, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_id
from app.core.errors import NotFoundError
from app.db.base import get_db
from app.db.models import AgentRun, Conversation, Message
from app.schemas.api import ConversationCreate, ConversationUpdate

router = APIRouter(prefix="/conversations", tags=["conversations"])


def serialize_message(m: Message) -> dict[str, Any]:
    return {
        "id": m.id,
        "role": m.role,
        "content": m.content,
        "reasoning": m.reasoning,
        "attachments": m.attachments or [],
        "plan": m.plan or [],
        "demo": m.demo,
        "tool_calls": m.tool_calls or [],
        "tool_results": m.tool_results or [],
        "provider": m.provider,
        "model": m.model,
        "tokens": m.tokens,
        "latency_ms": m.latency_ms,
        "error": m.error,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


def serialize_conversation(c: Conversation) -> dict[str, Any]:
    return {
        "id": c.id,
        "title": c.title,
        "provider": c.provider,
        "model": c.model,
        "summary": c.summary,
        "message_count": c.message_count,
        "pinned": c.pinned,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }


@router.get("")
async def list_conversations(
    session: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict[str, Any]:
    rows = (
        await session.execute(
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(desc(Conversation.pinned), desc(Conversation.updated_at))
            .limit(200)
        )
    ).scalars().all()
    return {"items": [serialize_conversation(c) for c in rows], "total": len(rows)}


@router.post("")
async def create_conversation(
    payload: ConversationCreate,
    session: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict[str, Any]:
    conv = Conversation(user_id=user_id, title=(payload.title or "新对话").strip()[:200])
    session.add(conv)
    await session.commit()
    await session.refresh(conv)
    return serialize_conversation(conv)


@router.get("/{conversation_id}")
async def get_conversation(
    conversation_id: str,
    session: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict[str, Any]:
    conv = await session.get(Conversation, conversation_id)
    if conv is None or conv.user_id != user_id:
        raise NotFoundError("会话不存在")
    msgs = (
        await session.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.id)
        )
    ).scalars().all()
    data = serialize_conversation(conv)
    data["messages"] = [serialize_message(m) for m in msgs]
    return data


@router.patch("/{conversation_id}")
async def update_conversation(
    conversation_id: str,
    payload: ConversationUpdate,
    session: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict[str, Any]:
    conv = await session.get(Conversation, conversation_id)
    if conv is None or conv.user_id != user_id:
        raise NotFoundError("会话不存在")
    if payload.title is not None:
        conv.title = payload.title.strip()[:200] or conv.title
    if payload.pinned is not None:
        conv.pinned = payload.pinned
    await session.commit()
    await session.refresh(conv)
    return serialize_conversation(conv)


@router.delete("/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    session: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict[str, Any]:
    conv = await session.get(Conversation, conversation_id)
    if conv is None or conv.user_id != user_id:
        raise NotFoundError("会话不存在")
    await session.execute(delete(Message).where(Message.conversation_id == conversation_id))
    await session.execute(delete(AgentRun).where(AgentRun.conversation_id == conversation_id))
    await session.delete(conv)
    await session.commit()
    return {"ok": True, "deleted": conversation_id}


@router.delete("/{conversation_id}/messages")
async def clear_messages(
    conversation_id: str,
    session: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict[str, Any]:
    conv = await session.get(Conversation, conversation_id)
    if conv is None or conv.user_id != user_id:
        raise NotFoundError("会话不存在")
    await session.execute(delete(Message).where(Message.conversation_id == conversation_id))
    conv.message_count = 0
    conv.summary = None
    await session.commit()
    return {"ok": True}


@router.get("/{conversation_id}/runs")
async def list_runs(
    conversation_id: str,
    session: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict[str, Any]:
    rows = (
        await session.execute(
            select(AgentRun)
            .where(AgentRun.conversation_id == conversation_id)
            .order_by(desc(AgentRun.id))
            .limit(30)
        )
    ).scalars().all()
    return {
        "items": [
            {
                "id": r.id,
                "plan": r.plan or [],
                "steps": r.steps or [],
                "status": r.status,
                "iterations": r.iterations,
                "latency_ms": r.latency_ms,
                "provider": r.provider,
                "model": r.model,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    }

@router.get("/{conversation_id}/tasks")
async def list_tasks(conversation_id: str) -> dict[str, Any]:
    from app.agent.tasks import list_tasks as load

    items = await load(conversation_id)
    done = sum(1 for i in items if i["status"] == "done")
    return {"items": items, "total": len(items), "done": done}


@router.patch("/{conversation_id}/tasks/{idx}")
async def set_task_status(conversation_id: str, idx: int, payload: dict[str, Any]) -> dict[str, Any]:
    from app.agent.tasks import set_status

    status = str(payload.get("status") or "done")
    if status not in ("done", "skipped", "pending", "active"):
        raise AppError("状态只能是 done / skipped / pending / active")
    return await set_status(conversation_id, idx, status)
