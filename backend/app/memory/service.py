"""记忆系统：短期会话上下文（滚动摘要）+ 长期持久化记忆（向量召回）。"""

from __future__ import annotations

import re
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from sqlalchemy import delete, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.db.models import Conversation, MemoryItem, Message
from app.rag.store import QdrantStore

logger = get_logger(__name__)

SUMMARY_PROMPT = """【会话摘要器】
请把下面的多轮对话压缩成不超过 200 字的中文摘要，保留：学习者目标、已掌握内容、
卡住的地方、约定过的偏好。只输出摘要正文，不要任何前缀。

对话：
{dialogue}
"""


# --------------------------------------------------------------------- 短期记忆
async def load_history_messages(
    session: AsyncSession, conversation_id: str, limit: int | None = None
) -> list[Message]:
    limit = limit or settings.short_term_window
    rows = (
        await session.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id, Message.role.in_(("user", "assistant")))
            .order_by(desc(Message.id))
            .limit(limit)
        )
    ).scalars().all()
    return list(reversed(rows))


def to_langchain_messages(rows: list[Message]) -> list[BaseMessage]:
    out: list[BaseMessage] = []
    for row in rows:
        text = row.content or ""
        if not text.strip():
            continue
        if row.role == "user":
            out.append(HumanMessage(content=text))
        elif row.role == "assistant":
            out.append(AIMessage(content=text))
    return out


async def build_context_messages(
    session: AsyncSession, conversation: Conversation, *, limit: int | None = None
) -> list[BaseMessage]:
    """历史消息 + 会话摘要（若有）。"""
    rows = await load_history_messages(session, conversation.id, limit)
    messages = to_langchain_messages(rows)
    if conversation.summary:
        messages.insert(
            0,
            SystemMessage(content=f"【此前对话摘要】\n{conversation.summary}\n（仅供参考，不必复述）"),
        )
    return messages


async def maybe_summarize(
    session: AsyncSession, conversation: Conversation, llm: BaseChatModel | None
) -> str | None:
    """消息过多时滚动压缩历史，控制上下文长度。"""
    if conversation.message_count < settings.summary_trigger:
        return conversation.summary
    rows = (
        await session.execute(
            select(Message)
            .where(Message.conversation_id == conversation.id, Message.role.in_(("user", "assistant")))
            .order_by(desc(Message.id))
            .limit(settings.short_term_window * 2)
        )
    ).scalars().all()
    rows = list(reversed(rows))
    if len(rows) < settings.summary_trigger:
        return conversation.summary

    dialogue = "\n".join(
        f"{'学习者' if r.role == 'user' else '助手'}：{(r.content or '')[:300]}" for r in rows
    )
    summary: str | None = None
    if llm is not None:
        try:
            resp = await llm.ainvoke([HumanMessage(content=SUMMARY_PROMPT.format(dialogue=dialogue))])
            summary = resp.content if isinstance(resp.content, str) else str(resp.content)
            summary = summary.strip()[:600]
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM 生成摘要失败，使用截断摘要: %s", exc)
    if not summary:
        summary = dialogue[:400] + "…"
    conversation.summary = summary
    await session.commit()
    return summary


# --------------------------------------------------------------------- 长期记忆
_PREF_PATTERNS = [
    (r"我(?:更|最)?(?:喜欢|偏好|习惯|倾向于)(.{2,60})", "preference"),
    (r"我(?:是|在|正在)(?:学|学习|做|开发)(.{2,60})", "profile"),
    (r"我(?:用|使用|装)(?:的是|了)?(.{2,60})", "profile"),
    (r"(?:以后|以后都|请)(?:要|请)?(.{4,60})", "preference"),
    (r"记住[:：]?(.{2,80})", "fact"),
    (r"我(?:想|要|计划)(?:学|做)(.{2,60})", "goal"),
]


def extract_candidate_memories(user_text: str) -> list[tuple[str, str]]:
    """启发式抽取值得长期记住的信息（无需额外 LLM 调用）。"""
    found: list[tuple[str, str]] = []
    text = user_text.strip()
    if len(text) < 4:
        return found
    for pattern, kind in _PREF_PATTERNS:
        for match in re.finditer(pattern, text):
            snippet = match.group(0).strip("。！？,!? ")
            if 4 <= len(snippet) <= 100:
                found.append((snippet, kind))
    # 去重保序
    seen: set[str] = set()
    uniq: list[tuple[str, str]] = []
    for content, kind in found:
        key = content[:40]
        if key in seen:
            continue
        seen.add(key)
        uniq.append((content, kind))
    return uniq[:3]


async def add_memory(
    session: AsyncSession,
    store: QdrantStore | None,
    *,
    user_id: int,
    content: str,
    kind: str = "fact",
    tags: str | None = None,
    conversation_id: str | None = None,
    importance: int = 3,
) -> MemoryItem:
    content = content.strip()
    existing = (
        await session.execute(
            select(MemoryItem).where(MemoryItem.user_id == user_id, MemoryItem.content == content)
        )
    ).scalars().first()
    if existing:
        return existing

    item = MemoryItem(
        user_id=user_id,
        kind=kind,
        content=content,
        tags=tags,
        source_conversation=conversation_id,
        importance=importance,
    )
    session.add(item)
    await session.commit()
    await session.refresh(item)
    if store is not None:
        try:
            await store.upsert_memory(memory_id=item.id, content=content, kind=kind)
            item.indexed = True
            await session.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("长期记忆写入向量库失败(不影响主流程): %s", exc)
    return item


async def recall_memories(
    session: AsyncSession,
    store: QdrantStore | None,
    *,
    user_id: int,
    query: str,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    if store is not None:
        try:
            vector_hits = await store.search_memory(query, top_k=top_k * 2)
            ids = [h["memory_id"] for h in vector_hits if h.get("memory_id") is not None]
            if ids:
                rows = (
                    await session.execute(
                        select(MemoryItem).where(
                            MemoryItem.id.in_(ids), MemoryItem.user_id == user_id, MemoryItem.active.is_(True)
                        )
                    )
                ).scalars().all()
                by_id = {r.id: r for r in rows}
                for hit in vector_hits:
                    row = by_id.get(hit["memory_id"])
                    if row is None:
                        continue
                    hits.append(
                        {
                            "id": row.id,
                            "content": row.content,
                            "kind": row.kind,
                            "tags": row.tags,
                            "importance": row.importance,
                            "score": hit["score"],
                            "created_at": row.created_at.isoformat(),
                        }
                    )
        except Exception as exc:  # noqa: BLE001
            logger.warning("向量召回记忆失败，降级关键词匹配: %s", exc)

    if not hits:
        rows = (
            await session.execute(
                select(MemoryItem)
                .where(MemoryItem.user_id == user_id, MemoryItem.active.is_(True))
                .order_by(desc(MemoryItem.importance), desc(MemoryItem.id))
                .limit(top_k)
            )
        ).scalars().all()
        hits = [
            {
                "id": r.id,
                "content": r.content,
                "kind": r.kind,
                "tags": r.tags,
                "importance": r.importance,
                "score": 0.0,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]

    hits = hits[:top_k]
    if hits:
        ids = [h["id"] for h in hits]
        rows = (
            await session.execute(select(MemoryItem).where(MemoryItem.id.in_(ids)))
        ).scalars().all()
        from app.db.models import utcnow

        for row in rows:
            row.access_count += 1
            row.last_accessed_at = utcnow()
        await session.commit()
    return hits


async def list_memories(session: AsyncSession, user_id: int = 1) -> list[MemoryItem]:
    return list(
        (
            await session.execute(
                select(MemoryItem)
                .where(MemoryItem.user_id == user_id)
                .order_by(desc(MemoryItem.importance), desc(MemoryItem.id))
            )
        ).scalars().all()
    )


async def delete_memory(
    session: AsyncSession, store: QdrantStore | None, memory_id: int
) -> bool:
    row = await session.get(MemoryItem, memory_id)
    if row is None:
        return False
    await session.delete(row)
    await session.commit()
    if store is not None:
        try:
            await store.delete_memory(memory_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("删除记忆向量失败: %s", exc)
    return True


async def clear_memories(session: AsyncSession, user_id: int = 1) -> int:
    result = await session.execute(delete(MemoryItem).where(MemoryItem.user_id == user_id))
    await session.commit()
    return int(result.rowcount or 0)


async def memory_stats(session: AsyncSession, user_id: int = 1) -> dict[str, Any]:
    total = (
        await session.execute(
            select(func.count(MemoryItem.id)).where(MemoryItem.user_id == user_id)
        )
    ).scalar_one()
    by_kind = (
        await session.execute(
            select(MemoryItem.kind, func.count(MemoryItem.id))
            .where(MemoryItem.user_id == user_id)
            .group_by(MemoryItem.kind)
        )
    ).all()
    return {"total": int(total), "by_kind": {k: int(v) for k, v in by_kind}}