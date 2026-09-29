"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import "@/lib/demoRuntime";
import { ExperimentPanel, ForecastPanel, SimulatorPanel } from "@/components/LabPanels";
import { PlansAndRoi } from "@/components/Business";
import { CompliancePanel } from "@/components/CompliancePanel";
import { DEMO } from "@/lib/config";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const V1 = `${API}/api/v1`;
const inr = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 });

const AUTHOR = {
  name: "NIKHIL CHARY SRIRAMOJU",
  github: "https://github.com/Nikhil-creat",
  linkedin: "https://in.linkedin.com/in/nikhil-chary-sriramoju-95041b38a",
  email: "sriramojunikhil66@gmail.com",
};

interface Warehouse { warehouse: string; name: string; distance_km: number; available: number }
interface Decision {
  action: string; approved: boolean; sku: string; old_price: number; new_price: number;
  price_change_pct: number; expected_profit_delta_pct: number; expected_units_change_pct: number;
  reorder_qty: number; inventory_status: string; fulfilment_warehouse: Warehouse | null;
  risk_score: number; attempts: number; applied: boolean; reasons: string[]; explain?: { label: string; price: number }[];
}
interface Product {
  id: string; sku: string; name: string; category: string; cost: number; current_price: number;
  map_price: number | null; available_units: number; last_decision: Decision | null;
}
interface MeshEvent { type: string; node: string | null; ts: string; data: any }
interface RagSource { text: string; source: string; kind: string; score: number }
interface VisionResult {
  quality: { photo_quality: number; sharpness: number; brightness: number; contrast: number };
  palette: { name: string; hex: string; share: number }[];
  attributes: { tag: string; prob: number }[] | null;
  aesthetic_score: number | null; defect_risk: number | null; calibrated: boolean; backbone: string; note?: string;
}
type NodeState = "idle" | "active" | "done";

const PIPELINE = [
  { key: "context", label: "Context", tone: "text-mute", ring: "border-mute" },
  { key: "pricing", label: "Pricing", tone: "text-volt", ring: "border-volt" },
  { key: "inventory", label: "Inventory", tone: "text-mint", ring: "border-mint" },
  { key: "risk", label: "Risk audit", tone: "text-amber", ring: "border-amber" },
  { key: "finalize", label: "Decision", tone: "text-soft", ring: "border-soft" },
] as const;
const KEYS: string[] = PIPELINE.map((p) => p.key);
const freshNodes = (): Record<string, NodeState> => Object.fromEntries(KEYS.map((k) => [k, "idle"]));
const toneOf = (node: string | null) => PIPELINE.find((p) => p.key === node)?.tone ?? "text-mute";

export default function Dashboard() {
  const [products, setProducts] = useState<Product[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [events, setEvents] = useState<MeshEvent[]>([]);
  const [nodes, setNodes] = useState<Record<string, NodeState>>(freshNodes());
  const [runId, setRunId] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [decision, setDecision] = useState<Decision | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [autoApply, setAutoApply] = useState(false);
  const [health, setHealth] = useState<"ok" | "degraded" | "offline">("offline");
  const esRef = useRef<EventSource | null>(null);

  const loadProducts = useCallback(async () => {
    try {
      const res = await fetch(`${V1}/agents/products`, { cache: "no-store" });
      const data: Product[] = await res.json();
      setProducts(data);
      setSelected((cur) => cur ?? data[0]?.id ?? null);
    } catch {
      setError("Cannot reach the API. Start the stack with docker compose up.");
    }
  }, []);

  useEffect(() => {
    loadProducts();
    const poll = async () => {
      try {
        const res = await fetch(`${API}/health`, { cache: "no-store" });
        setHealth((await res.json()).status === "ok" ? "ok" : "degraded");
      } catch { setHealth("offline"); }
    };
    poll();
    const t = setInterval(poll, 15000);
    return () => { clearInterval(t); esRef.current?.close(); };
  }, [loadProducts]);

  const applyEvent = (ev: MeshEvent) => {
    if (ev.type === "node.started" && ev.node) {
      const idx = KEYS.indexOf(ev.node);
      setNodes((prev) => {
        const next = { ...prev };
        KEYS.forEach((k, i) => { if (i > idx) next[k] = "idle"; });
        next[ev.node as string] = "active";
        return next;
      });
    } else if (ev.type === "node.completed" && ev.node) {
      setNodes((prev) => ({ ...prev, [ev.node as string]: "done" }));
    } else if (ev.type === "run.completed") {
      setDecision(ev.data as Decision);
    } else if (ev.type === "run.failed") {
      setError(ev.data?.error ?? "The run failed.");
    }
  };

  const runAgents = async () => {
    if (!selected) return;
    esRef.current?.close();
    setEvents([]); setNodes(freshNodes()); setDecision(null); setError(null); setRunning(true);
    try {
      const res = await fetch(`${V1}/agents/run`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ product_id: selected, auto_apply: autoApply }),
      });
      if (!res.ok) throw new Error(`The API rejected the run (${res.status}).`);
      const { run_id, stream_url } = await res.json();
      setRunId(run_id);
      const es = new EventSource(`${API}${stream_url}`);
      esRef.current = es;
      es.onmessage = (m) => {
        const ev: MeshEvent = JSON.parse(m.data);
        setEvents((prev) => [...prev, ev]);
        applyEvent(ev);
        if (ev.type === "run.completed" || ev.type === "run.failed") {
          es.close(); setRunning(false); loadProducts();
        }
      };
      es.onerror = () => { es.close(); setRunning(false); setError("The live stream dropped. Check the backend and run again."); };
    } catch (e) {
      setRunning(false);
      setError(e instanceof Error ? e.message : "Could not start the run.");
    }
  };

  const applyPrice = async () => {
    if (!runId) return;
    const res = await fetch(`${V1}/agents/runs/${runId}/apply`, { method: "POST" });
    if (res.ok) { setDecision((d) => (d ? { ...d, applied: true } : d)); loadProducts(); }
    else setError((await res.json()).detail ?? "Could not apply the price.");
  };

  const current = products.find((p) => p.id === selected) ?? null;
  const attempts = events.filter((e) => e.type === "node.started" && e.node === "pricing").length;

  return (
    <div className="mx-auto flex min-h-screen max-w-[1400px] flex-col px-4 pb-6 pt-5 sm:px-6">
      <header className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">
            Opti<span className="text-volt">Nexus</span>
          </h1>
          <p className="mt-1 text-sm text-mute">Autonomous commerce intelligence: agents price, restock and audit your catalogue while you watch.</p>
        </div>
        <div className="flex items-center gap-2 rounded-full border border-edge bg-panel px-3 py-1.5 text-sm" role="status">
          <span className={`h-2 w-2 rounded-full ${health === "ok" ? "bg-mint" : health === "degraded" ? "bg-amber" : "bg-coral"}`} />
          <span className="text-mute">{DEMO ? "Browser demo, no backend needed" : health === "ok" ? "All services healthy" : health === "degraded" ? "Some services degraded" : "API offline"}</span>
        </div>
      </header>

      <main className="grid flex-1 gap-4 lg:grid-cols-[270px_minmax(0,1fr)_340px]">
        {/* Catalogue */}
        <section aria-label="Catalogue" className="rounded-2xl border border-edge bg-panel p-3">
          <h2 className="px-2 pb-2 pt-1 text-sm font-medium text-mute">Catalogue</h2>
          <ul className="space-y-1.5">
            {products.map((p) => (
              <li key={p.id}>
                <button onClick={() => setSelected(p.id)} aria-pressed={p.id === selected}
                  className={`w-full rounded-xl border px-3 py-2.5 text-left transition-colors ${p.id === selected ? "border-volt bg-raise" : "border-transparent hover:bg-raise/60"}`}>
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="truncate text-sm font-medium">{p.name}</span>
                    <span className="font-mono text-sm">{inr.format(p.current_price)}</span>
                  </div>
                  <div className="mt-1 flex items-center justify-between font-mono text-xs text-mute">
                    <span>{p.sku}</span>
                    <span>{p.available_units.toLocaleString("en-IN")} in stock</span>
                  </div>
                  {p.last_decision && (
                    <div className={`mt-1.5 text-xs ${p.last_decision.action === "reprice" ? "text-volt" : "text-mute"}`}>
                      Last run: {p.last_decision.action === "reprice" ? `reprice ${p.last_decision.price_change_pct > 0 ? "+" : ""}${p.last_decision.price_change_pct}%` : "hold"}
                    </div>
                  )}
                </button>
              </li>
            ))}
            {products.length === 0 && <li className="px-2 py-6 text-sm text-mute">No products yet. The API seeds a demo catalogue on first start.</li>}
          </ul>
        </section>

        {/* Live execution */}
        <section aria-label="Agent execution" className="min-w-0 space-y-4">
          <div className="rounded-2xl border border-edge bg-panel p-4 sm:p-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="min-w-0">
                <h2 className="truncate text-lg font-medium">{current ? current.name : "Select a product"}</h2>
                {current && (
                  <p className="font-mono text-xs text-mute">
                    cost {inr.format(current.cost)}{current.map_price ? ` · MAP ${inr.format(current.map_price)}` : ""}
                  </p>
                )}
              </div>
              <div className="flex items-center gap-3">
                <label className="flex cursor-pointer items-center gap-2 text-sm text-mute">
                  <input type="checkbox" checked={autoApply} onChange={(e) => setAutoApply(e.target.checked)} className="accent-[#8577FF]" />
                  Apply approved price automatically
                </label>
                <button onClick={runAgents} disabled={!selected || running}
                  className="rounded-xl bg-volt px-4 py-2 text-sm font-semibold text-ink transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50">
                  {running ? "Agents working…" : "Run agent mesh"}
                </button>
              </div>
            </div>

            {/* Pipeline: the run's real sequence */}
            <ol className="mt-6 flex items-start justify-between gap-1 overflow-x-auto pb-1" aria-label="Pipeline progress">
              {PIPELINE.map((n, i) => {
                const st = nodes[n.key];
                return (
                  <li key={n.key} className="flex min-w-[76px] flex-1 flex-col items-center text-center">
                    <div className="flex w-full items-center">
                      <div className={`h-px flex-1 ${i === 0 ? "opacity-0" : st === "idle" ? "bg-edge" : "bg-volt"}`} />
                      <div className={`grid h-9 w-9 place-items-center rounded-full border-2 bg-ink text-xs font-mono ${st === "idle" ? "border-edge text-mute" : n.ring + " " + n.tone} ${st === "active" ? "node-active" : ""}`}>
                        {st === "done" ? "✓" : st === "active" ? "•" : ""}
                      </div>
                      <div className={`h-px flex-1 ${i === PIPELINE.length - 1 ? "opacity-0" : st === "done" ? "bg-volt" : "bg-edge"}`} />
                    </div>
                    <span className={`mt-2 text-xs ${st === "idle" ? "text-mute" : n.tone}`}>{n.label}</span>
                  </li>
                );
              })}
            </ol>
            {attempts > 1 && <p className="mt-3 text-xs text-amber">The risk audit sent pricing back {attempts - 1} time{attempts > 2 ? "s" : ""} with a tighter step size.</p>}
          </div>

          {error && <div role="alert" className="rounded-xl border border-coral/50 bg-coral/10 px-4 py-3 text-sm text-coral">{error}</div>}

          {decision && <DecisionCard d={decision} onApply={applyPrice} />}

          <div className="rounded-2xl border border-edge bg-panel p-4">
            <h3 className="mb-3 text-sm font-medium text-mute">Live trace</h3>
            {events.length === 0 ? (
              <p className="py-6 text-sm text-mute">Nothing running. Pick a product and run the agent mesh to watch each agent reason in real time.</p>
            ) : (
              <ul className="space-y-2 font-mono text-[13px]" aria-live="polite">
                {events.map((ev, i) => (
                  <li key={i} className="rounded-lg bg-ink/60 px-3 py-2">
                    <div className="flex flex-wrap items-baseline gap-x-3">
                      <span className="text-mute">{new Date(ev.ts).toLocaleTimeString("en-GB")}</span>
                      <span className={`font-semibold ${toneOf(ev.node)}`}>{ev.node ?? ev.type.replace("run.", "run ")}</span>
                      <span className="text-mute">{ev.type}</span>
                    </div>
                    {ev.data?.summary && <p className="mt-1 text-soft">{ev.data.summary}</p>}
                    {ev.data?.detail && (
                      <details className="mt-1">
                        <summary className="cursor-pointer text-xs text-mute hover:text-soft">Show raw output</summary>
                        <pre className="mt-1 max-h-56 overflow-auto rounded bg-panel p-2 text-xs text-mute">{JSON.stringify(ev.data.detail, null, 2)}</pre>
                      </details>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </section>

        {/* Tools */}
        <aside className="space-y-4">
          <AskPanel />
          <VisionPanel sku={current?.sku ?? null} />
        </aside>
      </main>

      <section aria-label="Analytics lab" className="mt-4 grid gap-4 lg:grid-cols-3">
        <ForecastPanel sku={current?.sku ?? null} />
        <SimulatorPanel sku={current?.sku ?? null} price={current?.current_price ?? null} />
        <ExperimentPanel sku={current?.sku ?? null} />
      </section>

      <CompliancePanel />
      <PlansAndRoi />

      <footer className="mt-8 flex flex-col items-center justify-between gap-2 border-t border-edge pt-4 text-sm text-mute sm:flex-row">
        <p>Designed and developed by <span className="font-semibold text-soft">{AUTHOR.name}</span></p>
        <nav className="flex gap-4" aria-label="Author links">
          <a className="hover:text-volt" href={AUTHOR.github} target="_blank" rel="noreferrer">GitHub</a>
          <a className="hover:text-volt" href={AUTHOR.linkedin} target="_blank" rel="noreferrer">LinkedIn</a>
          <a className="hover:text-volt" href={`mailto:${AUTHOR.email}`}>Email</a>
        </nav>
      </footer>
    </div>
  );
}

function Stat({ label, value, tone = "text-soft" }: { label: string; value: string; tone?: string }) {
  return (
    <div className="rounded-xl bg-ink/60 px-3 py-2">
      <div className="text-xs text-mute">{label}</div>
      <div className={`mt-0.5 font-mono text-sm ${tone}`}>{value}</div>
    </div>
  );
}

function DecisionCard({ d, onApply }: { d: Decision; onApply: () => void }) {
  const up = d.price_change_pct > 0;
  const canApply = d.approved && d.action === "reprice" && !d.applied;
  return (
    <div className={`rounded-2xl border p-4 sm:p-5 ${d.approved ? "border-mint/40 bg-mint/5" : "border-amber/40 bg-amber/5"}`}>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className={`text-sm font-medium ${d.approved ? "text-mint" : "text-amber"}`}>
            {d.action === "reprice" ? "Reprice approved" : d.approved ? "Hold price" : "Blocked by risk audit"}
          </p>
          <p className="mt-1 font-mono text-3xl tracking-tight">
            {inr.format(d.old_price)} <span className="text-mute">→</span> {inr.format(d.new_price)}
            {d.action === "reprice" && <span className={`ml-3 text-base ${up ? "text-mint" : "text-amber"}`}>{up ? "+" : ""}{d.price_change_pct}%</span>}
          </p>
        </div>
        {canApply && <button onClick={onApply} className="rounded-xl bg-mint px-4 py-2 text-sm font-semibold text-ink hover:opacity-90">Apply this price</button>}
        {d.applied && <span className="rounded-full border border-mint/50 px-3 py-1 text-sm text-mint">Price applied</span>}
      </div>
      <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Stat label="Daily profit" value={`${d.expected_profit_delta_pct > 0 ? "+" : ""}${d.expected_profit_delta_pct}%`} tone={d.expected_profit_delta_pct >= 0 ? "text-mint" : "text-amber"} />
        <Stat label="Units sold" value={`${d.expected_units_change_pct > 0 ? "+" : ""}${d.expected_units_change_pct}%`} />
        <Stat label="Reorder" value={`${d.reorder_qty} units`} />
        <Stat label="Ships from" value={d.fulfilment_warehouse ? `${d.fulfilment_warehouse.warehouse} · ${d.fulfilment_warehouse.distance_km} km` : "No stock"} />
      </div>
      {d.explain && d.explain.length > 0 && (
        <details className="mt-4">
          <summary className="cursor-pointer text-sm text-mute hover:text-soft">Why this price</summary>
          <ol className="mt-2 space-y-1 font-mono text-xs">
            {d.explain.map((x, i) => (
              <li key={i} className="flex justify-between rounded bg-ink/60 px-2.5 py-1.5"><span className="text-mute">{x.label}</span><span>{inr.format(x.price)}</span></li>
            ))}
          </ol>
        </details>
      )}
      {d.reasons.length > 0 && <p className="mt-3 text-sm text-amber">Failed checks: {d.reasons.join(", ")}.</p>}
    </div>
  );
}

function AskPanel() {
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [answer, setAnswer] = useState<{ answer: string; mode: string; sources: RagSource[] } | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const ask = async () => {
    if (q.trim().length < 3) return;
    setBusy(true); setErr(null);
    try {
      const res = await fetch(`${V1}/rag/query`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question: q, k: 5 }) });
      if (!res.ok) throw new Error("The market memory did not respond.");
      setAnswer(await res.json());
    } catch (e) { setErr(e instanceof Error ? e.message : "Something went wrong."); }
    finally { setBusy(false); }
  };

  return (
    <div className="rounded-2xl border border-edge bg-panel p-4">
      <h2 className="text-sm font-medium text-mute">Ask the market</h2>
      <div className="mt-3 flex gap-2">
        <input value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && ask()}
          placeholder="What are rivals doing on tees?" aria-label="Question for market memory"
          className="min-w-0 flex-1 rounded-xl border border-edge bg-ink px-3 py-2 text-sm placeholder:text-mute/70" />
        <button onClick={ask} disabled={busy} className="rounded-xl border border-volt px-3 py-2 text-sm text-volt hover:bg-volt/10 disabled:opacity-50">{busy ? "…" : "Ask"}</button>
      </div>
      {err && <p className="mt-3 text-sm text-coral">{err}</p>}
      {answer && (
        <div className="mt-3 space-y-2">
          <p className="text-sm leading-relaxed">{answer.answer}</p>
          <p className="text-xs text-mute">{answer.mode === "llm" ? "Written by the language model from these sources." : "Top matching passages (add an Anthropic API key for written answers)."}</p>
          <ul className="space-y-1.5">
            {answer.sources.slice(0, 3).map((s, i) => (
              <li key={i} className="rounded-lg bg-ink/60 px-2.5 py-1.5 text-xs text-mute"><span className="font-mono text-soft">[{i + 1}]</span> {s.source} · {s.kind}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function VisionPanel({ sku }: { sku: string | null }) {
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<VisionResult | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const onFile = async (file: File | undefined) => {
    if (!file) return;
    setBusy(true); setErr(null); setRes(null);
    const form = new FormData();
    form.append("file", file);
    if (sku) form.append("sku", sku);
    try {
      const r = await fetch(`${V1}/vision/analyze`, { method: "POST", body: form });
      if (!r.ok) throw new Error((await r.json()).detail ?? "Analysis failed.");
      setRes(await r.json());
    } catch (e) { setErr(e instanceof Error ? e.message : "Analysis failed."); }
    finally { setBusy(false); }
  };

  return (
    <div className="rounded-2xl border border-edge bg-panel p-4">
      <h2 className="text-sm font-medium text-mute">Analyse a product photo</h2>
      <label className="mt-3 flex cursor-pointer flex-col items-center rounded-xl border border-dashed border-edge px-3 py-5 text-center text-sm text-mute hover:border-volt hover:text-soft">
        {busy ? "Running the CNN…" : "Choose an image (JPG, PNG, WebP)"}
        <input type="file" accept="image/*" className="sr-only" onChange={(e) => onFile(e.target.files?.[0])} />
      </label>
      {err && <p className="mt-3 text-sm text-coral">{err}</p>}
      {res && (
        <div className="mt-3 space-y-3 text-sm">
          <div className="grid grid-cols-2 gap-2">
            <Stat label="Photo quality" value={`${Math.round(res.quality.photo_quality * 100)}/100`} />
            <Stat label="Sharpness" value={String(res.quality.sharpness)} />
          </div>
          <div className="flex gap-1.5" aria-label="Dominant colours">
            {res.palette.map((c) => (
              <div key={c.hex} title={`${c.name} ${Math.round(c.share * 100)}%`} className="h-7 rounded-md border border-edge" style={{ background: c.hex, flexGrow: Math.max(c.share, 0.08) }} />
            ))}
          </div>
          {res.calibrated ? (
            <div className="space-y-1.5">
              <p className="text-mute">Style score <span className="font-mono text-soft">{res.aesthetic_score}</span> · Defect risk <span className="font-mono text-soft">{res.defect_risk}</span></p>
              <p className="flex flex-wrap gap-1.5">{res.attributes?.map((a) => <span key={a.tag} className="rounded-full border border-edge px-2 py-0.5 text-xs">{a.tag} {Math.round(a.prob * 100)}%</span>)}</p>
            </div>
          ) : (
            <p className="text-xs text-mute">Attribute, defect and style heads are not fine-tuned yet, so only photo quality and colours are shown. Load a checkpoint to enable them.</p>
          )}
        </div>
      )}
    </div>
  );
}
