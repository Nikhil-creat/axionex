"""Plans and usage metering (the commercial layer)."""
from fastapi import APIRouter, Depends, Request

from app.core.config import settings
from app.core.ratelimit import month_key, rate_limit
from app.services.event_bus import EventBus, get_event_bus

router = APIRouter(prefix="/billing", tags=["billing"])

PLANS = [
    {"id": "starter", "name": "Starter", "price_usd_month": 0, "skus": 3, "features": ["50 agent runs / month", "Forecasts & what-if simulator", "Community support"]},
    {"id": "growth", "name": "Growth", "price_usd_month": 99, "skus": 100, "features": ["2,000 agent runs / month", "Webhook automation", "Price lab (bandit experiments)", "Email support"]},
    {"id": "scale", "name": "Scale", "price_usd_month": 499, "skus": 2000, "features": ["50,000 agent runs / month", "Priority support", "Custom guardrail rules", "Optional performance fee on verified profit uplift"]},
]


@router.get("/plans")
async def plans() -> list[dict]:
    return PLANS


@router.get("/usage")
async def usage(request: Request, _: None = Depends(rate_limit), bus: EventBus = Depends(get_event_bus)) -> dict:
    plan, ident = request.state.plan, request.state.ident
    try:
        used = int(await bus.redis.get(month_key(ident)) or 0)
    except Exception:
        used = 0
    lim = settings.plan_limits[plan]
    return {"plan": plan, "runs_used": used, "runs_limit": lim["runs_per_month"], "rpm_limit": lim["rpm"]}
