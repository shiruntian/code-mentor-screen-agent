"""知识库：文档入库（切片→向量化→Qdrant）、检索调试、重建索引。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_id
from app.core.errors import AppError, NotFoundError
from app.core.state import state
from app.db.base import get_db
from app.db.models import KnowledgeDoc
from app.rag.chunker import chunk_text
from app.rag.seed import SEED_DOCS
from app.schemas.api import KnowledgeCreate, KnowledgeSearch

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


def _serialize(doc: KnowledgeDoc) -> dict[str, Any]:
    return {
        "id": doc.id,
        "title": doc.title,
        "source": doc.source,
        "tags": doc.tags,
        "kind": getattr(doc, "kind", "doc") or "doc",
        "target": getattr(doc, "target", "both") or "both",
        "char_count": doc.char_count,
        "chunk_count": doc.chunk_count,
        "preview": (doc.content or "")[:160],
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
    }


async def ingest_document(
    session: AsyncSession,
    *,
    title: str,
    content: str,
    source: str | None,
    tags: str | None,
    user_id: int,
    kind: str = "doc",
    target: str = "both",
) -> KnowledgeDoc:
    if state.store is None and kind != "guide":
        raise AppError("向量库未初始化", hint="请重启后端服务")
    kind = "guide" if kind == "guide" else "doc"
    target = target if target in ("chat", "screen", "both") else "both"
    if kind == "guide" and not (content or "").strip():
        raise AppError("提示知识的内容不能为空")

    chunks = [] if kind == "guide" else chunk_text(content)
    if kind == "doc" and not chunks:
        raise AppError("文档内容为空或无法切分")

    doc = KnowledgeDoc(
        user_id=user_id,
        title=title[:200],
        source=(source or "")[:255] or None,
        tags=(tags or "")[:255] or None,
        content=content,
        kind=kind,
        target=target,
        char_count=len(content),
    )
    session.add(doc)
    await session.commit()
    await session.refresh(doc)

    if kind == "guide":
        # 提示知识直接注入提示词，不参与向量检索
        from app.rag.guides import invalidate_cache

        invalidate_cache()
        doc.chunk_count = 0
        await session.commit()
        return doc

    count = await state.store.upsert_knowledge(
        doc_id=doc.id,
        title=doc.title,
        source=doc.source or "知识库",
        chunks=[c.text for c in chunks],
        tags=doc.tags,
    )
    doc.chunk_count = count
    await session.commit()
    await session.refresh(doc)
    return doc


@router.get("")
async def list_docs(
    session: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict[str, Any]:
    rows = (
        await session.execute(
            select(KnowledgeDoc)
            .where(KnowledgeDoc.user_id == user_id)
            .order_by(desc(KnowledgeDoc.id))
            .limit(200)
        )
    ).scalars().all()
    return {"items": [_serialize(d) for d in rows], "total": len(rows)}


@router.post("")
async def create_doc(
    payload: KnowledgeCreate,
    session: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict[str, Any]:
    doc = await ingest_document(
        session,
        title=payload.title,
        content=payload.content,
        source=payload.source,
        tags=payload.tags,
        user_id=user_id,
        kind=getattr(payload, "kind", "doc"),
        target=getattr(payload, "target", "both"),
    )
    return _serialize(doc)


@router.delete("/{doc_id}")
async def delete_doc(
    doc_id: int,
    session: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict[str, Any]:
    doc = await session.get(KnowledgeDoc, doc_id)
    if doc is None or doc.user_id != user_id:
        raise NotFoundError("文档不存在")
    await session.delete(doc)
    await session.commit()
    try:
        from app.rag.guides import invalidate_cache

        invalidate_cache()
    except Exception:  # noqa: BLE001
        pass
    if state.store is not None:
        try:
            await state.store.delete_knowledge_doc(doc_id)
        except Exception:  # noqa: BLE001
            pass
    return {"ok": True, "deleted": doc_id}


@router.post("/search")
async def search(
    payload: KnowledgeSearch,
    user_id: int = Depends(get_current_user_id),
) -> dict[str, Any]:
    if state.store is None:
        raise AppError("向量库未初始化")
    hits = await state.store.search_knowledge(payload.query, top_k=max(1, min(payload.top_k, 10)))
    return {"query": payload.query, "hits": hits, "count": len(hits)}


@router.get("/stats")
async def stats(session: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    doc_count = int((await session.execute(select(func.count(KnowledgeDoc.id)))).scalar_one())
    chunk_total = int(
        (await session.execute(select(func.coalesce(func.sum(KnowledgeDoc.chunk_count), 0)))).scalar_one()
    )
    vector = await state.store.stats() if state.store is not None else {}
    return {"documents": doc_count, "chunks": chunk_total, "vector": vector}


@router.post("/seed")
async def seed(
    session: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict[str, Any]:
    existing = {
        t
        for t in (
            await session.execute(select(KnowledgeDoc.title).where(KnowledgeDoc.user_id == user_id))
        ).scalars().all()
    }
    created = 0
    for item in SEED_DOCS:
        if item["title"] in existing:
            continue
        await ingest_document(
            session,
            title=item["title"],
            content=item["content"],
            source=item.get("source", "内置知识包"),
            tags=item.get("tags"),
            user_id=user_id,
        )
        created += 1
    return {"ok": True, "created": created}


@router.post("/reindex")
async def reindex(
    session: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict[str, Any]:
    if state.store is None:
        raise AppError("向量库未初始化")
    rows = (
        await session.execute(select(KnowledgeDoc).where(KnowledgeDoc.user_id == user_id))
    ).scalars().all()
    total = 0
    for doc in rows:
        chunks = chunk_text(doc.content or "")
        total += await state.store.upsert_knowledge(
            doc_id=doc.id,
            title=doc.title,
            source=doc.source or "知识库",
            chunks=[c.text for c in chunks],
            tags=doc.tags,
        )
        doc.chunk_count = len(chunks)
    await session.commit()
    return {"ok": True, "documents": len(rows), "chunks": total}