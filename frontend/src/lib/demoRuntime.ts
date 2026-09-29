/* In-browser demo runtime.
 * When NEXT_PUBLIC_DEMO_MODE=true (GitHub Pages build) this replaces window.fetch / EventSource for the
 * AxioNex API with a TypeScript port of the same engines running on seeded synthetic data.
 * Nothing leaves the browser. */
import { DEMO } from "./config";

/* eslint-disable @typescript-eslint/no-explicit-any */
const DAY = 86_400_000;
const rngFactory = (seed: number) => () => {
  seed |= 0; seed = (seed + 0x6d2b79f5) | 0;
  let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
  t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
  return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
};
const rand = rngFactory(42);
const gauss = (r: () => number = rand) => Math.sqrt(-2 * Math.log(1 - r())) * Math.cos(2 * Math.PI * r());
const mean = (a: number[]) => (a.length ? a.reduce((x, y) => x + y, 0) / a.length : 0);
const std = (a: number[]) => { const m = mean(a); return Math.sqrt(mean(a.map((x) => (x - m) ** 2))); };
const median = (a: number[]) => { const s = [...a].sort((x, y) => x - y); const h = s.length >> 1; return s.length % 2 ? s[h] : (s[h - 1] + s[h]) / 2; };
const pct = (a: number[], p: number) => { const s = [...a].sort((x, y) => x - y); return s[Math.min(s.length - 1, Math.floor((p / 100) * s.length))]; };
const r2 = (x: number, d = 2) => Math.round(x * 10 ** d) / 10 ** d;

const WH = [
  ["HYD", "Hyderabad Fulfilment Hub", 17.385, 78.4867], ["BOM", "Mumbai Bhiwandi Hub", 19.2967, 73.0631],
  ["DEL", "Delhi Bilaspur Hub", 28.4089, 77.025], ["BLR", "Bengaluru Hoskote Hub", 13.0707, 77.798],
  ["CCU", "Kolkata Dankuni Hub", 22.68, 88.29],
] as const;
const PRODUCTS = [
  ["OMX-TEE-001", "Heavyweight Oversized Tee", "tops", 420, 1199, null, 34], ["OMX-DEN-014", "Selvedge Denim Jacket", "outerwear", 1650, 4499, null, 11],
  ["OMX-HOD-007", "Brushed Fleece Hoodie", "outerwear", 780, 2199, 1799, 19], ["OMX-SNK-022", "Trail Runner Sneaker", "footwear", 1900, 5299, null, 9],
  ["OMX-KUR-031", "Handloom Linen Kurta", "ethnic", 650, 1899, null, 15],
] as const;
const INTEL = [
  ["Festive season demand surge expected from mid-October: analysts see rising demand of 18-25% for ethnic wear and outerwear across metro markets.", "market_trend", "retail-pulse"],
  ["Cotton yarn prices increased 6% month over month; several D2C brands are absorbing costs and holding shelf prices to protect volume.", "market_trend", "textile-weekly"],
  ["Competitor NorthLoop launched a price war on oversized tees with aggressive discount bundles, clearance pricing near 10% below last quarter.", "competitor", "scrape-log-north"],
  ["Brand guideline: premium positioning. Avoid discounting beyond 15% off list price; never advertise below MAP on hoodies.", "brand_guideline", "brand-book-v3"],
  ["Sneaker category shows weak demand in tier-1 cities after monsoon slowdown, with returns spike on size-fit issues.", "market_trend", "footwear-insights"],
  ["Handloom linen kurtas trending on social commerce; viral creator drops caused stockout risk on top SKUs in Hyderabad and Bengaluru.", "market_trend", "social-listening"],
  ["Kaarigar Co. raised denim jacket prices by 4% following a supply crunch in selvedge fabric.", "competitor", "scrape-log-kaarigar"],
] as const;
const POS = ["surge", "spike", "festive", "demand up", "shortage", "sold out", "viral", "trending", "stockout", "rising demand", "supply crunch"];
const NEG = ["discount", "clearance", "slowdown", "weak demand", "oversupply", "price war", "markdown", "decline", "returns spike", "falling demand"];
const ARMS = [0.94, 0.97, 1.0, 1.03, 1.06];

interface P { id: string; sku: string; name: string; category: string; cost: number; current_price: number; map_price: number | null; base: number; prices: number[]; units: number[]; comps: number[]; inv: { code: string; on_hand: number; reserved: number; lead: number }[]; last: any }
let world: P[] | null = null;
const runs = new Map<string, { events: any[]; decision: any; pid: string; applied: boolean }>();
const bandits = new Map<string, { n: number[]; s: number[]; q: number[] }>();

function getWorld(): P[] {
  if (world) return world;
  world = PRODUCTS.map(([sku, name, category, cost, price, map, base]) => {
    let p = price as number; const prices: number[] = [], units: number[] = [];
    for (let d = 0; d < 60; d++) {
      p = Math.min(price * 1.12, Math.max(price * 0.88, p * (1 + gauss() * 0.03)));
      prices.push(r2(p)); units.push(Math.max(1, Math.floor(base * (p / price) ** -2.1 * Math.exp(gauss() * 0.12))));
    }
    return {
      id: sku, sku, name, category, cost, current_price: price, map_price: map, base, prices, units,
      comps: [0, 1, 2].map(() => Math.round(price * (0.94 + rand() * 0.14))),
      inv: WH.map(([code]) => ({ code, on_hand: Math.floor(base * (3 + rand() * 11)), reserved: Math.floor(base * rand() * 0.6), lead: 2 + Math.floor(rand() * 5) })),
      last: null,
    };
  });
  return world;
}

/* ---------- engines (mirror of the Python implementations) ---------- */
function fitDemand(prices: number[], units: number[], priorE = -1.8, lam = 0.05) {
  const x = prices.map(Math.log), y = units.map((u) => Math.log(Math.max(u, 1)));
  const xm = mean(x), ym = mean(y);
  const sxx = x.reduce((a, v) => a + (v - xm) ** 2, 0), sxy = x.reduce((a, v, i) => a + (v - xm) * (y[i] - ym), 0);
  let e = (sxy + lam * priorE) / (sxx + lam); e = Math.min(-1.05, Math.max(-4.5, e));
  const a = ym - e * xm, res = y.map((v, i) => v - (a + e * x[i]));
  const sst = y.reduce((s, v) => s + (v - ym) ** 2, 0) || 1, sse = res.reduce((s, v) => s + v * v, 0);
  return { e, r2: Math.max(0, 1 - sse / sst), se: Math.sqrt(sse / Math.max(x.length - 2, 1) / (sxx + lam)), n: x.length };
}
const trendScore = (snips: { text: string; score: number }[]) => {
  let pos = 0, neg = 0;
  for (const s of snips) { const t = s.text.toLowerCase(); pos += s.score * POS.filter((k) => t.includes(k)).length; neg += s.score * NEG.filter((k) => t.includes(k)).length; }
  return pos + neg === 0 ? 0 : (pos - neg) / (pos + neg);
};
const tokens = (t: string) => t.toLowerCase().match(/[a-z0-9]+/g) ?? [];
function retrieve(q: string, k: number) {
  const qt = new Set(tokens(q));
  return INTEL.map(([text, kind, source]) => { const ov = tokens(text).filter((w) => qt.has(w)).length; return { text, kind, source, score: r2(ov / Math.sqrt(tokens(text).length), 4) }; })
    .sort((a, b) => b.score - a.score).slice(0, k);
}
function propose(p: P, days: number, snips: any[], c: { min_margin: number; max_change_pct: number }) {
  const m = fitDemand(p.prices, p.units), cur = p.current_price, qCur = mean(p.units.slice(-14));
  const pOpt = (p.cost * m.e) / (1 + m.e), compMed = median(p.comps);
  let w = Math.min(0.85, 0.35 + 0.5 * m.r2); w *= Math.exp(-2 * Math.abs(Math.log(pOpt / cur)));
  const blend = w * pOpt + (1 - w) * compMed * 0.99, ts = trendScore(snips), trend = blend * (1 + 0.03 * ts);
  const inv = days > 60 ? -Math.min(0.06, (days - 60) / 1000) : days < 10 ? Math.min(0.04, (10 - days) * 0.005) : 0;
  const target = trend * (1 + inv);
  const hardLo = Math.max(p.cost / (1 - c.min_margin), p.map_price ?? 0);
  let hi = Math.max(Math.min(cur * (1 + c.max_change_pct), Math.max(...p.comps) * 1.15), hardLo);
  const lo = Math.min(Math.max(hardLo, cur * (1 - c.max_change_pct)), hi);
  const clamped = Math.min(Math.max(target, lo), hi); let price = clamped;
  let charm = Math.floor(price / 10) * 10 + 9; if (charm > price) charm -= 10; if (charm >= lo && charm <= hi) price = charm;
  price = r2(price);
  const profit = (x: number) => (x - p.cost) * qCur * (x / cur) ** m.e, ratio = (price / cur) ** m.e;
  return {
    elasticity: r2(m.e, 3), elasticity_se: r2(m.se, 3), model_r2: r2(m.r2, 3), model_source: "posterior", observations: m.n, profit_maximising_price: r2(pOpt),
    competitor_median: r2(compMed), trend_score: r2(ts, 3), inventory_adjustment_pct: r2(inv * 100), bounds: { low: r2(lo), high: r2(hi) },
    current_price: cur, proposed_price: price, price_change_pct: r2((price / cur - 1) * 100), expected_units_change_pct: r2((ratio - 1) * 100),
    expected_daily_profit_current: r2(profit(cur)), expected_daily_profit_proposed: r2(profit(price)), baseline_daily_units: r2(qCur),
    explain: [["Profit-maximising price", pOpt], ["Blended with rivals", blend], ["Market trend", trend], ["Stock cover", target], ["Guardrails", clamped], ["Price ending", price]].map(([label, v]) => ({ label, price: r2(v as number) })),
  };
}
const hav = (a: number, b: number, c: number, d: number) => { const t = Math.PI / 180, dl = (c - a) * t, dg = (d - b) * t; const h = Math.sin(dl / 2) ** 2 + Math.cos(a * t) * Math.cos(c * t) * Math.sin(dg / 2) ** 2; return 12742 * Math.asin(Math.sqrt(h)); };
function inventoryPlan(p: P, price: number, e: number, req: any) {
  const rows = p.inv.map((i) => { const w = WH.find((x) => x[0] === i.code)!; return { ...i, name: w[1], dist: hav(req.customer_lat, req.customer_lon, w[2], w[3]), avail: Math.max(0, i.on_hand - i.reserved) }; }).sort((a, b) => a.dist - b.dist);
  const position = rows.reduce((s, r) => s + r.avail, 0), lead = mean(rows.map((r) => r.lead));
  const mu = Math.max(0.1, mean(p.units.slice(-14)) * (price / p.current_price) ** e), sigma = std(p.units.slice(-30));
  const safety = 1.65 * sigma * Math.sqrt(Math.max(lead, 1)), rop = mu * lead + safety, qty = Math.max(0, Math.ceil(mu * (lead + 7) + safety - position)), cover = position / mu;
  const f = rows.find((r) => r.avail > 0);
  return { status: position <= rop ? "reorder" : cover > 60 ? "overstock" : "healthy", days_of_cover: r2(cover, 1), available_units: position, expected_daily_demand: r2(mu), safety_stock: Math.ceil(safety), reorder_point: Math.ceil(rop), avg_lead_time_days: r2(lead, 1), recommended_order_qty: qty, order_value: r2(qty * p.cost), fulfilment_warehouse: f ? { warehouse: f.code, name: f.name, distance_km: r2(f.dist, 1), available: f.avail } : null, routing: rows.slice(0, 4).map((r) => ({ warehouse: r.code, name: r.name, distance_km: r2(r.dist, 1), available: r.avail })) };
}

function executeRun(p: P, req: any) {
  const ev: any[] = [], push = (type: string, node: string | null, data: any) => ev.push({ type, node, data });
  push("run.started", null, { product_id: p.id });
  const snips = retrieve(`${p.name} ${p.category} demand pricing trend competitor`, 6);
  const stock = p.inv.reduce((s, i) => s + i.on_hand - i.reserved, 0), days = stock / Math.max(mean(p.units.slice(-14)), 0.1);
  push("node.started", "context", { attempt: 0 });
  push("node.completed", "context", { summary: `60 demand points, ${p.comps.length} competitors, ${snips.length} intel snippets, ${stock} units on hand`, detail: { sku: p.sku, name: p.name, cost: p.cost, current_price: p.current_price } });
  const c = { min_margin: req.min_margin ?? 0.25, max_change_pct: req.max_change_pct ?? 0.12 };
  let pr: any, inv: any, risk: any, attempts = 0;
  do {
    attempts++;
    push("node.started", "pricing", { attempt: attempts - 1 }); pr = propose(p, days, snips, c);
    push("node.completed", "pricing", { summary: `attempt ${attempts}: ε=${pr.elasticity} (R² ${pr.model_r2}) → ₹${Math.round(pr.proposed_price)} (${pr.price_change_pct >= 0 ? "+" : ""}${pr.price_change_pct}%), volume ${pr.expected_units_change_pct >= 0 ? "+" : ""}${pr.expected_units_change_pct}%`, detail: pr });
    push("node.started", "inventory", { attempt: attempts - 1 }); inv = inventoryPlan(p, pr.proposed_price, pr.elasticity, req);
    push("node.completed", "inventory", { summary: `${inv.status}: ${inv.days_of_cover}d cover, order ${inv.recommended_order_qty} units, ship from ${inv.fulfilment_warehouse?.warehouse ?? "none"}`, detail: inv });
    push("node.started", "risk", { attempt: attempts - 1 });
    const price = pr.proposed_price, margin = (price - p.cost) / price, chg = Math.abs(price / p.current_price - 1);
    const checks = [
      ["margin_floor", margin >= c.min_margin - 1e-9], ["map_compliance", p.map_price == null || price >= p.map_price], ["change_limit", chg <= (req.max_change_pct ?? 0.12) + 1e-9],
      ["volume_drop", pr.expected_units_change_pct >= -25], ["profit_regression", pr.expected_daily_profit_proposed >= 0.98 * pr.expected_daily_profit_current || days > 60],
      ["competitor_ceiling", price <= 1.25 * Math.max(...p.comps)], ["po_budget", inv.order_value <= 500000],
    ].map(([rule, ok]) => ({ rule, passed: ok, detail: "" }));
    const failed = checks.filter((k) => !k.passed).map((k) => k.rule);
    risk = { approved: failed.length === 0, checks, score: r2(checks.filter((k) => k.passed).length / checks.length, 3) };
    push("node.completed", "risk", { summary: risk.approved ? "approved" : `rejected (${failed.join(", ")}); tightening step size`, detail: risk });
    if (!risk.approved) c.max_change_pct = r2(c.max_change_pct * 0.5, 4);
  } while (!risk.approved && attempts < 3);
  const moves = risk.approved && Math.abs(pr.price_change_pct) >= 0.5, base = pr.expected_daily_profit_current || 1;
  const decision = {
    action: moves ? "reprice" : "hold", approved: risk.approved, sku: p.sku, old_price: p.current_price, new_price: moves ? pr.proposed_price : p.current_price,
    price_change_pct: moves ? pr.price_change_pct : 0, expected_profit_delta_pct: moves ? r2((pr.expected_daily_profit_proposed / base - 1) * 100) : 0,
    expected_units_change_pct: moves ? pr.expected_units_change_pct : 0, reorder_qty: inv.recommended_order_qty, inventory_status: inv.status,
    fulfilment_warehouse: inv.fulfilment_warehouse, risk_score: risk.score, attempts, applied: false, explain: pr.explain,
    reasons: risk.checks.filter((k: any) => !k.passed).map((k: any) => k.rule),
  };
  push("node.started", "finalize", { attempt: attempts }); push("node.completed", "finalize", { summary: `${decision.action}: ₹${Math.round(decision.old_price)} → ₹${Math.round(decision.new_price)}, reorder ${decision.reorder_qty}`, detail: decision });
  push("run.completed", null, decision);
  return { events: ev, decision };
}

/* ---------- forecast (Holt-Winters, damped trend) ---------- */
function hw(y: number[], m: number, a: number, b: number, g: number) {
  const PHI = 0.92; let level = mean(y.slice(0, m)), trend = (mean(y.slice(m, 2 * m)) - level) / m; const season = y.slice(0, m).map((v) => v - level), fit: number[] = [];
  y.forEach((obs, t) => { const s = season[t % m]; fit.push(level + PHI * trend + s); const nl = a * (obs - s) + (1 - a) * (level + PHI * trend); trend = b * (nl - level) + (1 - b) * PHI * trend; season[t % m] = g * (obs - nl) + (1 - g) * s; level = nl; });
  return { fit, level, trend, season };
}
function bestHw(y: number[], m: number) {
  let best: any = null;
  for (const a of [0.1, 0.3, 0.5]) for (const b of [0.01, 0.05, 0.1]) for (const g of [0.1, 0.3, 0.5]) { const r = hw(y, m, a, b, g); const sse = y.slice(m).reduce((s, v, i) => s + (v - r.fit[i + m]) ** 2, 0); if (!best || sse < best.sse) best = { ...r, sse, params: [a, b, g] }; }
  return best;
}
const project = (r: any, n: number, m: number, h: number) => Array.from({ length: h }, (_, i) => { let d = 0; for (let k = 1; k <= i + 1; k++) d += 0.92 ** k; return Math.max(0, r.level + d * r.trend + r.season[(n + i) % m]); });
function forecast(p: P, horizon: number) {
  const y = p.units, m = 7, r = bestHw(y, m), resid = y.slice(m).map((v, i) => v - r.fit[i + m]), sigma = std(resid) || 1;
  const mu = project(r, y.length, m, horizon), width = mu.map((_, i) => 1.2816 * sigma * Math.sqrt(1 + 0.15 * i));
  const tr = y.slice(0, -14), rb = bestHw(tr, m), pred = project(rb, tr.length, m, 14);
  const mape = mean(y.slice(-14).map((v, i) => Math.abs(v - pred[i]) / Math.max(v, 1))) * 100;
  const med = median(resid), mad = median(resid.map((v) => Math.abs(v - med))) || 1e-9;
  const now = Date.now(), date = (i: number) => new Date(now + (i - y.length + 1) * DAY).toISOString().slice(0, 10);
  const anomalies = resid.map((v, i) => ({ index: i + m, units: y[i + m], z: r2((0.6745 * (v - med)) / mad) })).filter((a) => Math.abs(a.z) > 3.5 && a.index >= y.length - 45).map((a) => ({ ...a, date: date(a.index) }));
  return {
    mean: mu.map((v) => r2(v)), lower: mu.map((v, i) => r2(Math.max(v - width[i], 0))), upper: mu.map((v, i) => r2(v + width[i])), mape: r2(mape, 1), anomalies,
    seasonality: r.season.map((s: number) => r2((r.level + s) / r.level, 3)), trend_pct_per_week: r2(((r.trend * 7) / Math.max(r.level, 1e-9)) * 100),
    method: `holt-winters(alpha=${r.params[0]}, beta=${r.params[1]}, gamma=${r.params[2]})`,
    history: y.slice(-45).map((u, i) => ({ date: date(y.length - 45 + i), units: u })), dates: Array.from({ length: horizon }, (_, i) => date(y.length + i)),
  };
}

/* ---------- Monte Carlo simulator ---------- */
function simulate(p: P, price: number, samples: number, H: number) {
  const m = fitDemand(p.prices, p.units), qCur = mean(p.units.slice(-14)), r = rngFactory(7);
  const es: number[] = [], noise: number[] = [];
  for (let i = 0; i < samples; i++) { es.push(Math.min(m.e + gauss(r) * Math.max(m.se, 0.05), -1.02)); noise.push(Math.exp((gauss(r) * 0.12) / Math.sqrt(H))); }
  const base = noise.map((n) => (p.current_price - p.cost) * qCur * H * n), prof = (x: number) => es.map((e, i) => (x - p.cost) * qCur * H * (x / p.current_price) ** e * noise[i]);
  const up = prof(price).map((v, i) => v - base[i]), sorted = [...up].sort((a, b) => a - b), tail = sorted.slice(0, Math.max(1, Math.floor(samples * 0.05)));
  const lo = sorted[0], hi = sorted[sorted.length - 1], bins = 24, step = (hi - lo || 1) / bins, counts = new Array(bins).fill(0);
  up.forEach((v) => counts[Math.min(bins - 1, Math.floor((v - lo) / step))]++);
  const curve = Array.from({ length: 13 }, (_, i) => { const x = p.current_price * (0.85 + (i * 0.3) / 12), d = prof(x).map((v, k) => v - base[k]); return { price: r2(x), mean: r2(mean(d)), p5: r2(pct(d, 5)), p95: r2(pct(d, 95)) }; });
  return {
    sku: p.sku, current_price: p.current_price, elasticity: r2(m.e, 3), elasticity_se: r2(m.se, 3), horizon_days: H, samples, candidate_price: r2(price),
    expected_uplift: r2(mean(up)), uplift_p5: r2(pct(up, 5)), uplift_p50: r2(pct(up, 50)), uplift_p95: r2(pct(up, 95)), prob_uplift: r2(up.filter((v) => v > 0).length / samples, 4),
    cvar5: r2(mean(tail)), expected_baseline_profit: r2(mean(base)), histogram: { edges: Array.from({ length: bins + 1 }, (_, i) => r2(lo + i * step)), counts }, curve,
  };
}

/* ---------- Thompson bandit ---------- */
function bandit(p: P) { if (!bandits.has(p.sku)) bandits.set(p.sku, { n: ARMS.map(() => 0), s: ARMS.map(() => 0), q: ARMS.map(() => 0) }); return bandits.get(p.sku)!; }
function banditSummary(p: P) {
  const b = bandit(p), baseline = (p.current_price - p.cost) * mean(p.units.slice(-14));
  const vars = b.n.map((n, i) => (n >= 2 ? Math.max(b.q[i] / n - (b.s[i] / n) ** 2, 0) : null)).filter((v) => v !== null) as number[];
  const pooled = Math.max(vars.length ? Math.sqrt(mean(vars)) : 0.25 * baseline, 0.02 * baseline, 1e-6);
  const means = b.n.map((n, i) => (n ? b.s[i] / n : baseline)), sds = b.n.map((n) => pooled / Math.sqrt(n + 1));
  return { means, sds, baseline };
}
const chooseArm = (p: P) => { const { means, sds } = banditSummary(p); const d = means.map((m, i) => m + gauss(Math.random) * sds[i]); return d.indexOf(Math.max(...d)); };
function banditState(p: P) {
  const b = bandit(p), { means, sds } = banditSummary(p), wins = ARMS.map(() => 0), D = 2000;
  for (let i = 0; i < D; i++) { const d = means.map((m, k) => m + gauss(Math.random) * sds[k]); wins[d.indexOf(Math.max(...d))]++; }
  return { sku: p.sku, total_pulls: b.n.reduce((a, c) => a + c, 0), arms: ARMS.map((m, i) => ({ arm: i, multiplier: m, price: r2(p.current_price * m), pulls: b.n[i], mean_profit: b.n[i] ? r2(means[i]) : null, prob_best: r2(wins[i] / D, 3) })) };
}

/* ---------- browser-side photo analysis (no CNN in demo) ---------- */
async function analyzeImage(file: File) {
  const bmp = await createImageBitmap(file), cv = document.createElement("canvas"); cv.width = cv.height = 64;
  const cx = cv.getContext("2d")!; cx.drawImage(bmp, 0, 0, 64, 64); const d = cx.getImageData(0, 0, 64, 64).data;
  const px: number[][] = []; for (let i = 0; i < d.length; i += 4) px.push([d[i], d[i + 1], d[i + 2]]);
  let cs = [px[100], px[1000], px[2000], px[3500]].map((c) => [...c]); let lab: number[] = [];
  for (let it = 0; it < 8; it++) { lab = px.map((p) => { let bi = 0, bd = 1e18; cs.forEach((c, i) => { const dd = (p[0] - c[0]) ** 2 + (p[1] - c[1]) ** 2 + (p[2] - c[2]) ** 2; if (dd < bd) { bd = dd; bi = i; } }); return bi; }); cs = cs.map((c, i) => { const m = px.filter((_, k) => lab[k] === i); return m.length ? [0, 1, 2].map((ch) => mean(m.map((q) => q[ch]))) : c; }); }
  const palette = cs.map((c, i) => ({ name: "dominant", hex: "#" + c.map((v) => Math.round(v).toString(16).padStart(2, "0")).join(""), share: r2(lab.filter((l) => l === i).length / px.length, 3) })).sort((a, b) => b.share - a.share);
  const g = px.map((p) => 0.299 * p[0] + 0.587 * p[1] + 0.114 * p[2]); let lv: number[] = [];
  for (let y = 1; y < 63; y++) for (let x = 1; x < 63; x++) lv.push(-4 * g[y * 64 + x] + g[(y - 1) * 64 + x] + g[(y + 1) * 64 + x] + g[y * 64 + x - 1] + g[y * 64 + x + 1]);
  const sharp = std(lv) ** 2, bright = mean(g) / 255, contrast = std(g) / 255;
  const score = 0.5 * Math.min(1, sharp / 300) + 0.3 * (1 - Math.abs(bright - 0.55) / 0.55) + 0.2 * Math.min(1, contrast / 0.25);
  return { width: bmp.width, height: bmp.height, backbone: "browser-canvas", calibrated: false, quality: { sharpness: r2(sharp, 1), brightness: r2(bright, 3), contrast: r2(contrast, 3), photo_quality: r2(Math.max(0, Math.min(1, score)), 3) }, palette, attributes: null, defects: null, defect_risk: null, aesthetic_score: null, note: "Demo mode analyses the photo in your browser; the CNN runs in the full backend.", indexed: false };
}

/* ---------- install ---------- */
const json = (data: any, status = 200) => new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });
const product = (sku: string) => getWorld().find((p) => p.sku === sku);

function install() {
  const realFetch = window.fetch.bind(window);
  window.fetch = async (input: any, init?: RequestInit) => {
    const url = new URL(typeof input === "string" ? input : input instanceof URL ? input.href : input.url, location.href);
    if (url.pathname.endsWith("/health")) return json({ status: "ok", checks: { browser_demo: true } });
    const i = url.pathname.indexOf("/api/v1/"); if (i < 0) return realFetch(input, init);
    const route = url.pathname.slice(i + 8), method = (init?.method ?? "GET").toUpperCase();
    const body = typeof init?.body === "string" ? JSON.parse(init.body) : init?.body;
    await new Promise((r) => setTimeout(r, 120));
    let m: RegExpMatchArray | null;
    if (route === "agents/products") return json(getWorld().map((p) => ({ id: p.id, sku: p.sku, name: p.name, category: p.category, cost: p.cost, current_price: p.current_price, map_price: p.map_price, available_units: p.inv.reduce((s, x) => s + x.on_hand - x.reserved, 0), last_decision: p.last })));
    if (route === "agents/run" && method === "POST") {
      const p = product(body.product_id ?? body.sku); if (!p) return json({ detail: "Product not found" }, 404);
      const id = "demo-" + Math.random().toString(36).slice(2, 10), { events, decision } = executeRun(p, body);
      runs.set(id, { events, decision, pid: p.sku, applied: false });
      if (body.auto_apply && decision.action === "reprice") { p.current_price = decision.new_price; decision.applied = true; runs.get(id)!.applied = true; }
      p.last = decision; return json({ run_id: id, stream_url: `/api/v1/agents/runs/${id}/stream` }, 202);
    }
    if ((m = route.match(/^agents\/runs\/([^/]+)\/apply$/))) {
      const r = runs.get(m[1]); if (!r || !r.decision.approved || r.decision.action !== "reprice") return json({ detail: "Only approved repricing decisions can be applied" }, 409);
      if (r.applied) return json({ detail: "Decision already applied" }, 409);
      product(r.pid)!.current_price = r.decision.new_price; r.applied = true; r.decision.applied = true; return json({ id: m[1], status: "completed", decision: r.decision });
    }
    if (route === "rag/query" && method === "POST") { const s = retrieve(body.question, body.k ?? 5); return json({ answer: s.slice(0, 3).map((x, k) => `${x.text} [${k + 1}]`).join(" "), mode: "extractive", sources: s }); }
    if (route === "compliance/checklist") return json([
      ["privacy_policy","Privacy policy page"],["terms_page","T&C's page"],["cookies_policy","Cookies policy"],
      ["cookie_consent","Check for cookie consent"],["refund_policy","Refund policy"],["form_consent","Form consent"],
      ["data_minimisation","Only collect necessary data"],["tracking","Check tracking"],["third_party_embeds","Check 3rd party embeds"],
      ["accessibility","Fix accessibility"],["alt_text","Alt text on images"],["colour_contrast","Check colour contrast"],
      ["keyboard_forms","Keyboard-friendly forms"],["button_labels","Clear button labels"],["fake_reviews","Remove fake reviews"],
      ["false_claims","Remove false claims"],["business_details","Business details"],["image_copyright","Image copyright"],
      ["dpdp_compliant","DPDP Act compliant"],["other_risks","Flag other risks"],
    ].map(([key,label])=>({key,label})));
    if (route === "compliance/scan" && method === "POST") {
      await new Promise((r) => setTimeout(r, 700));
      const statuses = ["pass","warn","fail","info","unknown"];
      const labels: [string,string][] = [
        ["privacy_policy","Privacy policy page"],["terms_page","T&C's page"],["cookies_policy","Cookies policy"],
        ["cookie_consent","Check for cookie consent"],["refund_policy","Refund policy"],["form_consent","Form consent"],
        ["data_minimisation","Only collect necessary data"],["tracking","Check tracking"],["third_party_embeds","Check 3rd party embeds"],
        ["accessibility","Fix accessibility"],["alt_text","Alt text on images"],["colour_contrast","Check colour contrast"],
        ["keyboard_forms","Keyboard-friendly forms"],["button_labels","Clear button labels"],["fake_reviews","Remove fake reviews"],
        ["false_claims","Remove false claims"],["business_details","Business details"],["image_copyright","Image copyright"],
        ["dpdp_compliant","DPDP Act compliant"],["other_risks","Flag other risks"],
      ];
      const checks = labels.map(([key,label],i)=>{ const st = statuses[Math.floor(rand()*100+i)%statuses.length===0?0:Math.floor(rand()*4)];
        const status = rand() < 0.55 ? "pass" : rand() < 0.75 ? "info" : rand() < 0.9 ? "warn" : "fail";
        return { key, label, status, detail: "Demo-mode result on seeded data; connect the full backend to scan a real URL.", evidence: [] }; });
      const counts: any = { pass:0, warn:0, fail:0, info:0, unknown:0 }; checks.forEach((c)=>counts[c.status]++);
      const score = Math.round(100*(counts.pass+0.5*counts.info)/checks.length);
      return json({ url: (body as any).url, status_code: 200, score, counts, checks, dpdp_score: Math.max(40, score-10), disclaimer: "Not legal advice — have a lawyer review before you rely on this." });
    }
    if (route === "vision/analyze" && method === "POST") { const f = (body as FormData).get("file") as File; try { return json(await analyzeImage(f)); } catch { return json({ detail: "Could not decode image" }, 422); } }
    if ((m = route.match(/^insights\/forecast\/([^/?]+)$/))) { const p = product(m[1]); return p ? json(forecast(p, Math.min(60, Number(url.searchParams.get("horizon") ?? 14)))) : json({ detail: "Unknown SKU" }, 404); }
    if (route === "insights/simulate" && method === "POST") { const p = product(body.sku); return p ? json(simulate(p, body.price, body.samples ?? 4000, body.horizon_days ?? 14)) : json({ detail: "Unknown SKU" }, 404); }
    if ((m = route.match(/^insights\/experiments\/([^/]+)(?:\/(simulate|reset))?$/))) {
      const p = product(m[1]); if (!p) return json({ detail: "Unknown SKU" }, 404);
      if (m[2] === "reset") { bandits.delete(p.sku); return json({ reset: true }); }
      if (m[2] === "simulate") {
        const e = fitDemand(p.prices, p.units).e, q = mean(p.units.slice(-14)), b = bandit(p);
        for (let k = 0; k < (body.rounds ?? 200); k++) { const a = chooseArm(p), price = p.current_price * ARMS[a], prof = (price - p.cost) * q * ARMS[a] ** e * Math.exp(gauss(Math.random) * 0.15); b.n[a]++; b.s[a] += prof; b.q[a] += prof * prof; }
      }
      return json(banditState(p));
    }
    return json({ detail: "Not found" }, 404);
  };

  class DemoEventSource {
    onmessage: ((e: MessageEvent) => void) | null = null; onerror: (() => void) | null = null; private timers: number[] = [];
    constructor(url: string) {
      const id = url.match(/runs\/([^/]+)\/stream/)?.[1] ?? "", run = runs.get(id);
      if (!run) { this.timers.push(window.setTimeout(() => this.onerror?.(), 50)); return; }
      let t = 250; run.events.forEach((ev) => { t += ev.type === "node.started" ? 120 : ev.type === "node.completed" ? 650 : 200;
        this.timers.push(window.setTimeout(() => this.onmessage?.({ data: JSON.stringify({ ...ev, ts: new Date().toISOString() }) } as MessageEvent), t)); });
    }
    close() { this.timers.forEach(clearTimeout); }
  }
  (window as any).EventSource = DemoEventSource;
}

if (typeof window !== "undefined" && DEMO) install();
export {};
