"""Monte Carlo what-if engine: propagates elasticity uncertainty and demand noise into profit distributions."""
from typing import Any

import numpy as np


def simulate_price(*, cost: float, current_price: float, candidate_price: float, q_cur: float, elasticity: float,
                   se: float, horizon_days: int = 14, samples: int = 4000, demand_cv: float = 0.12,
                   seed: int | None = None) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    samples = int(min(max(samples, 500), 20_000))
    e = np.minimum(rng.normal(elasticity, max(se, 0.05), samples), -1.02)
    noise = rng.lognormal(0.0, demand_cv / np.sqrt(horizon_days), samples)  # shared noise -> paired comparison
    base = (current_price - cost) * q_cur * horizon_days * noise

    def profit(price: float) -> np.ndarray:
        return (price - cost) * q_cur * horizon_days * (price / current_price) ** e * noise

    cand = profit(candidate_price)
    uplift = cand - base
    tail = np.sort(uplift)[: max(1, int(0.05 * samples))]
    counts, edges = np.histogram(uplift, bins=24)
    curve = []
    for mult in np.linspace(0.85, 1.15, 13):
        p = float(current_price * mult)
        pr = profit(p) - base
        curve.append({"price": round(p, 2), "mean": round(float(pr.mean()), 2),
                      "p5": round(float(np.percentile(pr, 5)), 2), "p95": round(float(np.percentile(pr, 95)), 2)})
    return {
        "horizon_days": horizon_days, "samples": samples, "candidate_price": round(candidate_price, 2),
        "expected_uplift": round(float(uplift.mean()), 2), "uplift_p5": round(float(np.percentile(uplift, 5)), 2),
        "uplift_p50": round(float(np.percentile(uplift, 50)), 2), "uplift_p95": round(float(np.percentile(uplift, 95)), 2),
        "prob_uplift": round(float((uplift > 0).mean()), 4), "cvar5": round(float(tail.mean()), 2),
        "expected_baseline_profit": round(float(base.mean()), 2),
        "histogram": {"edges": [round(float(x), 2) for x in edges], "counts": [int(c) for c in counts]},
        "curve": curve,
    }
