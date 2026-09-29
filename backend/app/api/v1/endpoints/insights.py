"""Advanced analytics: demand forecast, Monte Carlo what-if simulator, Thompson-sampling price lab."""
from datetime import timedelta

import numpy as np
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.pricing_agent import fit_demand
from app.core.database import get_session
from app.models.models import PricePoint, Product
from app.services.event_bus import EventBus, get_event_bus
from app.services.experiments import ARMS, BanditStore, ThompsonBandit
from app.services.forecasting import forecast_demand
from app.services.simulation import simulate_price

router = APIRouter(prefix="/insights", tags=["insights"])


async def _load(session: AsyncSession, sku: str):
    product = (await session.execute(select(Product).where(Product.sku == sku))).scalar_one_or_none()
    if product is None:
        raise HTTPException(404, "Unknown SKU")
    pts = (await session.execute(select(PricePoint).where(PricePoint.product_id == product.id)
                                 .order_by(PricePoint.observed_at))).scalars().all()
    if len(pts) < 8:
        raise HTTPException(409, "Not enough demand history for this SKU")
    return product, pts


@router.get("/forecast/{sku}")
async def forecast(sku: str, horizon: int = 14, session: AsyncSession = Depends(get_session)) -> dict:
    _, pts = await _load(session, sku)
    horizon = min(max(horizon, 3), 60)
    res = forecast_demand([p.units_sold for p in pts], horizon)
    last = pts[-1].observed_at.date()
    hist = [{"date": p.observed_at.date().isoformat(), "units": p.units_sold} for p in pts[-45:]]
    offset = len(pts) - len(hist)
    res["anomalies"] = [{**a, "date": pts[a["index"]].observed_at.date().isoformat()} for a in res["anomalies"] if a["index"] >= offset]
    res["history"] = hist
    res["dates"] = [(last + timedelta(days=i + 1)).isoformat() for i in range(horizon)]
    return res


class SimulateRequest(BaseModel):
    sku: str
    price: float = Field(gt=0)
    samples: int = Field(4000, ge=500, le=20_000)
    horizon_days: int = Field(14, ge=3, le=60)


@router.post("/simulate")
async def simulate(body: SimulateRequest, session: AsyncSession = Depends(get_session)) -> dict:
    product, pts = await _load(session, body.sku)
    units = [float(p.units_sold) for p in pts]
    model = fit_demand([float(p.price) for p in pts], units)
    return {
        "sku": body.sku, "current_price": product.current_price, "elasticity": round(model.elasticity, 3),
        "elasticity_se": round(model.se, 3),
        **simulate_price(cost=product.cost, current_price=product.current_price, candidate_price=body.price,
                         q_cur=float(np.mean(units[-14:])), elasticity=model.elasticity, se=model.se,
                         horizon_days=body.horizon_days, samples=body.samples),
    }


# ---- price lab (bandit) -------------------------------------------------------------------------
async def _bandit(sku: str, session: AsyncSession, bus: EventBus, seed: int | None = None):
    product, pts = await _load(session, sku)
    store = BanditStore(bus.redis)
    n, s, q = await store.load(sku)
    units = [float(p.units_sold) for p in pts]
    q_cur = float(np.mean(units[-14:]))
    baseline = (product.current_price - product.cost) * q_cur
    return product, pts, units, q_cur, store, ThompsonBandit(n, s, q, baseline, np.random.default_rng(seed))


class SimulateRounds(BaseModel):
    rounds: int = Field(200, ge=1, le=1000)


class Reward(BaseModel):
    arm: int = Field(ge=0, lt=len(ARMS))
    profit: float


@router.get("/experiments/{sku}")
async def experiment_state(sku: str, session: AsyncSession = Depends(get_session), bus: EventBus = Depends(get_event_bus)) -> dict:
    product, _, _, _, _, bandit = await _bandit(sku, session, bus)
    return {"sku": sku, "arms": bandit.summary(product.current_price), "total_pulls": int(bandit.n.sum())}


@router.post("/experiments/{sku}/pull")
async def experiment_pull(sku: str, session: AsyncSession = Depends(get_session), bus: EventBus = Depends(get_event_bus)) -> dict:
    product, _, _, _, _, bandit = await _bandit(sku, session, bus)
    arm = bandit.choose()
    return {"arm": arm, "price": round(product.current_price * ARMS[arm], 2)}


@router.post("/experiments/{sku}/reward")
async def experiment_reward(sku: str, body: Reward, session: AsyncSession = Depends(get_session), bus: EventBus = Depends(get_event_bus)) -> dict:
    _, _, _, _, store, _ = await _bandit(sku, session, bus)
    await store.add(sku, body.arm, 1, body.profit, body.profit ** 2)
    return {"recorded": True}


@router.post("/experiments/{sku}/simulate")
async def experiment_simulate(sku: str, body: SimulateRounds, session: AsyncSession = Depends(get_session),
                              bus: EventBus = Depends(get_event_bus)) -> dict:
    """Run rounds against the fitted demand curve as a simulated storefront (safe way to preview convergence)."""
    product, pts, units, q_cur, store, bandit = await _bandit(sku, session, bus)
    model = fit_demand([float(p.price) for p in pts], units)
    rng = np.random.default_rng()
    n0, s0, q0 = bandit.n.copy(), bandit.s.copy(), bandit.q.copy()
    for _ in range(body.rounds):
        arm = bandit.choose()
        price = product.current_price * ARMS[arm]
        demand = q_cur * (price / product.current_price) ** model.elasticity * rng.lognormal(0, 0.15)
        bandit.update(arm, (price - product.cost) * demand)
    for i in range(len(ARMS)):
        if bandit.n[i] != n0[i]:
            await store.add(sku, i, bandit.n[i] - n0[i], bandit.s[i] - s0[i], bandit.q[i] - q0[i])
    return {"sku": sku, "arms": bandit.summary(product.current_price), "total_pulls": int(bandit.n.sum())}


@router.post("/experiments/{sku}/reset")
async def experiment_reset(sku: str, session: AsyncSession = Depends(get_session), bus: EventBus = Depends(get_event_bus)) -> dict:
    await _load(session, sku)
    await BanditStore(bus.redis).reset(sku)
    return {"reset": True}
