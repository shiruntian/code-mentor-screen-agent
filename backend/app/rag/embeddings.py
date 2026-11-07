"""Embedding 后端。

默认使用「离线哈希向量」：字符 n-gram + 词元哈希到固定维度，无需联网、无需下载模型，
在中文技术问答这种词面重合度高的场景下召回效果足够好；同时保留在线 Embedding
（OpenAI 兼容 /embeddings 接口）与本地 sentence-transformers 两种升级路径。
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from typing import Any, Protocol

import httpx

from app.core.logging import get_logger

logger = get_logger(__name__)

_WORD = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*|\d+")
_CJK = re.compile(r"[\u4e00-\u9fff]+")


class Embedder(Protocol):
    name: str
    dim: int

    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...


def tokenize(text: str) -> list[str]:
    """中英混合分词：中文按 1~2 字滑窗，英文/数字按标识符切分（含下划线拆分）。"""
    tokens: list[str] = []
    lowered = text.lower()
    for run in _CJK.findall(lowered):
        tokens.extend(run)
        tokens.extend(run[i : i + 2] for i in range(len(run) - 1))
    for word in _WORD.findall(lowered):
        tokens.append(word)
        if "_" in word:
            tokens.extend(p for p in word.split("_") if p)
    return tokens


def _hash(token: str, modulo: int, salt: int = 0) -> tuple[int, float]:
    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8, salt=str(salt).encode()).digest()
    value = int.from_bytes(digest, "big")
    sign = 1.0 if (value >> 63) & 1 else -1.0
    return value % modulo, sign


class HashEmbedder:
    """确定性离线向量（hashing trick）。"""

    name = "hash-ngram"

    def __init__(self, dim: int = 512):
        self.dim = dim

    def _encode(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        if not text.strip():
            return vec
        counts = Counter(tokenize(text))
        for token, tf in counts.items():
            idx, sign = _hash(token, self.dim)
            vec[idx] += sign * (1.0 + math.log(tf))
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._encode(t) for t in texts]

    async def embed_query(self, text: str) -> list[float]:
        return self._encode(text)


class ApiEmbedder:
    """OpenAI 兼容的远程 Embedding。"""

    name = "api"

    def __init__(self, base_url: str, api_key: str, model: str, dim: int = 1024):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.dim = dim

    async def _call(self, texts: list[str]) -> list[list[float]]:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        payload: dict[str, Any] = {"model": self.model, "input": texts}
        if "text-embedding-v3" in self.model:
            payload["dimensions"] = self.dim
            payload["encoding_format"] = "float"
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(f"{self.base_url}/embeddings", headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json().get("data", [])
        data.sort(key=lambda d: d.get("index", 0))
        vectors = [d["embedding"] for d in data]
        if vectors:
            self.dim = len(vectors[0])
        return vectors

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), 16):
            out.extend(await self._call(texts[i : i + 16]))
        return out

    async def embed_query(self, text: str) -> list[float]:
        return (await self._call([text]))[0]


class LocalEmbedder:
    """可选的本地向量模型（需要自行 pip install sentence-transformers）。"""

    name = "sentence-transformers"

    def __init__(self, model_name: str = "BAAI/bge-small-zh-v1.5"):
        from sentence_transformers import SentenceTransformer  # type: ignore

        self._model = SentenceTransformer(model_name)
        self.dim = int(self._model.get_sentence_embedding_dimension() or 512)
        self.name = model_name

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        import asyncio

        return await asyncio.to_thread(
            lambda: [v.tolist() for v in self._model.encode(texts, normalize_embeddings=True)]
        )

    async def embed_query(self, text: str) -> list[float]:
        return (await self.embed_documents([text]))[0]


def build_embedder(config: dict[str, Any] | None = None) -> Embedder:
    config = config or {}
    provider = (config.get("provider") or "hash").lower()
    dim = int(config.get("dim") or 512)

    if provider == "api":
        base_url = config.get("base_url") or "https://dashscope.aliyuncs.com/compatible-mode/v1"
        api_key = config.get("api_key") or ""
        model = config.get("model") or "text-embedding-v3"
        if api_key:
            return ApiEmbedder(base_url=base_url, api_key=api_key, model=model, dim=dim)
        logger.warning("未提供 Embedding API Key，回退到离线哈希向量")
    elif provider == "local":
        try:
            return LocalEmbedder(config.get("model") or "BAAI/bge-small-zh-v1.5")
        except Exception as exc:  # noqa: BLE001
            logger.warning("本地向量模型加载失败(%s)，回退到离线哈希向量", exc)
    return HashEmbedder(dim=dim)