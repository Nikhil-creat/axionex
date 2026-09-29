"use client";

import { useEffect, useMemo, useState } from "react";
import { V1, inr } from "@/lib/config";

/* eslint-disable @typescript-eslint/no-explicit-any */
const Card = ({ title, children, note }: { title: string; children: React.ReactNode; note?: string }) => (
  <div className="min-w-0 rounded-2xl border border-edge bg-panel p-4">
    <h2 className="text-sm font-medium text-mute">{title}</h2>
    {note && <p className="mt-0.5 text-xs text-mute/80">{note}</p>}
    <div className="mt-3">{children}</div>
  </div>
);

function useSku<T>(sku: string | null, path: (s: string) => string): { data: T | null; error: string | null } {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!sku) return;
    let live = true; setData(null); setError(null);
    fetch(`${V1}${path(sku)}`).then(async (r) => { if (!r.ok) throw new Error((await r.json()).detail ?? "Request failed"); return r.json(); })
      .then((d) => live && setData(d)).catch((e) => live && setError(e.message));
    return () => { live = false; };
  }, [sku]); // eslint-disable-line react-hooks/exhaustive-deps
  return { data, error };
}

export function ForecastPanel({ sku }: { sku: string | null }) {
  const { data, error } = useSku<any>(sku, (s) => `/insights/forecast/${s}?horizon=14`);
  const chart = useMemo(() => {
    if (!data) return null;
    const hist: number[] = data.history.map((h: any) => h.units), n = hist.length, h = data.mean.length, total = n + h;
    const max = Math.max(...hist, ...data.upper) * 1.08, W = 340, H = 140;
    const x = (i: number) => (i / (total - 1)) * W, y = (v: number) => H - (v / max) * H;
    const line = (arr: number[], off: number) => arr.map((v, i) => `${i ? "L" : "M"}${x(i + off).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
    const band = [...data.upper.map((v: number, i: number) => `${x(n + i).toFixed(1)},${y(v).toFixed(1)}`), ...data.lower.map((v: number, i: number) => `${x(n + h - 1 - i).toFixed(1)},${y(data.lower[h - 1 - i]).toFixed(1)}`)].join(" ");
    const anomalies = data.anomalies.map((a: any) => ({ cx: x(data.history.findIndex((p: any) => p.date === a.date)), cy: y(a.units) })).filter((a: any) => a.cx >= 0);
    return { W, H, hist: line(hist, 0), fc: line(data.mean, n), band, anomalies, split: x(n - 1) };
  }, [data]);

  return (
    <Card title="Demand forecast" note="Holt-Winters with weekly seasonality, 80% band, 14 days ahead">
      {error && <p className="text-sm text-coral">{error}</p>}
      {!data && !error && <p className="py-8 text-sm text-mute">Fitting the model…</p>}
      {data && chart && (
        <>
          <svg viewBox={`0 0 ${chart.W} ${chart.H}`} className="w-full" role="img" aria-label="Units sold history and forecast with confidence band">
            <line x1={chart.split} x2={chart.split} y1="0" y2={chart.H} stroke="#2B3468" strokeDasharray="3 3" />
            <polygon points={chart.band} fill="#8577FF" opacity="0.18" />
            <path d={chart.hist} fill="none" stroke="#E7EAFF" strokeWidth="1.6" />
            <path d={chart.fc} fill="none" stroke="#8577FF" strokeWidth="2" strokeDasharray="5 3" />
            {chart.anomalies.map((a: any, i: number) => <circle key={i} cx={a.cx} cy={a.cy} r="3.5" fill="#FF5F7A" />)}
          </svg>
          <div className="mt-3 grid grid-cols-3 gap-2 text-center">
            <div className="rounded-lg bg-ink/60 p-2"><div className="text-xs text-mute">Backtest error</div><div className="font-mono text-sm">{data.mape != null ? `${data.mape}%` : "n/a"}</div></div>
            <div className="rounded-lg bg-ink/60 p-2"><div className="text-xs text-mute">Trend / week</div><div className={`font-mono text-sm ${data.trend_pct_per_week >= 0 ? "text-mint" : "text-amber"}`}>{data.trend_pct_per_week > 0 ? "+" : ""}{data.trend_pct_per_week}%</div></div>
            <div className="rounded-lg bg-ink/60 p-2"><div className="text-xs text-mute">Anomalies</div><div className="font-mono text-sm">{data.anomalies.length}</div></div>
          </div>
        </>
      )}
    </Card>
  );
}

export function SimulatorPanel({ sku, price }: { sku: string | null; price: number | null }) {
  const [delta, setDelta] = useState(-5);
  const [res, setRes] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { setRes(null); }, [sku]);
  useEffect(() => {
    if (!sku || !price) return;
    const t = setTimeout(async () => {
      try {
        const r = await fetch(`${V1}/insights/simulate`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ sku, price: price * (1 + delta / 100), samples: 4000 }) });
        if (!r.ok) throw new Error((await r.json()).detail ?? "Simulation failed");
        setRes(await r.json()); setErr(null);
      } catch (e) { setErr(e instanceof Error ? e.message : "Simulation failed"); }
    }, 250);
    return () => clearTimeout(t);
  }, [sku, price, delta]);
  const maxC = res ? Math.max(...res.histogram.counts) : 1;
  const zero = res ? (() => { const e: number[] = res.histogram.edges; const lo = e[0], hi = e[e.length - 1]; return hi > lo ? Math.min(100, Math.max(0, ((0 - lo) / (hi - lo)) * 100)) : 0; })() : 0;

  return (
    <Card title="What-if simulator" note="4,000 Monte Carlo draws over elasticity uncertainty, 14 days">
      <label className="flex items-center justify-between text-sm">
        <span className="text-mute">Test price</span>
        <span className="font-mono">{price ? inr.format(price * (1 + delta / 100)) : "–"} <span className="text-mute">({delta > 0 ? "+" : ""}{delta}%)</span></span>
      </label>
      <input type="range" min={-15} max={15} step={1} value={delta} onChange={(e) => setDelta(Number(e.target.value))} aria-label="Price change percent" className="mt-2 w-full accent-[#8577FF]" />
      {err && <p className="mt-2 text-sm text-coral">{err}</p>}
      {res && (
        <>
          <div className="mt-3 flex h-20 items-end gap-[2px]" role="img" aria-label="Distribution of profit uplift">
            {res.histogram.counts.map((c: number, i: number) => <div key={i} className={`flex-1 rounded-t ${res.histogram.edges[i] >= 0 ? "bg-mint/80" : "bg-coral/70"}`} style={{ height: `${Math.max(3, (c / maxC) * 100)}%` }} />)}
          </div>
          <div className="relative mt-1 h-3"><div className="absolute top-0 h-3 border-l border-soft/70" style={{ left: `${zero}%` }} /><span className="absolute -top-0.5 text-[10px] text-mute" style={{ left: `calc(${zero}% + 4px)` }}>break-even</span></div>
          <div className="mt-3 grid grid-cols-2 gap-2">
            <div className="rounded-lg bg-ink/60 p-2"><div className="text-xs text-mute">Chance of more profit</div><div className={`font-mono text-sm ${res.prob_uplift >= 0.6 ? "text-mint" : "text-amber"}`}>{Math.round(res.prob_uplift * 100)}%</div></div>
            <div className="rounded-lg bg-ink/60 p-2"><div className="text-xs text-mute">Expected change</div><div className="font-mono text-sm">{inr.format(res.expected_uplift)}</div></div>
            <div className="rounded-lg bg-ink/60 p-2"><div className="text-xs text-mute">Likely range (90%)</div><div className="font-mono text-xs">{inr.format(res.uplift_p5)} to {inr.format(res.uplift_p95)}</div></div>
            <div className="rounded-lg bg-ink/60 p-2"><div className="text-xs text-mute">Worst 5% average</div><div className="font-mono text-sm text-amber">{inr.format(res.cvar5)}</div></div>
          </div>
        </>
      )}
    </Card>
  );
}

export function ExperimentPanel({ sku }: { sku: string | null }) {
  const [state, setState] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const call = async (path: string, method = "GET", body?: unknown) => {
    setBusy(true); setErr(null);
    try {
      const r = await fetch(`${V1}${path}`, { method, headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
      if (!r.ok) throw new Error((await r.json()).detail ?? "Request failed");
      const d = await r.json(); if (d.arms) setState(d); else if (sku) await call(`/insights/experiments/${sku}`);
    } catch (e) { setErr(e instanceof Error ? e.message : "Request failed"); } finally { setBusy(false); }
  };
  useEffect(() => { setState(null); if (sku) call(`/insights/experiments/${sku}`); }, [sku]); // eslint-disable-line react-hooks/exhaustive-deps
  const best = state ? [...state.arms].sort((a: any, b: any) => b.prob_best - a.prob_best)[0] : null;

  return (
    <Card title="Price lab" note="Thompson-sampling bandit: explores five price points and shifts traffic to the winner">
      {err && <p className="mb-2 text-sm text-coral">{err}</p>}
      {state && (
        <ul className="space-y-1.5">
          {state.arms.map((a: any) => (
            <li key={a.arm} className="grid grid-cols-[64px_1fr_44px] items-center gap-2 text-xs">
              <span className="font-mono">{inr.format(a.price)}</span>
              <div className="h-2 overflow-hidden rounded bg-ink"><div className={`h-full ${a === best && state.total_pulls > 0 ? "bg-mint" : "bg-volt/70"}`} style={{ width: `${Math.max(2, a.prob_best * 100)}%` }} /></div>
              <span className="text-right font-mono text-mute">{Math.round(a.prob_best * 100)}%</span>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-2 text-xs text-mute">{state ? `${state.total_pulls} simulated rounds. Bars show the probability each price is the most profitable.` : "Loading…"}</p>
      <div className="mt-3 flex gap-2">
        <button disabled={busy || !sku} onClick={() => sku && call(`/insights/experiments/${sku}/simulate`, "POST", { rounds: 200 })} className="flex-1 rounded-xl border border-volt px-3 py-2 text-sm text-volt hover:bg-volt/10 disabled:opacity-50">Run 200 rounds</button>
        <button disabled={busy || !sku} onClick={() => sku && call(`/insights/experiments/${sku}/reset`, "POST")} className="rounded-xl border border-edge px-3 py-2 text-sm text-mute hover:text-soft disabled:opacity-50">Reset</button>
      </div>
    </Card>
  );
}
