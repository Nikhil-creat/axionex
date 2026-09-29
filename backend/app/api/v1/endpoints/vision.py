"""Computer-vision endpoints: analyse product imagery and search visually similar products."""
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_session
from app.models.models import VisionAnalysis
from app.services.cnn_pipeline import VisionPipeline, get_vision_pipeline
from app.services.vector_store import VectorStore, get_vector_store
import uuid

router = APIRouter(prefix="/vision", tags=["vision"])


async def _read(file: UploadFile) -> bytes:
    if not (file.content_type or "").startswith("image/"):
        raise HTTPException(415, "Upload an image file")
    data = await file.read()
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"Image exceeds {settings.max_upload_mb} MB")
    return data


@router.post("/analyze")
async def analyze(file: UploadFile = File(...), sku: str | None = Form(None), index: bool = Form(False),
                  pipe: VisionPipeline = Depends(get_vision_pipeline), store: VectorStore = Depends(get_vector_store),
                  session: AsyncSession = Depends(get_session)) -> dict:
    data = await _read(file)
    try:
        result = await pipe.analyze(data)
    except Exception:
        raise HTTPException(422, "Could not decode image")
    embedding = result.pop("embedding")
    indexed = False
    if index:
        await store.upsert(settings.visual_collection, pipe.embedding_dim,
                           [(str(uuid.uuid4()), embedding, {"sku": sku or "", "kind": "product_image", "filename": file.filename})])
        indexed = True
    session.add(VisionAnalysis(sku=sku, filename=file.filename or "upload", result=result))
    await session.commit()
    return {**result, "indexed": indexed}


@router.post("/similar")
async def similar(file: UploadFile = File(...), k: int = Form(5),
                  pipe: VisionPipeline = Depends(get_vision_pipeline), store: VectorStore = Depends(get_vector_store)) -> dict:
    data = await _read(file)
    result = await pipe.analyze(data)
    hits = await store.search(settings.visual_collection, pipe.embedding_dim, result["embedding"], limit=min(k, 20))
    return {"matches": [{"score": round(h["score"], 4), **h["payload"]} for h in hits]}
