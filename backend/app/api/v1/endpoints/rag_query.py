"""RAG endpoints: ingest market intelligence, ask grounded questions."""
from fastapi import APIRouter, Depends

from app.schemas import RagAnswer, RagIngestRequest, RagQueryRequest
from app.services.rag_engine import RagEngine, get_rag_engine

router = APIRouter(prefix="/rag", tags=["rag"])


@router.post("/ingest", status_code=201)
async def ingest(body: RagIngestRequest, rag: RagEngine = Depends(get_rag_engine)) -> dict:
    return {"chunks_indexed": await rag.ingest([d.model_dump() for d in body.documents])}


@router.post("/query", response_model=RagAnswer)
async def query(body: RagQueryRequest, rag: RagEngine = Depends(get_rag_engine)) -> dict:
    return await rag.answer(body.question, body.k, body.sku, body.kind)
