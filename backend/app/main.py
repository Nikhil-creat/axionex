"""AxioNex — FastAPI application entrypoint."""
import logging
import time
from collections import defaultdict
from uuid import uuid4
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.database import SessionLocal, engine
from app.services.event_bus import get_event_bus
from app.services.rag_engine import get_rag_engine
from app.services.seed import seed_demo_data
from app.services.vector_store import get_vector_store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("optimarket")


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.seed_demo_data:
        try:
            async with SessionLocal() as session:
                await seed_demo_data(session, get_rag_engine())
        except Exception:
            logger.exception("Demo seeding failed")
    yield
    await get_event_bus().close()
    await engine.dispose()


app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan,
              description=f"Autonomous multi-agent commerce mesh. Designed and developed by {settings.author_name}.")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"])


REQS: dict[tuple[str, int], int] = defaultdict(int)
LAT: dict[str, float] = defaultdict(float)


@app.middleware("http")
async def timing(request: Request, call_next):
    t0 = time.perf_counter()
    response = await call_next(request)
    dt = time.perf_counter() - t0
    REQS[(request.method, response.status_code)] += 1
    LAT["sum"] += dt
    LAT["count"] += 1
    response.headers["X-Request-ID"] = request.headers.get("X-Request-ID") or uuid4().hex[:12]
    response.headers["X-Process-Time-ms"] = f"{dt * 1000:.1f}"
    response.headers["X-Built-By"] = settings.author_name
    return response


app.include_router(api_router, prefix=settings.api_prefix)


@app.get("/metrics", tags=["ops"], response_class=PlainTextResponse)
async def metrics() -> str:
    """Prometheus text exposition."""
    lines = ["# TYPE axionex_http_requests_total counter"]
    lines += [f'axionex_http_requests_total{{method="{m}",status="{s}"}} {n}' for (m, s), n in sorted(REQS.items())]
    lines += ["# TYPE axionex_http_request_seconds_sum counter", f"axionex_http_request_seconds_sum {LAT['sum']:.6f}",
              "# TYPE axionex_http_request_seconds_count counter", f"axionex_http_request_seconds_count {int(LAT['count'])}"]
    return "\n".join(lines) + "\n"


@app.get("/ready", tags=["ops"])
async def ready() -> dict:
    """Readiness probe: 200 only when Postgres answers."""
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    return {"ready": True}


@app.get("/health", tags=["ops"])
async def health() -> dict:
    checks: dict[str, bool] = {}
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT PostGIS_Version()"))
        checks["postgres_postgis"] = True
    except Exception:
        checks["postgres_postgis"] = False
    try:
        checks["redis"] = await get_event_bus().ping()
    except Exception:
        checks["redis"] = False
    checks["qdrant"] = await get_vector_store().healthy()
    return {"status": "ok" if all(checks.values()) else "degraded", "checks": checks, "version": settings.app_version,
            "author": {"name": settings.author_name, "github": settings.author_github,
                       "linkedin": settings.author_linkedin, "email": settings.author_email}}
