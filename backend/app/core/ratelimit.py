"""Per-key rate limiting (fixed window in Redis) and monthly run quotas for plan enforcement.
Both fail open if Redis is unreachable, so an infrastructure blip never takes the API down."""
import hashlib
import time
from datetime import datetime, timezone

from fastapi import Depends, Header, HTTPException, Request

from app.core.config import settings
from app.services.event_bus import EventBus, get_event_bus


async def rate_limit(request: Request, x_api_key: str | None = Header(None, alias="X-API-Key"),
                     bus: EventBus = Depends(get_event_bus)) -> None:
    plan, ident = "anonymous", request.client.host if request.client else "unknown"
    if x_api_key:
        plan = settings.api_keys.get(x_api_key, "")
        if not plan or plan not in settings.plan_limits:
            raise HTTPException(401, "Invalid API key")
        ident = "key:" + hashlib.sha256(x_api_key.encode()).hexdigest()[:16]
    request.state.plan, request.state.ident = plan, ident
    window = int(time.time() // 60)
    try:
        key = f"rl:{ident}:{window}"
        n = await bus.redis.incr(key)
        if n == 1:
            await bus.redis.expire(key, 70)
    except Exception:
        return
    limit = settings.plan_limits[plan]["rpm"]
    if n > limit:
        raise HTTPException(429, f"Rate limit of {limit} requests/minute exceeded",
                            headers={"Retry-After": str(60 - int(time.time() % 60))})


def month_key(ident: str) -> str:
    return f"usage:{ident}:{datetime.now(timezone.utc):%Y%m}:runs"


async def run_quota(request: Request, _: None = Depends(rate_limit), bus: EventBus = Depends(get_event_bus)) -> None:
    plan, ident = request.state.plan, request.state.ident
    try:
        used = await bus.redis.incr(month_key(ident))
        if used == 1:
            await bus.redis.expire(month_key(ident), 40 * 86400)
    except Exception:
        return
    cap = settings.plan_limits[plan]["runs_per_month"]
    if used > cap:
        raise HTTPException(402, f"Monthly agent-run quota ({cap}) reached on the {plan} plan. Upgrade to continue.")
