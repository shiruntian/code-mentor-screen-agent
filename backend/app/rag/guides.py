"""提示知识（guide）：不参与向量检索，直接注入到对应智能体的提示词里。

和普通知识库文档的区别：
- **doc**：可被 knowledge_search 检索，用来回答"是什么/怎么做"；
- **guide**：是一段"行为准则"，每轮都原样放进系统提示词，用来约束模型怎么做事。

按 `target` 分发给不同智能体：`chat`（对话）、`screen`（屏幕控制）、`both`。
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import select

from app.core.logging import get_logger
from app.db.base import session_scope
from app.db.models import KnowledgeDoc

logger = get_logger(__name__)

TARGETS = {"chat", "screen", "both"}
_TTL_S = 20.0
_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}


def invalidate_cache() -> None:
    _CACHE.clear()


async def list_guides(target: str) -> list[dict[str, Any]]:
    """取某个智能体可用的提示知识（含 both），带 20 秒缓存。"""
    target = target if target in TARGETS else "chat"
    cached = _CACHE.get(target)
    now = time.time()
    if cached and now - cached[0] < _TTL_S:
        return cached[1]
    try:
        async with session_scope() as session:
            rows = (
                (
                    await session.execute(
                        select(KnowledgeDoc)
                        .where(
                            KnowledgeDoc.kind == "guide",
                            KnowledgeDoc.target.in_([target, "both"]),
                        )
                        .order_by(KnowledgeDoc.id)
                        .limit(30)
                    )
                )
                .scalars()
                .all()
            )
        items = [
            {
                "id": r.id,
                "title": r.title,
                "content": (r.content or "").strip(),
                "source": r.source or "",
            }
            for r in rows
            if (r.content or "").strip()
        ]
    except Exception as exc:  # noqa: BLE001
        logger.warning("读取提示知识失败: %s", exc)
        items = []
    _CACHE[target] = (now, items)
    return items


def render_guides(items: list[dict[str, Any]], heading: str = "行为准则（来自知识库的提示知识，优先级高于默认习惯）") -> str:
    """把提示知识拼成提示词片段；没有就返回空串。"""
    if not items:
        return ""
    lines = [f"## {heading}"]
    for item in items:
        body = item["content"].strip()
        if not body:
            continue
        lines.append(f"### {item['title']}")
        lines.append(body[:1200])
    if len(lines) <= 1:
        return ""
    return "\n".join(lines) + "\n"


async def guide_context(target: str) -> str:
    """给调用方直接用的便捷函数。"""
    return render_guides(await list_guides(target))

async def upsert_guide(
    *,
    title: str,
    content: str,
    target: str = "screen",
    source: str = "retro",
) -> bool:
    """按标题去重写一条提示知识；已存在则合并内容。"""
    title = (title or "").strip()[:60]
    content = (content or "").strip()
    if not title or not content:
        return False
    try:
        async with session_scope() as session:
            row = (
                await session.execute(
                    select(KnowledgeDoc).where(KnowledgeDoc.title == title).limit(1)
                )
            ).scalar_one_or_none()
            if row is None:
                session.add(
                    KnowledgeDoc(
                        user_id=1,
                        title=title,
                        source=source,
                        tags="自动复盘",
                        content=content,
                        kind="guide",
                        target=target if target in TARGETS else "screen",
                        char_count=len(content),
                        chunk_count=0,
                    )
                )
            else:
                if content in (row.content or ""):
                    return False
                merged = ((row.content or "").rstrip() + "\n" + content).strip()
                row.content = merged[:2000]
                row.char_count = len(row.content)
            await session.commit()
        invalidate_cache()
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("写入复盘经验失败: %s", exc)
        return False
