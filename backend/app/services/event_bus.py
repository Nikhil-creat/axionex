"""Redis Streams event bus: per-run agent trace streams + inbound webhook queue."""
import json
import logging
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

import redis.asyncio as aioredis
from redis.asyncio.cluster import RedisCluster
from redis.exceptions import ResponseError

from app.core.config import settings

logger = logging.getLogger("optimarket.bus")


def run_stream_key(run_id: Any) -> str:
    return f"agent:run:{run_id}"


class EventBus:
    def __init__(self, url: str, cluster: bool = False) -> None:
        if cluster:
            self.redis = RedisCluster.from_url(url, decode_responses=True)
        else:
            self.redis = aioredis.from_url(url, decode_responses=True)

    async def ping(self) -> bool:
        return bool(await self.redis.ping())

    async def close(self) -> None:
        await self.redis.aclose()

    # ---- agent execution trace --------------------------------------------
    async def publish_run_event(
        self, run_id: Any, type_: str, node: str | None = None, data: dict[str, Any] | None = None
    ) -> str:
        event = {
            "type": type_,
            "node": node or "",
            "ts": datetime.now(timezone.utc).isoformat(),
            "data": json.dumps(data or {}, default=str),
        }
        key = run_stream_key(run_id)
        entry_id = await self.redis.xadd(key, event, maxlen=2000, approximate=True)
        await self.redis.expire(key, settings.run_stream_ttl_seconds)
        return entry_id

    async def read_run_events(
        self, run_id: Any, last_id: str = "0-0", block_ms: int = 15_000
    ) -> list[tuple[str, dict[str, Any]]]:
        res = await self.redis.xread({run_stream_key(run_id): last_id}, block=block_ms, count=50)
        out: list[tuple[str, dict[str, Any]]] = []
        for _key, entries in res or []:
            for entry_id, fields in entries:
                out.append((entry_id, {
                    "type": fields["type"],
                    "node": fields.get("node") or None,
                    "ts": fields["ts"],
                    "data": json.loads(fields.get("data") or "{}"),
                }))
        return out

    async def run_stream_length(self, run_id: Any) -> int:
        return int(await self.redis.xlen(run_stream_key(run_id)))

    # ---- webhook pipeline --------------------------------------------------
    async def enqueue_webhook(self, source: str, event_type: str, data: dict[str, Any]) -> str:
        return await self.redis.xadd(
            settings.webhook_stream,
            {"source": source, "event_type": event_type, "data": json.dumps(data, default=str)},
            maxlen=50_000, approximate=True,
        )

    async def ensure_group(self) -> None:
        try:
            await self.redis.xgroup_create(settings.webhook_stream, settings.webhook_group, id="0", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def consume_webhooks(self, consumer: str, block_ms: int = 5000, count: int = 10):
        res = await self.redis.xreadgroup(
            settings.webhook_group, consumer, {settings.webhook_stream: ">"}, count=count, block=block_ms
        )
        for _key, entries in res or []:
            for entry_id, fields in entries:
                yield entry_id, fields["source"], fields["event_type"], json.loads(fields["data"])

    async def ack_webhook(self, entry_id: str) -> None:
        await self.redis.xack(settings.webhook_stream, settings.webhook_group, entry_id)

    async def dead_letter(self, entry_id: str, source: str, event_type: str, data: dict, error: str) -> None:
        await self.redis.xadd(settings.webhook_dead_stream, {
            "orig_id": entry_id, "source": source, "event_type": event_type,
            "data": json.dumps(data, default=str), "error": error[:500],
        }, maxlen=5000, approximate=True)


@lru_cache
def get_event_bus() -> EventBus:
    return EventBus(settings.redis_url, settings.redis_cluster)
