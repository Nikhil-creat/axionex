"""Resilience primitives: async retry with exponential backoff + jitter, and a circuit breaker."""
import asyncio
import random
import time
from typing import Awaitable, Callable, TypeVar

T = TypeVar("T")


class CircuitOpenError(RuntimeError):
    pass


class CircuitBreaker:
    """Opens after `failures` consecutive errors; lets one probe through after `reset_seconds` (half-open)."""

    def __init__(self, failures: int = 3, reset_seconds: float = 30.0) -> None:
        self.failures, self.reset_seconds = failures, reset_seconds
        self._count, self._opened_at = 0, 0.0

    def allow(self) -> bool:
        if self._count < self.failures:
            return True
        return time.monotonic() - self._opened_at >= self.reset_seconds

    def record(self, ok: bool) -> None:
        if ok:
            self._count = 0
            return
        self._count += 1
        if self._count >= self.failures:
            self._opened_at = time.monotonic()

    @property
    def is_open(self) -> bool:
        return not self.allow()


async def retry_async(fn: Callable[[], Awaitable[T]], attempts: int = 3, base_delay: float = 0.3,
                      retry_on: tuple[type[BaseException], ...] = (Exception,)) -> T:
    last: BaseException | None = None
    for i in range(attempts):
        try:
            return await fn()
        except retry_on as exc:
            last = exc
            if i < attempts - 1:
                await asyncio.sleep(base_delay * (2 ** i) * (0.5 + random.random()))
    assert last is not None
    raise last
