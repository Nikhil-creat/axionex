"""LangGraph supervisor: context -> pricing -> inventory -> risk audit -> (retry | finalize)."""
import logging
import operator
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Awaitable, Callable, TypedDict

import numpy as np
from langgraph.graph import END, START, StateGraph
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.inventory_agent import InventoryAgent
from app.agents.pricing_agent import PricingAgent
from app.core.config import settings
from app.core.database import SessionLocal
from app.models.models import AgentRun, CompetitorSignal, InventoryLevel, PricePoint, Product
from app.services.event_bus import EventBus, get_event_bus
from app.services.rag_engine import get_rag_engine

logger = logging.getLogger("optimarket.supervisor")
MAX_ATTEMPTS = 3


class MeshState(TypedDict, total=False):
    run_id: str
    product_id: str
    request: dict[str, Any]
    product: dict[str, Any]
    prices: list[float]
    units: list[float]
    competitor_prices: list[float]
    days_cover: float
    snippets: list[dict[str, Any]]
    constraints: dict[str, float]
    pricing: dict[str, Any]
    inventory: dict[str, Any]
    risk: dict[str, Any]
    decision: dict[str, Any]
    attempts: int
    trace: Annotated[list[dict[str, Any]], operator.add]


class Supervisor:
    def __init__(self, session: AsyncSession, bus: EventBus, run_id: uuid.UUID) -> None:
        self.session, self.bus, self.run_id = session, bus, run_id
        self.pricing, self.inventory, self.rag = PricingAgent(), InventoryAgent(), get_rag_engine()
        self.graph = self._build()

    # ---- graph wiring ----------------------------------------------------
    def _build(self):
        g = StateGraph(MeshState)
        for name, fn in (("context", self._context), ("pricing", self._pricing), ("inventory", self._inventory),
                         ("risk", self._risk), ("finalize", self._finalize)):
            g.add_node(name, self._instrument(name, fn))
        g.add_edge(START, "context")
        g.add_edge("context", "pricing")
        g.add_edge("pricing", "inventory")
        g.add_edge("inventory", "risk")
        g.add_conditional_edges("risk", self._route, {"pricing": "pricing", "finalize": "finalize"})
        g.add_edge("finalize", END)
        return g.compile()

    def _instrument(self, name: str, fn: Callable[[MeshState], Awaitable[dict[str, Any]]]):
        async def wrapper(state: MeshState) -> dict[str, Any]:
            await self.bus.publish_run_event(self.run_id, "node.started", name, {"attempt": state.get("attempts", 0)})
            update = await fn(state)
            entry = update["trace"][-1]
            detail = update.get(name) if name in update else update.get("product")
            await self.bus.publish_run_event(self.run_id, "node.completed", name,
                                             {"summary": entry["summary"], "detail": detail})
            return update
        return wrapper

    @staticmethod
    def _route(state: MeshState) -> str:
        if state["risk"]["approved"] or state.get("attempts", 0) >= MAX_ATTEMPTS:
            return "finalize"
        return "pricing"

    # ---- nodes -----------------------------------------------------------
    async def _context(self, state: MeshState) -> dict[str, Any]:
        s, pid = self.session, uuid.UUID(state["product_id"])
        product = await s.get(Product, pid)
        if product is None:
            raise LookupError("product not found")
        now = datetime.now(timezone.utc)
        pts = (await s.execute(select(PricePoint).where(PricePoint.product_id == pid, PricePoint.observed_at >= now - timedelta(days=60))
                               .order_by(PricePoint.observed_at))).scalars().all()
        sigs = (await s.execute(select(CompetitorSignal).where(CompetitorSignal.product_id == pid, CompetitorSignal.observed_at >= now - timedelta(days=14))
                                .order_by(CompetitorSignal.observed_at.desc()))).scalars().all()
        latest: dict[str, float] = {}
        for sig in sigs:
            latest.setdefault(sig.competitor, float(sig.price))
        available = int((await s.execute(select(func.coalesce(func.sum(InventoryLevel.on_hand - InventoryLevel.reserved), 0))
                                         .where(InventoryLevel.product_id == pid))).scalar_one())
        units = [float(p.units_sold) for p in pts]
        daily = float(np.mean(units[-14:])) if units else 1.0
        try:
            snippets = await self.rag.retrieve(f"{product.name} {product.category} demand pricing trend competitor", k=6)
        except Exception as exc:  # RAG must never block a decision
            logger.warning("RAG unavailable: %s", exc)
            snippets = []
        prod = {"sku": product.sku, "name": product.name, "category": product.category, "cost": product.cost,
                "current_price": product.current_price, "map_price": product.map_price}
        summary = f"{len(pts)} demand points, {len(latest)} competitors, {len(snippets)} intel snippets, {available} units on hand"
        return {
            "product": prod, "prices": [float(p.price) for p in pts], "units": units,
            "competitor_prices": list(latest.values()), "days_cover": available / max(daily, 0.1), "snippets": snippets,
            "constraints": {"min_margin": state["request"]["min_margin"], "max_change_pct": state["request"]["max_change_pct"]},
            "attempts": 0, "trace": [{"node": "context", "summary": summary}],
        }

    async def _pricing(self, state: MeshState) -> dict[str, Any]:
        p = state["product"]
        result = self.pricing.propose(
            cost=p["cost"], current_price=p["current_price"], map_price=p["map_price"], prices=state["prices"],
            units=state["units"], competitor_prices=state["competitor_prices"], days_cover=state["days_cover"],
            snippets=state["snippets"], constraints=state["constraints"],
        )
        attempt = state.get("attempts", 0) + 1
        return {"pricing": result, "attempts": attempt,
                "trace": [{"node": "pricing", "summary": f"attempt {attempt}: " + self.pricing.summarise(result)}]}

    async def _inventory(self, state: MeshState) -> dict[str, Any]:
        p, pr, req = state["product"], state["pricing"], state["request"]
        result = await self.inventory.plan(
            self.session, product_id=uuid.UUID(state["product_id"]), cost=p["cost"], current_price=p["current_price"],
            proposed_price=pr["proposed_price"], elasticity=pr["elasticity"], units=state["units"],
            customer_lat=req["customer_lat"], customer_lon=req["customer_lon"],
        )
        return {"inventory": result, "trace": [{"node": "inventory", "summary": self.inventory.summarise(result)}]}

    async def _risk(self, state: MeshState) -> dict[str, Any]:
        p, pr, inv, req = state["product"], state["pricing"], state["inventory"], state["request"]
        price = pr["proposed_price"]
        margin = (price - p["cost"]) / price
        change = abs(price / p["current_price"] - 1)
        comps = state["competitor_prices"]
        checks = [
            ("margin_floor", margin >= req["min_margin"] - 1e-9, f"margin {margin:.1%} vs floor {req['min_margin']:.0%}"),
            ("map_compliance", p["map_price"] is None or price >= p["map_price"], f"MAP {p['map_price']}"),
            ("change_limit", change <= req["max_change_pct"] + 1e-9, f"change {change:.1%} vs cap {req['max_change_pct']:.0%}"),
            ("volume_drop", pr["expected_units_change_pct"] >= -25.0, f"expected volume {pr['expected_units_change_pct']:+.1f}%"),
            ("profit_regression",
             pr["expected_daily_profit_proposed"] >= 0.98 * pr["expected_daily_profit_current"] or state["days_cover"] > 60,
             "profit must not fall >2% unless clearing overstock"),
            ("competitor_ceiling", not comps or price <= 1.25 * max(comps), "price within 125% of highest rival"),
            ("po_budget", inv["order_value"] <= settings.max_po_value, f"PO ₹{inv['order_value']:.0f} vs cap ₹{settings.max_po_value:.0f}"),
        ]
        detail = [{"rule": r, "passed": bool(ok), "detail": d} for r, ok, d in checks]
        approved = all(c["passed"] for c in detail)
        failed = [c["rule"] for c in detail if not c["passed"]]
        update: dict[str, Any] = {
            "risk": {"approved": approved, "checks": detail, "score": round(sum(c["passed"] for c in detail) / len(detail), 3)},
            "trace": [{"node": "risk", "summary": "approved" if approved else f"rejected ({', '.join(failed)}); tightening step size"}],
        }
        if not approved:
            c = dict(state["constraints"])
            c["max_change_pct"] = round(c["max_change_pct"] * 0.5, 4)
            update["constraints"] = c
        return update

    async def _finalize(self, state: MeshState) -> dict[str, Any]:
        pr, inv, risk, p = state["pricing"], state["inventory"], state["risk"], state["product"]
        approved = risk["approved"]
        moves = approved and abs(pr["price_change_pct"]) >= 0.5
        action = "reprice" if moves else "hold"
        base = pr["expected_daily_profit_current"] or 1.0
        decision = {
            "action": action, "approved": approved, "sku": p["sku"], "old_price": p["current_price"],
            "new_price": pr["proposed_price"] if moves else p["current_price"],
            "price_change_pct": pr["price_change_pct"] if moves else 0.0,
            "expected_profit_delta_pct": round((pr["expected_daily_profit_proposed"] / base - 1) * 100, 2) if moves else 0.0,
            "expected_units_change_pct": pr["expected_units_change_pct"] if moves else 0.0,
            "reorder_qty": inv["recommended_order_qty"], "inventory_status": inv["status"],
            "fulfilment_warehouse": inv["fulfilment_warehouse"], "risk_score": risk["score"],
            "attempts": state.get("attempts", 1), "applied": False, "explain": pr.get("explain", []),
            "reasons": [c["rule"] for c in risk["checks"] if not c["passed"]],
        }
        msg = (f"{action}: ₹{decision['old_price']:.0f} → ₹{decision['new_price']:.0f}, reorder {decision['reorder_qty']}"
               if approved else f"hold: risk auditor blocked ({', '.join(decision['reasons'])})")
        return {"decision": decision, "trace": [{"node": "finalize", "summary": msg}]}

    # ---- entry -----------------------------------------------------------
    async def run(self, product_id: uuid.UUID, request: dict[str, Any]) -> dict[str, Any]:
        await self.bus.publish_run_event(self.run_id, "run.started", None, {"product_id": str(product_id)})
        init: MeshState = {"run_id": str(self.run_id), "product_id": str(product_id), "request": request, "trace": []}
        return await self.graph.ainvoke(init, {"recursion_limit": 40})


async def start_run(session: AsyncSession, request: dict[str, Any]) -> AgentRun:
    """Resolve the product and create the AgentRun row. Raises LookupError if the product is unknown."""
    if request.get("product_id"):
        product = await session.get(Product, uuid.UUID(str(request["product_id"])))
    else:
        product = (await session.execute(select(Product).where(Product.sku == request["sku"]))).scalar_one_or_none()
    if product is None:
        raise LookupError("Unknown product")
    run = AgentRun(product_id=product.id, status="running", request=request)
    session.add(run)
    await session.commit()
    return run


async def execute_run(run_id: uuid.UUID) -> None:
    bus = get_event_bus()
    async with SessionLocal() as session:
        run = await session.get(AgentRun, run_id)
        if run is None:
            return
        sup = Supervisor(session, bus, run_id)
        final: dict[str, Any] | None = None
        try:
            final = await sup.run(run.product_id, run.request)
            run.status, run.trace, run.decision = "completed", final["trace"], final["decision"]
            if run.request.get("auto_apply") and final["decision"]["action"] == "reprice":
                product = await session.get(Product, run.product_id)
                product.current_price = final["decision"]["new_price"]
                run.applied = True
                run.decision = {**run.decision, "applied": True}
        except Exception as exc:
            logger.exception("run %s failed", run_id)
            await session.rollback()
            run = await session.get(AgentRun, run_id)
            run.status, run.error = "failed", str(exc)[:1000]
        run.finished_at = datetime.now(timezone.utc)
        await session.commit()
        if run.status == "completed":
            await bus.publish_run_event(run_id, "run.completed", None, run.decision or {})
        else:
            await bus.publish_run_event(run_id, "run.failed", None, {"error": run.error})
