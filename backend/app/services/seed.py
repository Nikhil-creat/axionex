"""Idempotent demo dataset: Indian D2C apparel catalogue, PostGIS warehouses, demand history, market intel."""
import logging
from datetime import datetime, timedelta, timezone

import numpy as np
from geoalchemy2.elements import WKTElement
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import CompetitorSignal, InventoryLevel, PricePoint, Product, Warehouse
from app.services.rag_engine import RagEngine

logger = logging.getLogger("optimarket.seed")

WAREHOUSES = [
    ("HYD", "Hyderabad Fulfilment Hub", 17.3850, 78.4867),
    ("BOM", "Mumbai Bhiwandi Hub", 19.2967, 73.0631),
    ("DEL", "Delhi Bilaspur Hub", 28.4089, 77.0250),
    ("BLR", "Bengaluru Hoskote Hub", 13.0707, 77.7980),
    ("CCU", "Kolkata Dankuni Hub", 22.6800, 88.2900),
]
# sku, name, category, cost, price, map, base units/day
PRODUCTS = [
    ("OMX-TEE-001", "Heavyweight Oversized Tee", "tops", 420, 1199, None, 34),
    ("OMX-DEN-014", "Selvedge Denim Jacket", "outerwear", 1650, 4499, None, 11),
    ("OMX-HOD-007", "Brushed Fleece Hoodie", "outerwear", 780, 2199, 1799, 19),
    ("OMX-SNK-022", "Trail Runner Sneaker", "footwear", 1900, 5299, None, 9),
    ("OMX-KUR-031", "Handloom Linen Kurta", "ethnic", 650, 1899, None, 15),
]
COMPETITORS = ["NorthLoop", "Kaarigar Co.", "UrbanWeft"]
INTEL = [
    ("Festive season demand surge expected from mid-October: analysts see rising demand of 18-25% for ethnic wear and outerwear across metro markets.", "market_trend", "retail-pulse"),
    ("Cotton yarn prices increased 6% month over month; several D2C brands are absorbing costs and holding shelf prices to protect volume.", "market_trend", "textile-weekly"),
    ("Competitor NorthLoop launched a price war on oversized tees with aggressive discount bundles, clearance pricing near 10% below last quarter.", "competitor", "scrape-log-north"),
    ("Brand guideline: premium positioning. Avoid discounting beyond 15% off list price; never advertise below MAP on hoodies.", "brand_guideline", "brand-book-v3"),
    ("Sneaker category shows weak demand in tier-1 cities after monsoon slowdown, with returns spike on size-fit issues.", "market_trend", "footwear-insights"),
    ("Handloom linen kurtas trending on social commerce; viral creator drops caused stockout risk on top SKUs in Hyderabad and Bengaluru.", "market_trend", "social-listening"),
    ("Kaarigar Co. raised denim jacket prices by 4% following a supply crunch in selvedge fabric.", "competitor", "scrape-log-kaarigar"),
]


async def seed_demo_data(session: AsyncSession, rag: RagEngine) -> None:
    if (await session.execute(select(func.count()).select_from(Product))).scalar_one():
        return
    rng = np.random.default_rng(42)
    now = datetime.now(timezone.utc)
    whs = []
    for code, name, lat, lon in WAREHOUSES:
        wh = Warehouse(code=code, name=name, location=WKTElement(f"POINT({lon} {lat})", srid=4326))
        session.add(wh)
        whs.append(wh)
    await session.flush()

    for sku, name, cat, cost, price, map_p, base_q in PRODUCTS:
        prod = Product(sku=sku, name=name, category=cat, cost=cost, current_price=price, map_price=map_p,
                       attributes={"season": "AW26", "channel": "d2c"})
        session.add(prod)
        await session.flush()
        p = float(price)
        for d in range(60, 0, -1):
            p = float(np.clip(p * (1 + rng.normal(0, 0.03)), price * 0.88, price * 1.12))
            units = max(1, int(base_q * (p / price) ** -2.1 * rng.lognormal(0, 0.12)))
            session.add(PricePoint(product_id=prod.id, price=round(p, 2), units_sold=units, observed_at=now - timedelta(days=d)))
        for comp in COMPETITORS:
            session.add(CompetitorSignal(product_id=prod.id, competitor=comp, price=round(price * rng.uniform(0.94, 1.08), 0),
                                         observed_at=now - timedelta(days=int(rng.integers(0, 6)))))
        for wh in whs:
            stock = int(base_q * rng.uniform(3, 14) * (1.2 if wh.code in ("HYD", "BLR") else 1.0))
            session.add(InventoryLevel(product_id=prod.id, warehouse_id=wh.id, on_hand=stock,
                                       reserved=int(stock * rng.uniform(0.02, 0.1)), lead_time_days=float(rng.integers(2, 7))))
    await session.commit()
    try:
        await rag.ingest([{"text": t, "kind": k, "source": s} for t, k, s in INTEL])
    except Exception as exc:
        logger.warning("Skipping RAG seeding (vector store unavailable): %s", exc)
    logger.info("Seeded demo data")
