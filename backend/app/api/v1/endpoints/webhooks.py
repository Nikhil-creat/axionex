"""Signed webhook ingress -> Redis Stream (processed asynchronously by the worker)."""
import json

from fastapi import APIRouter, Depends, HTTPException

from app.core.security import verify_webhook
from app.schemas import WebhookEvent
from app.services.event_bus import EventBus, get_event_bus

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
SUPPORTED = {"competitor.price_changed", "inventory.adjusted", "order.created"}


@router.post("/{source}", status_code=202)
async def receive(source: str, body: bytes = Depends(verify_webhook), bus: EventBus = Depends(get_event_bus)) -> dict:
    try:
        event = WebhookEvent.model_validate(json.loads(body))
    except Exception:
        raise HTTPException(422, "Malformed webhook payload")
    if event.event_type not in SUPPORTED:
        raise HTTPException(422, f"Unsupported event_type; expected one of {sorted(SUPPORTED)}")
    entry_id = await bus.enqueue_webhook(source, event.event_type, event.data)
    return {"accepted": True, "stream_id": entry_id}
