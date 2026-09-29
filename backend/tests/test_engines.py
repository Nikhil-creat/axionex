import numpy as np

from app.agents.pricing_agent import PricingAgent, fit_demand
from app.services.experiments import ARMS, ThompsonBandit
from app.services.forecasting import forecast_demand
from app.services.simulation import simulate_price


def _history(n=60, e=-2.1, base=30, seed=0):
    rng = np.random.default_rng(seed)
    prices = 1000 * np.exp(rng.normal(0, 0.05, n))
    units = [max(1, int(base * (p / 1000) ** e * rng.lognormal(0, 0.1))) for p in prices]
    return list(prices), units


def test_elasticity_recovered():
    p, u = _history()
    m = fit_demand(p, u)
    assert -3.0 < m.elasticity < -1.5 and m.se > 0


def test_pricing_respects_guardrails():
    p, u = _history()
    r = PricingAgent().propose(cost=400, current_price=1000, map_price=None, prices=p, units=u, competitor_prices=[950, 1100],
                               days_cover=30, snippets=[], constraints={"min_margin": 0.25, "max_change_pct": 0.1})
    assert 900 <= r["proposed_price"] <= 1100 and (r["proposed_price"] - 400) / r["proposed_price"] >= 0.25
    assert len(r["explain"]) == 6


def test_forecast_learns_weekly_pattern():
    rng = np.random.default_rng(1)
    y = [50 + 15 * np.sin(2 * np.pi * t / 7) + rng.normal(0, 2) for t in range(70)]
    res = forecast_demand(y, 14)
    assert res["mape"] is not None and res["mape"] < 15
    assert all(l <= m <= u for l, m, u in zip(res["lower"], res["mean"], res["upper"]))


def test_forecast_flags_spike():
    rng = np.random.default_rng(2)
    y = [40 + rng.normal(0, 2) for _ in range(60)]
    y[45] = 120
    assert any(a["index"] == 45 for a in forecast_demand(y, 7)["anomalies"])


def test_simulation_prefers_profitable_price():
    kw = dict(cost=400, current_price=1500, q_cur=20, elasticity=-2.0, se=0.2, seed=3)  # optimum is 800, so cutting is better
    assert simulate_price(candidate_price=1300, **kw)["prob_uplift"] > 0.9
    assert simulate_price(candidate_price=1500, **kw)["expected_uplift"] == 0.0


def test_bandit_converges_to_best_arm():
    rng = np.random.default_rng(4)
    b = ThompsonBandit(np.zeros(5), np.zeros(5), np.zeros(5), 100.0, rng)
    means = [90, 100, 130, 105, 95]
    for _ in range(600):
        a = b.choose()
        b.update(a, rng.normal(means[a], 10))
    assert int(np.argmax(b.n)) == 2 and len(ARMS) == 5


def test_circuit_breaker_and_retry():
    import asyncio
    from app.core.reliability import CircuitBreaker, retry_async
    cb = CircuitBreaker(failures=2, reset_seconds=999)
    cb.record(False); assert cb.allow()
    cb.record(False); assert not cb.allow()
    cb.record(True); assert cb.allow()
    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ValueError("boom")
        return "ok"

    assert asyncio.run(retry_async(flaky, attempts=3, base_delay=0.001)) == "ok" and calls["n"] == 3


SAMPLE_HTML = """
<html>
<head><script type="application/ld+json">
{"@type":"Review","reviewBody":"Great product!","reviewRating":{"ratingValue":"5"}}
</script></head>
<body>
<a href="/privacy-policy">Privacy Policy</a>
<img src="a.jpg">
<div style="color:#ffffff;background-color:#ffffff;">invisible text</div>
<div style="color:#000000;background-color:#ffffff;">readable text</div>
<p>This product is 100% guaranteed and clinically proven to work.</p>
<footer>GSTIN: 27AAAPL1234C1Z5, contact: hello@brand.com, call 9876543210, Mumbai 400001</footer>
</body></html>
"""


def test_contrast_ratio_known_values():
    from app.services.compliance_scanner import contrast_ratio
    assert contrast_ratio("#000000", "#ffffff") == 21.0
    assert contrast_ratio("#ffffff", "#ffffff") == 1.0


def test_compliance_scanner_heuristics():
    import asyncio
    from unittest.mock import AsyncMock, patch
    from app.services.compliance_scanner import ComplianceScanner

    class FakeResp:
        text = SAMPLE_HTML
        status_code = 200
        headers: dict = {}

    with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=FakeResp())):
        report = asyncio.run(ComplianceScanner().scan("https://example.com"))

    by_key = {c["key"]: c for c in report["checks"]}
    assert by_key["privacy_policy"]["status"] == "pass"
    assert by_key["terms_page"]["status"] == "fail"
    assert by_key["alt_text"]["status"] == "fail"  # <img> has no alt
    assert by_key["colour_contrast"]["status"] == "fail"  # white-on-white pair present
    assert by_key["false_claims"]["status"] == "warn"
    assert by_key["business_details"]["status"] == "pass"  # GST/email/phone/pin all present
    assert 0 <= report["score"] <= 100 and report["disclaimer"]
