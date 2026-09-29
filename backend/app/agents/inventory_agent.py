"""Inventory Coordinator: reorder policy (safety stock / ROP) + PostGIS spatial fulfilment routing."""
import math
from typing import Any

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import InventoryLevel, Warehouse


class InventoryAgent:
    name = "inventory"

    async def plan(
        self, session: AsyncSession, *, product_id: Any, cost: float, current_price: float, proposed_price: float,
        elasticity: float, units: list[float], customer_lat: float, customer_lon: float,
        service_z: float = 1.65, review_days: int = 7,
    ) -> dict[str, Any]:
        point = func.ST_GeogFromText(f"SRID=4326;POINT({customer_lon} {customer_lat})")
        dist = func.ST_Distance(Warehouse.location, point).label("dist_m")
        rows = (await session.execute(
            select(Warehouse, InventoryLevel, dist)
            .join(InventoryLevel, InventoryLevel.warehouse_id == Warehouse.id)
            .where(InventoryLevel.product_id == product_id)
            .order_by(dist)
        )).all()

        available = [max(0, inv.on_hand - inv.reserved) for _, inv, _ in rows]
        position = int(sum(available))
        lead = float(np.mean([float(inv.lead_time_days) for _, inv, _ in rows])) if rows else 5.0
        recent = np.asarray(units[-14:] or [1.0], dtype=float)
        sigma = float(np.std(units[-30:])) if len(units) > 1 else 1.0
        mu = float(recent.mean()) * (proposed_price / current_price) ** elasticity  # demand at the new price
        mu = max(mu, 0.1)

        safety = service_z * sigma * math.sqrt(max(lead, 1.0))
        rop = mu * lead + safety
        order_qty = max(0, math.ceil(mu * (lead + review_days) + safety - position))
        cover = position / mu
        status = "reorder" if position <= rop else "overstock" if cover > 60 else "healthy"

        routing = [
            {"warehouse": wh.code, "name": wh.name, "distance_km": round(float(d) / 1000, 1), "available": av}
            for (wh, _inv, d), av in zip(rows, available)
        ]
        fulfil = next((r for r in routing if r["available"] > 0), None)
        return {
            "status": status, "days_of_cover": round(cover, 1), "available_units": position,
            "expected_daily_demand": round(mu, 2), "safety_stock": math.ceil(safety), "reorder_point": math.ceil(rop),
            "avg_lead_time_days": round(lead, 1), "recommended_order_qty": int(order_qty),
            "order_value": round(order_qty * cost, 2), "fulfilment_warehouse": fulfil, "routing": routing[:4],
        }

    def summarise(self, r: dict[str, Any]) -> str:
        wh = r["fulfilment_warehouse"]["warehouse"] if r["fulfilment_warehouse"] else "none"
        return f"{r['status']}: {r['days_of_cover']}d cover, order {r['recommended_order_qty']} units, ship from {wh}"
