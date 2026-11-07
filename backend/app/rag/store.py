"""Qdrant 向量库封装：知识库集合 + 长期记忆集合。

默认走 Qdrant 官方 embedded(local) 模式，数据落盘在 data/qdrant，无需 Docker；
配置 QDRANT_MODE=remote 即可无缝切到 qdrant/qdrant 服务端。
"""

from __future__ import annotations

import uuid
from typing import Any

from qdrant_client import AsyncQdrantClient, models

from app.core.config import settings
from app.core.logging import get_logger
from app.rag.embeddings import Embedder, tokenize

logger = get_logger(__name__)

_NS = uuid.UUID("6f1d2c3a-8b4e-4a51-9b7e-3c2d1f0a9e88")


def _point_id(*parts: str) -> str:
    return str(uuid.uuid5(_NS, "|".join(parts)))


class QdrantStore:
    def __init__(self, client: AsyncQdrantClient, embedder: Embedder):
        self.client = client
        self.embedder = embedder
        self.dim = embedder.dim
        self._ready: set[str] = set()

    # ------------------------------------------------------------------ 基础
    @classmethod
    def connect(cls, embedder: Embedder) -> "QdrantStore":
        if settings.qdrant_mode == "remote":
            client = AsyncQdrantClient(
                url=settings.qdrant_url, api_key=settings.qdrant_api_key, timeout=15
            )
            logger.info("Qdrant 使用远程模式: %s", settings.qdrant_url)
        else:
            settings.qdrant_path.mkdir(parents=True, exist_ok=True)
            client = AsyncQdrantClient(path=str(settings.qdrant_path))
            logger.info("Qdrant 使用本地 embedded 模式: %s", settings.qdrant_path)
        return cls(client, embedder)

    async def ensure_collection(self, name: str) -> None:
        key = f"{name}:{self.dim}"
        if key in self._ready:
            return
        existing = {c.name for c in (await self.client.get_collections()).collections}
        if name in existing:
            info = await self.client.get_collection(name)
            size = info.config.params.vectors.size  # type: ignore[union-attr]
            if size != self.dim:
                logger.warning(
                    "集合 %s 维度 %s 与当前向量维度 %s 不一致，重建集合（需重新索引）", name, size, self.dim
                )
                await self.client.delete_collection(name)
                existing.discard(name)
        if name not in existing:
            await self.client.create_collection(
                collection_name=name,
                vectors_config=models.VectorParams(size=self.dim, distance=models.Distance.COSINE),
            )
            logger.info("已创建 Qdrant 集合 %s (dim=%s)", name, self.dim)
        self._ready.add(key)

    # ------------------------------------------------------------------ 知识库
    async def upsert_knowledge(
        self,
        *,
        doc_id: int,
        title: str,
        source: str,
        chunks: list[str],
        tags: str | None = None,
    ) -> int:
        await self.ensure_collection(settings.kb_collection)
        if not chunks:
            return 0
        vectors = await self.embedder.embed_documents(chunks)
        points = [
            models.PointStruct(
                id=_point_id("kb", str(doc_id), str(i)),
                vector=vector,
                payload={
                    "doc_id": doc_id,
                    "title": title,
                    "source": source,
                    "tags": tags or "",
                    "chunk_index": i,
                    "text": chunk,
                },
            )
            for i, (chunk, vector) in enumerate(zip(chunks, vectors, strict=False))
        ]
        await self.client.upsert(collection_name=settings.kb_collection, points=points, wait=True)
        return len(points)

    async def search_knowledge(
        self, query: str, *, top_k: int = 4, score_threshold: float = 0.12
    ) -> list[dict[str, Any]]:
        await self.ensure_collection(settings.kb_collection)
        vector = await self.embedder.embed_query(query)
        result = await self.client.query_points(
            collection_name=settings.kb_collection,
            query=vector,
            limit=max(top_k * 4, 12),
            with_payload=True,
            score_threshold=None,
        )
        q_tokens = set(tokenize(query))
        hits: list[dict[str, Any]] = []
        for point in result.points:
            payload = point.payload or {}
            text = str(payload.get("text", ""))
            overlap = 0.0
            if q_tokens:
                doc_tokens = set(tokenize(text))
                overlap = len(q_tokens & doc_tokens) / (len(q_tokens) ** 0.5 + 1e-6)
            lexical = min(overlap / 3.0, 1.0)
            blended = 0.62 * float(point.score) + 0.38 * lexical
            if blended < score_threshold:
                continue
            hits.append(
                {
                    "doc_id": payload.get("doc_id"),
                    "title": payload.get("title"),
                    "source": payload.get("source"),
                    "text": text,
                    "score": round(blended, 4),
                    "vector_score": round(float(point.score), 4),
                }
            )
        hits.sort(key=lambda h: h["score"], reverse=True)
        return hits[:top_k]

    async def delete_knowledge_doc(self, doc_id: int) -> None:
        await self.ensure_collection(settings.kb_collection)
        await self.client.delete(
            collection_name=settings.kb_collection,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="doc_id", match=models.MatchValue(value=doc_id)
                        )
                    ]
                )
            ),
            wait=True,
        )

    async def knowledge_count(self) -> int:
        await self.ensure_collection(settings.kb_collection)
        info = await self.client.get_collection(settings.kb_collection)
        return int(info.points_count or 0)

    # ------------------------------------------------------------------ 长期记忆
    async def upsert_memory(self, *, memory_id: int, content: str, kind: str) -> None:
        await self.ensure_collection(settings.memory_collection)
        vector = await self.embedder.embed_query(content)
        await self.client.upsert(
            collection_name=settings.memory_collection,
            points=[
                models.PointStruct(
                    id=_point_id("mem", str(memory_id)),
                    vector=vector,
                    payload={"memory_id": memory_id, "content": content, "kind": kind},
                )
            ],
            wait=True,
        )

    async def search_memory(self, query: str, *, top_k: int = 5) -> list[dict[str, Any]]:
        await self.ensure_collection(settings.memory_collection)
        vector = await self.embedder.embed_query(query)
        result = await self.client.query_points(
            collection_name=settings.memory_collection,
            query=vector,
            limit=max(top_k, 5),
            with_payload=True,
        )
        q_tokens = set(tokenize(query))
        hits = []
        for p in result.points:
            payload = p.payload or {}
            text = str(payload.get("content", ""))
            lexical = 0.0
            if q_tokens:
                lexical = len(q_tokens & set(tokenize(text))) / (len(q_tokens) ** 0.5 + 1e-6)
            hits.append(
                {
                    "memory_id": payload.get("memory_id"),
                    "content": text,
                    "kind": payload.get("kind"),
                    "score": round(0.6 * float(p.score) + 0.4 * min(lexical / 3.0, 1.0), 4),
                }
            )
        hits.sort(key=lambda h: h["score"], reverse=True)
        return hits[:top_k]

    async def delete_memory(self, memory_id: int) -> None:
        await self.ensure_collection(settings.memory_collection)
        await self.client.delete(
            collection_name=settings.memory_collection,
            points_selector=models.PointIdsList(points=[_point_id("mem", str(memory_id))]),
            wait=True,
        )

    async def stats(self) -> dict[str, Any]:
        try:
            kb = await self.knowledge_count()
            await self.ensure_collection(settings.memory_collection)
            mem = await self.client.get_collection(settings.memory_collection)
            return {
                "mode": settings.qdrant_mode,
                "dim": self.dim,
                "embedder": self.embedder.name,
                "knowledge_points": kb,
                "memory_points": int(mem.points_count or 0),
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("Qdrant 状态读取失败: %s", exc)
            return {"mode": settings.qdrant_mode, "dim": self.dim, "error": str(exc)}

    async def close(self) -> None:
        await self.client.close()