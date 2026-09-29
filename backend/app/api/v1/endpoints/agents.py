"""Agent mesh endpoints: trigger runs, list products/runs, stream the live execution trace (SSE)."""
import asyncio
import json
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.supervisor import execute_run, start_run
from app.core.config import settings
from app.core.database import get_session
from app.core.ratelimit import run_quota
from app.models.models import AgentRun, InventoryLevel, Product
from app.schemas import ProductOut, RunAccepted, RunOut, RunRequest
from app.services.event_bus import EventBus, get_event_bus

router = APIRouter(prefix="/agents", tags=["agents"])
TERMINAL = {"run.completed", "run.failed"}


@router.get("/products", response_model=list[ProductOut])
async def list_products(session: AsyncSession = Depends(get_session)) -> list[ProductOut]:
    products = (await session.execute(select(Product).order_by(Product.sku))).scalars().all()
    stock = dict((await session.execute(
        select(InventoryLevel.product_id, func.sum(InventoryLevel.on_hand - InventoryLevel.reserved)).group_by(InventoryLevel.product_id)
    )).all())
    last: dict[uuid.UUID, dict] = {}
    for run in (await session.execute(
        select(AgentRun).where(AgentRun.status == "completed").order_by(AgentRun.created_at.desc()).limit(200)
    )).scalars():
        last.setdefault(run.product_id, run.decision or {})
    return [ProductOut(id=p.id, sku=p.sku, name=p.name, category=p.category, cost=p.cost, current_price=p.current_price,
                       map_price=p.map_price, available_units=int(stock.get(p.id, 0) or 0), last_decision=last.get(p.id))
            for p in products]


@router.post("/run", response_model=RunAccepted, status_code=202)
async def run_agents(body: RunRequest, tasks: BackgroundTasks, session: AsyncSession = Depends(get_session),
                     bus: EventBus = Depends(get_event_bus), idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
                     _: None = Depends(run_quota)) -> RunAccepted:
    """Idempotent: repeating a request with the same Idempotency-Key returns the original run instead of a new one."""
    if idempotency_key:
        try:
            prior = await bus.redis.get(f"idem:{idempotency_key}")
        except Exception:
            prior = None
        if prior:
            return RunAccepted(run_id=uuid.UUID(prior), stream_url=f"{settings.api_prefix}/agents/runs/{prior}/stream")
    try:
        run = await start_run(session, body.model_dump(mode="json"))
    except LookupError:
        raise HTTPException(404, "Product not found")
    if idempotency_key:
        try:
            await bus.redis.set(f"idem:{idempotency_key}", str(run.id), ex=86400, nx=True)
        except Exception:
            pass
    tasks.add_task(execute_run, run.id)
    return RunAccepted(run_id=run.id, stream_url=f"{settings.api_prefix}/agents/runs/{run.id}/stream")


@router.get("/runs", response_model=list[RunOut])
async def list_runs(limit: int = 20, session: AsyncSession = Depends(get_session)) -> list[AgentRun]:
    q = select(AgentRun).order_by(AgentRun.created_at.desc()).limit(min(limit, 100))
    return list((await session.execute(q)).scalars())


@router.get("/runs/{run_id}", response_model=RunOut)
async def get_run(run_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> AgentRun:
    run = await session.get(AgentRun, run_id)
    if run is None:
        raise HTTPException(404, "Run not found")
    return run


@router.post("/runs/{run_id}/apply", response_model=RunOut)
async def apply_run(run_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> AgentRun:
    run = await session.get(AgentRun, run_id)
    if run is None:
        raise HTTPException(404, "Run not found")
    d = run.decision or {}
    if run.status != "completed" or d.get("action") != "reprice" or not d.get("approved"):
        raise HTTPException(409, "Only approved repricing decisions can be applied")
    if run.applied:
        raise HTTPException(409, "Decision already applied")
    product = await session.get(Product, run.product_id)
    product.current_price = d["new_price"]
    run.applied, run.decision = True, {**d, "applied": True}
    await session.commit()
    return run


@router.get("/runs/{run_id}/stream")
async def stream_run(run_id: uuid.UUID, request: Request, session: AsyncSession = Depends(get_session),
                     bus: EventBus = Depends(get_event_bus)) -> StreamingResponse:
    run = await session.get(AgentRun, run_id)
    if run is None:
        raise HTTPException(404, "Run not found")
    finished_snapshot = None
    if run.status != "running" and await bus.run_stream_length(run_id) == 0:
        # trace stream already expired: replay the persisted outcome
        finished_snapshot = {"type": "run.completed" if run.status == "completed" else "run.failed", "node": None,
                             "ts": (run.finished_at or run.created_at).isoformat(),
                             "data": run.decision or {"error": run.error}}

    async def events():
        if finished_snapshot:
            yield f"data: {json.dumps(finished_snapshot)}\n\n"
            return
        last = "0-0"
        while not await request.is_disconnected():
            items = await bus.read_run_events(run_id, last, block_ms=10_000)
            if not items:
                yield ": keep-alive\n\n"
                continue
            for entry_id, ev in items:
                last = entry_id
                yield f"id: {entry_id}\ndata: {json.dumps(ev)}\n\n"
                if ev["type"] in TERMINAL:
                    return
            await asyncio.sleep(0)

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
