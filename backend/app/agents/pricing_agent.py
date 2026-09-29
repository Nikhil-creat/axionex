"""Pricing Agent: Bayesian-shrunk constant-elasticity demand model + constrained profit optimisation."""
import math
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np

POSITIVE = ("surge", "spike", "festive", "demand up", "shortage", "sold out", "viral", "trending", "stockout", "rising demand", "supply crunch")
NEGATIVE = ("discount", "clearance", "slowdown", "weak demand", "oversupply", "price war", "markdown", "decline", "returns spike", "falling demand")


@dataclass
class DemandModel:
    elasticity: float
    r2: float
    n: int
    source: str
    se: float = 0.5


def fit_demand(prices: list[float], units: list[float], prior_e: float = -1.8, prior_precision: float = 0.05) -> DemandModel:
    """ln q = a + e ln p, with a Gaussian prior on e (shrinkage = prior_precision) for stability."""
    p, q = np.asarray(prices, dtype=float), np.asarray(units, dtype=float)
    m = (p > 0) & (q > 0)
    p, q = p[m], q[m]
    if len(p) < 8 or np.ptp(np.log(p)) < 1e-3:
        return DemandModel(prior_e, 0.0, int(len(p)), "prior", 0.5)
    x, y = np.log(p), np.log(q)
    xm, ym = x.mean(), y.mean()
    sxx, sxy = float(((x - xm) ** 2).sum()), float(((x - xm) * (y - ym)).sum())
    e = (sxy + prior_precision * prior_e) / (sxx + prior_precision)
    e = float(np.clip(e, -4.5, -1.05))
    a = ym - e * xm
    resid = y - (a + e * x)
    ss_tot = float(((y - ym) ** 2).sum()) or 1.0
    r2 = float(max(0.0, 1 - (resid ** 2).sum() / ss_tot))
    s2 = float((resid ** 2).sum()) / max(len(p) - 2, 1)
    se = float(np.sqrt(s2 / (sxx + prior_precision)))
    return DemandModel(e, r2, int(len(p)), "posterior", se)


def trend_score(snippets: list[dict[str, Any]]) -> float:
    """Lexicon sentiment of retrieved market intel in [-1, 1], weighted by retrieval score."""
    pos = neg = 0.0
    for s in snippets:
        t, w = s["text"].lower(), max(s.get("score", 0.5), 0.05)
        pos += w * sum(t.count(k) for k in POSITIVE)
        neg += w * sum(t.count(k) for k in NEGATIVE)
    return 0.0 if pos + neg == 0 else (pos - neg) / (pos + neg)


class PricingAgent:
    name = "pricing"

    def propose(
        self, *, cost: float, current_price: float, map_price: float | None, prices: list[float], units: list[float],
        competitor_prices: list[float], days_cover: float, snippets: list[dict[str, Any]], constraints: dict[str, float],
    ) -> dict[str, Any]:
        model = fit_demand(prices, units)
        e = model.elasticity
        q_cur = float(np.mean(units[-14:])) if units else 1.0

        p_opt = cost * e / (1 + e)  # Lerner rule for constant elasticity
        comps = sorted(competitor_prices)
        comp_med = float(np.median(comps)) if comps else None
        w = min(0.85, 0.35 + 0.5 * model.r2)  # trust in own demand model
        # Constant-elasticity models are only trustworthy near the observed price range: shrink the
        # optimiser's weight the further p_opt sits from the current price.
        w *= math.exp(-2.0 * abs(math.log(p_opt / current_price)))
        anchor = comp_med * 0.99 if comp_med else current_price
        blended = w * p_opt + (1 - w) * anchor
        b_blend = blended
        ts = trend_score(snippets)
        blended *= 1 + 0.03 * ts
        b_trend = blended
        if days_cover > 60:
            inv_adj = -min(0.06, (days_cover - 60) / 1000)
        elif days_cover < 10:
            inv_adj = min(0.04, (10 - days_cover) * 0.005)
        else:
            inv_adj = 0.0
        target = blended * (1 + inv_adj)

        floor_margin = cost / (1 - constraints["min_margin"])
        hard_lo = max(floor_margin, map_price or 0.0)
        lo = max(hard_lo, current_price * (1 - constraints["max_change_pct"]))
        hi = current_price * (1 + constraints["max_change_pct"])
        if comps:
            hi = min(hi, comps[-1] * 1.15)
        hi = max(hi, hard_lo)
        lo = min(lo, hi)
        price = min(max(target, lo), hi)
        clamped = price

        charm = math.floor(price / 10) * 10 + 9  # x9 price ending, only if it stays feasible
        if charm > price:
            charm -= 10
        if lo <= charm <= hi:
            price = float(charm)
        price = round(price, 2)

        def profit(p_: float) -> float:
            return (p_ - cost) * q_cur * (p_ / current_price) ** e

        qty_ratio = (price / current_price) ** e
        return {
            "elasticity": round(e, 3), "elasticity_se": round(model.se, 3),
            "explain": [
                {"label": "Profit-maximising price", "price": round(p_opt, 2)},
                {"label": "Blended with rivals", "price": round(b_blend, 2)},
                {"label": "Market trend", "price": round(b_trend, 2)},
                {"label": "Stock cover", "price": round(target, 2)},
                {"label": "Guardrails", "price": round(clamped, 2)},
                {"label": "Price ending", "price": price},
            ], "model_r2": round(model.r2, 3), "model_source": model.source, "observations": model.n,
            "profit_maximising_price": round(p_opt, 2), "competitor_median": round(comp_med, 2) if comp_med else None,
            "trend_score": round(ts, 3), "inventory_adjustment_pct": round(inv_adj * 100, 2),
            "bounds": {"low": round(lo, 2), "high": round(hi, 2)},
            "current_price": current_price, "proposed_price": price,
            "price_change_pct": round((price / current_price - 1) * 100, 2),
            "expected_units_change_pct": round((qty_ratio - 1) * 100, 2),
            "expected_daily_profit_current": round(profit(current_price), 2),
            "expected_daily_profit_proposed": round(profit(price), 2),
            "baseline_daily_units": round(q_cur, 2),
        }

    def summarise(self, r: dict[str, Any]) -> str:
        return (f"ε={r['elasticity']} (R² {r['model_r2']}) → ₹{r['proposed_price']:.0f} "
                f"({r['price_change_pct']:+.1f}%), volume {r['expected_units_change_pct']:+.1f}%")
