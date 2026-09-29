"""Real-time RAG: chunk -> embed -> Qdrant -> recency-aware rerank -> grounded answer."""
import hashlib
import logging
import math
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

import httpx
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.core.config import settings
from app.core.reliability import CircuitBreaker, retry_async
from app.services.vector_store import Embedder, VectorStore, get_embedder, get_vector_store

logger = logging.getLogger("optimarket.rag")
llm_breaker = CircuitBreaker(failures=3, reset_seconds=45)

SYSTEM_PROMPT = (
    "You are the market-intelligence analyst inside AxioNex, a pricing and inventory platform for D2C brands. "
    "Answer ONLY from the numbered context. Cite sources like [1]. If the context is insufficient, say so plainly. "
    "Be concise and quantitative."
)


class RagEngine:
    def __init__(self, store: VectorStore, embedder: Embedder) -> None:
        self.store, self.embedder = store, embedder
        self.splitter = RecursiveCharacterTextSplitter(chunk_size=700, chunk_overlap=100)

    async def ingest(self, documents: list[dict[str, Any]]) -> int:
        chunks: list[tuple[str, dict[str, Any]]] = []
        now = datetime.now(timezone.utc).isoformat()
        for doc in documents:
            for i, piece in enumerate(self.splitter.split_text(doc["text"])):
                pid = str(uuid.uuid5(uuid.NAMESPACE_OID, hashlib.sha1(f"{doc.get('source')}|{piece}".encode()).hexdigest()))
                chunks.append((pid, {
                    "text": piece, "source": doc.get("source", "manual"), "kind": doc.get("kind", "market_trend"),
                    "sku": doc.get("sku") or "", "chunk": i, "ingested_at": now,
                }))
        if not chunks:
            return 0
        vectors = await self.embedder.embed([c[1]["text"] for c in chunks])
        items = [(pid, vec, payload) for (pid, payload), vec in zip(chunks, vectors)]
        return await self.store.upsert(settings.intel_collection, self.embedder.dim, items)

    async def retrieve(self, query: str, k: int = 6, sku: str | None = None, kind: str | None = None) -> list[dict[str, Any]]:
        (vec,) = await self.embedder.embed([query])
        filters = {k_: v for k_, v in {"sku": sku, "kind": kind}.items() if v}
        raw = await self.store.search(settings.intel_collection, self.embedder.dim, vec, limit=k * 3, filters=filters or None)
        now = datetime.now(timezone.utc)
        ranked = []
        for hit in raw:
            p = hit["payload"]
            try:
                age_days = max(0.0, (now - datetime.fromisoformat(p["ingested_at"])).total_seconds() / 86400)
            except Exception:
                age_days = 0.0
            recency = math.exp(-age_days / 45.0)  # market intel decays with a ~45 day time constant
            ranked.append({
                "text": p.get("text", ""), "source": p.get("source", ""), "kind": p.get("kind", ""),
                "score": round(hit["score"] * (0.75 + 0.25 * recency), 4),
            })
        ranked.sort(key=lambda r: r["score"], reverse=True)
        seen: set[str] = set()
        out = []
        for r in ranked:  # drop near-duplicate chunks
            key = r["text"][:80]
            if key not in seen:
                seen.add(key)
                out.append(r)
        return out[:k]

    async def answer(self, question: str, k: int = 6, sku: str | None = None, kind: str | None = None) -> dict[str, Any]:
        sources = await self.retrieve(question, k, sku, kind)
        if not sources:
            return {"answer": "No relevant market intelligence has been indexed yet.", "mode": "empty", "sources": []}
        if settings.anthropic_api_key and llm_breaker.allow():
            try:
                text = await retry_async(lambda: self._llm(question, sources), attempts=2)
                llm_breaker.record(True)
                return {"answer": text, "mode": "llm", "sources": sources}
            except Exception as exc:  # graceful degradation: extractive answer keeps the product usable
                llm_breaker.record(False)
                logger.warning("LLM synthesis failed (%s); using extractive fallback", exc)
        top = sources[:3]
        text = " ".join(f"{s['text'].strip()} [{i}]" for i, s in enumerate(top, 1))
        return {"answer": text, "mode": "extractive", "sources": sources}

    async def _llm(self, question: str, sources: list[dict[str, Any]]) -> str:
        context = "\n".join(f"[{i}] ({s['kind']}, {s['source']}) {s['text']}" for i, s in enumerate(sources, 1))
        async with httpx.AsyncClient(timeout=45) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": settings.anthropic_api_key or "",
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": settings.llm_model,
                    "max_tokens": settings.llm_max_tokens,
                    "system": SYSTEM_PROMPT,
                    "messages": [{"role": "user", "content": f"Context:\n{context}\n\nQuestion: {question}"}],
                },
            )
            resp.raise_for_status()
            return "".join(b.get("text", "") for b in resp.json()["content"] if b.get("type") == "text").strip()


@lru_cache
def get_rag_engine() -> RagEngine:
    return RagEngine(get_vector_store(), get_embedder())
