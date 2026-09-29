"""Webhook consumer worker: Redis Streams consumer group -> DB + RAG + autonomous agent runs."""
import asyncio
import logging
import socket
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.agents.supervisor import execute_run, start_run
from app.core.database import SessionLocal
from app.models.models import CompetitorSignal, InventoryLevel, PricePoint, Product, Warehouse
from app.services.event_bus import get_event_bus
from app.services.rag_engine import get_rag_engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("optimarket.worker")
REPRICE_TRIGGER = 0.05  # competitor move vs our price that wakes the agent mesh


async def handle(event_type: str, data: dict) -> None:
    async with SessionLocal() as session:
        product = (await session.execute(select(Product).where(Product.sku == data["sku"]))).scalar_one_or_none()
        if product is None:
            raise LookupError(f"unknown sku {data['sku']}")

        if event_type == "competitor.price_changed":
            price = float(data["price"])
            session.add(CompetitorSignal(product_id=product.id, competitor=data["competitor"], price=price))
            await session.commit()
            try:
                await get_rag_engine().ingest([{
                    "text": f"Competitor {data['competitor']} repriced {product.name} to {price:.0f}. {data.get('note', '')}".strip(),
                    "kind": "competitor", "source": f"webhook:{data['competitor']}", "sku": product.sku}])
            except Exception as exc:
                logger.warning("RAG ingest skipped: %s", exc)
            if abs(price / product.current_price - 1) >= REPRICE_TRIGGER:
                run = await start_run(session, {"sku": product.sku, "auto_apply": False, "customer_lat": 17.385,
                                                "customer_lon": 78.4867, "min_margin": 0.25, "max_change_pct": 0.12})
                logger.info("Competitor move triggered agent run %s", run.id)
                await execute_run(run.id)

        elif event_type == "inventory.adjusted":
            wh = (await session.execute(select(Warehouse).where(Warehouse.code == data["warehouse_code"]))).scalar_one()
            inv = (await session.execute(select(InventoryLevel).where(
                InventoryLevel.product_id == product.id, InventoryLevel.warehouse_id == wh.id))).scalar_one_or_none()
            if inv is None:
                inv = InventoryLevel(product_id=product.id, warehouse_id=wh.id, on_hand=0)
                session.add(inv)
            inv.on_hand = int(data["on_hand"])
            await session.commit()

        elif event_type == "order.created":
            session.add(PricePoint(product_id=product.id, price=float(data["unit_price"]), units_sold=int(data["quantity"]),
                                   observed_at=datetime.now(timezone.utc)))
            await session.commit()


async def main() -> None:
    bus = get_event_bus()
    await bus.ensure_group()
    consumer = f"{socket.gethostname()}-{uuid.uuid4().hex[:6]}"
    logger.info("Worker %s consuming webhooks", consumer)
    while True:
        try:
            async for entry_id, source, event_type, data in bus.consume_webhooks(consumer):
                try:
                    await handle(event_type, data)
                except Exception as exc:
                    logger.exception("Webhook %s failed", entry_id)
                    await bus.dead_letter(entry_id, source, event_type, data, str(exc))
                finally:
                    await bus.ack_webhook(entry_id)
        except Exception:
            logger.exception("Consumer loop error; retrying in 3s")
            await asyncio.sleep(3)


if __name__ == "__main__":
    asyncio.run(main())
