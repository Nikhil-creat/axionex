"""Demand forecasting: additive Holt-Winters (weekly seasonality, damped trend), prediction bands,
rolling-origin backtest and robust (MAD) anomaly detection."""
import itertools
from typing import Any

import numpy as np

PHI = 0.92  # trend damping


def _hw(y: np.ndarray, m: int, a: float, b: float, g: float):
    level = float(y[:m].mean())
    trend = float((y[m:2 * m].mean() - y[:m].mean()) / m)
    season = list((y[:m] - level).astype(float))
    fitted = np.zeros(len(y))
    for t, obs in enumerate(y):
        s = season[t % m]
        fitted[t] = level + PHI * trend + s
        new_level = a * (obs - s) + (1 - a) * (level + PHI * trend)
        trend = b * (new_level - level) + (1 - b) * PHI * trend
        season[t % m] = g * (obs - new_level) + (1 - g) * s
        level = new_level
    return fitted, level, trend, season


def _fit(y: np.ndarray, m: int):
    best = None
    for a, b, g in itertools.product((0.1, 0.3, 0.5), (0.01, 0.05, 0.1), (0.1, 0.3, 0.5)):
        fitted, level, trend, season = _hw(y, m, a, b, g)
        sse = float(((y[m:] - fitted[m:]) ** 2).sum())
        if best is None or sse < best[0]:
            best = (sse, fitted, level, trend, season, (a, b, g))
    return best


def _project(level: float, trend: float, season: list[float], n: int, m: int, horizon: int) -> np.ndarray:
    out = []
    for h in range(1, horizon + 1):
        damp = sum(PHI ** k for k in range(1, h + 1))
        out.append(level + damp * trend + season[(n + h - 1) % m])
    return np.maximum(np.array(out), 0.0)


def forecast_demand(units: list[float], horizon: int = 14, m: int = 7) -> dict[str, Any]:
    y = np.asarray(units, dtype=float)
    if len(y) < 3 * m:
        mean = float(y.mean()) if len(y) else 0.0
        return {"mean": [mean] * horizon, "lower": [mean * 0.7] * horizon, "upper": [mean * 1.3] * horizon,
                "mape": None, "anomalies": [], "seasonality": [1.0] * m, "trend_pct_per_week": 0.0, "method": "mean"}
    _, fitted, level, trend, season, params = _fit(y, m)
    resid = y[m:] - fitted[m:]
    sigma = float(resid.std()) or 1.0
    mean = _project(level, trend, season, len(y), m, horizon)
    width = 1.2816 * sigma * np.sqrt(1 + 0.15 * np.arange(horizon))  # 80% band widening with horizon
    mape = None
    if len(y) >= 42:  # rolling-origin backtest on the last 14 days
        tr, te = y[:-14], y[-14:]
        _, _, lv, td, sn, _ = _fit(tr, m)
        pred = _project(lv, td, sn, len(tr), m, 14)
        mape = float(np.mean(np.abs(te - pred) / np.maximum(te, 1.0)) * 100)
    med = float(np.median(resid))
    mad = float(np.median(np.abs(resid - med))) or 1e-9
    z = 0.6745 * (resid - med) / mad
    anomalies = [{"index": int(i + m), "units": float(y[i + m]), "z": round(float(z[i]), 2)}
                 for i in np.where(np.abs(z) > 3.5)[0]]
    seas_rel = [(float(level) + s) / float(level) if level else 1.0 for s in season]
    return {
        "mean": [round(float(v), 2) for v in mean],
        "lower": [round(float(max(v - w, 0)), 2) for v, w in zip(mean, width)],
        "upper": [round(float(v + w), 2) for v, w in zip(mean, width)],
        "mape": round(mape, 1) if mape is not None else None,
        "anomalies": anomalies, "seasonality": [round(s, 3) for s in seas_rel],
        "trend_pct_per_week": round(float(trend) * 7 / max(level, 1e-9) * 100, 2),
        "method": f"holt-winters(alpha={params[0]}, beta={params[1]}, gamma={params[2]})",
    }
