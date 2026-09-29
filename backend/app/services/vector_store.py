"""Qdrant vector memory + pluggable text embedder (sentence-transformers with hashing fallback)."""
import asyncio
import hashlib
import logging
import math
import re
from functools import lru_cache
from typing import Any

from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qm

from app.core.config import settings

logger = logging.getLogger("optimarket.vector")
_TOKEN = re.compile(r"[a-z0-9]+")


class Embedder:
    """Text -> unit vector. Falls back to a deterministic signed hashing embedder offline."""

    def __init__(self) -> None:
        self.dim = settings.embedding_dim
        self._model: Any = None
        self._lock = asyncio.Lock()
        self.backend = settings.embedding_backend

    def _load(self) -> None:
        if self.backend != "sentence-transformers" or self._model is not None:
            return
        try:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(settings.embedding_model)
            self.dim = int(self._model.get_sentence_embedding_dimension())
        except Exception as exc:  # offline / model not cached
            logger.warning("sentence-transformers unavailable (%s); using hashing embedder", exc)
            self.backend = "hash"
            self.dim = settings.embedding_dim

    def _hash_embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        tokens = _TOKEN.findall(text.lower())
        grams = tokens + [f"{a}_{b}" for a, b in zip(tokens, tokens[1:])]
        for g in grams:
            h = int.from_bytes(hashlib.blake2b(g.encode(), digest_size=8).digest(), "big")
            vec[h % self.dim] += 1.0 if (h >> 63) & 1 else -1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def _embed_sync(self, texts: list[str]) -> list[list[float]]:
        self._load()
        if self.backend == "hash" or self._model is None:
            return [self._hash_embed(t) for t in texts]
        arr = self._model.encode(texts, normalize_embeddings=True, batch_size=32, show_progress_bar=False)
        return [row.tolist() for row in arr]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        async with self._lock:  # serialise model load; inference itself runs off-loop
            return await asyncio.to_thread(self._embed_sync, texts)


class VectorStore:
    def __init__(self) -> None:
        self.client = AsyncQdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key)
        self._ready: set[str] = set()

    async def ensure_collection(self, name: str, dim: int) -> None:
        if name in self._ready:
            return
        if not await self.client.collection_exists(name):
            await self.client.create_collection(
                name, vectors_config=qm.VectorParams(size=dim, distance=qm.Distance.COSINE)
            )
            for field in ("sku", "kind"):
                await self.client.create_payload_index(name, field, qm.PayloadSchemaType.KEYWORD)
        self._ready.add(name)

    async def upsert(self, name: str, dim: int, items: list[tuple[str, list[float], dict[str, Any]]]) -> int:
        await self.ensure_collection(name, dim)
        points = [qm.PointStruct(id=pid, vector=vec, payload=payload) for pid, vec, payload in items]
        await self.client.upsert(name, points=points, wait=True)
        return len(points)

    async def search(
        self, name: str, dim: int, vector: list[float], limit: int = 6, filters: dict[str, str] | None = None
    ) -> list[dict[str, Any]]:
        await self.ensure_collection(name, dim)
        flt = None
        if filters:
            flt = qm.Filter(must=[
                qm.FieldCondition(key=k, match=qm.MatchValue(value=v)) for k, v in filters.items() if v
            ])
        res = await self.client.query_points(name, query=vector, limit=limit, query_filter=flt, with_payload=True)
        return [{"id": str(p.id), "score": float(p.score), "payload": p.payload or {}} for p in res.points]

    async def healthy(self) -> bool:
        try:
            await self.client.get_collections()
            return True
        except Exception:
            return False


@lru_cache
def get_embedder() -> Embedder:
    return Embedder()


@lru_cache
def get_vector_store() -> VectorStore:
    return VectorStore()
