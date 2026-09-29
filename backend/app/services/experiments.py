"""Thompson-sampling price experiments (Gaussian bandit) with Redis-persisted arm statistics."""
from typing import Any

import numpy as np

ARMS = (0.94, 0.97, 1.00, 1.03, 1.06)  # price multipliers vs. current price


class ThompsonBandit:
    def __init__(self, n: np.ndarray, s: np.ndarray, q: np.ndarray, baseline: float, rng: np.random.Generator) -> None:
        self.n, self.s, self.q, self.baseline, self.rng = n.astype(float), s.astype(float), q.astype(float), baseline, rng

    def _pooled_sd(self) -> float:
        var = [max(self.q[i] / self.n[i] - (self.s[i] / self.n[i]) ** 2, 0.0) for i in range(len(self.n)) if self.n[i] >= 2]
        sd = float(np.sqrt(np.mean(var))) if var else 0.25 * abs(self.baseline)
        return max(sd, 0.02 * abs(self.baseline), 1e-6)

    def posterior(self) -> tuple[np.ndarray, np.ndarray]:
        means = np.where(self.n > 0, self.s / np.maximum(self.n, 1), self.baseline)
        return means, self._pooled_sd() / np.sqrt(self.n + 1.0)

    def choose(self) -> int:
        means, sds = self.posterior()
        return int(np.argmax(self.rng.normal(means, sds)))

    def prob_best(self, draws: int = 2000) -> np.ndarray:
        means, sds = self.posterior()
        wins = np.argmax(self.rng.normal(means, sds, size=(draws, len(means))), axis=1)
        return np.bincount(wins, minlength=len(means)) / draws

    def update(self, arm: int, reward: float) -> None:
        self.n[arm] += 1
        self.s[arm] += reward
        self.q[arm] += reward * reward

    def summary(self, base_price: float) -> list[dict[str, Any]]:
        means, _ = self.posterior()
        pb = self.prob_best()
        return [{"arm": i, "multiplier": ARMS[i], "price": round(base_price * ARMS[i], 2), "pulls": int(self.n[i]),
                 "mean_profit": round(float(means[i]), 2) if self.n[i] else None, "prob_best": round(float(pb[i]), 3)}
                for i in range(len(ARMS))]


class BanditStore:
    def __init__(self, redis) -> None:
        self.redis = redis

    @staticmethod
    def _key(sku: str) -> str:
        return f"bandit:{sku}"

    async def load(self, sku: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        raw = await self.redis.hgetall(self._key(sku))
        k = len(ARMS)
        return (np.array([float(raw.get(f"n{i}", 0)) for i in range(k)]),
                np.array([float(raw.get(f"s{i}", 0)) for i in range(k)]),
                np.array([float(raw.get(f"q{i}", 0)) for i in range(k)]))

    async def add(self, sku: str, arm: int, n: float, s: float, q: float) -> None:
        key = self._key(sku)
        await self.redis.hincrbyfloat(key, f"n{arm}", n)
        await self.redis.hincrbyfloat(key, f"s{arm}", s)
        await self.redis.hincrbyfloat(key, f"q{arm}", q)

    async def reset(self, sku: str) -> None:
        await self.redis.delete(self._key(sku))
