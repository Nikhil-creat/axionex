"use client";

import { useState } from "react";
import { V1 } from "@/lib/config";

/* eslint-disable @typescript-eslint/no-explicit-any */
const ICON: Record<string, string> = { pass: "✅", warn: "⚠️", fail: "❌", info: "ℹ️", unknown: "❔" };
const TONE: Record<string, string> = {
  pass: "border-mint/40 bg-mint/5 text-mint", warn: "border-amber/40 bg-amber/5 text-amber",
  fail: "border-coral/40 bg-coral/5 text-coral", info: "border-volt/40 bg-volt/5 text-volt",
  unknown: "border-edge bg-ink/40 text-mute",
};

export function CompliancePanel() {
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [report, setReport] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);

  const run = async () => {
    if (!url.trim()) return;
    setBusy(true); setErr(null); setReport(null);
    try {
      const r = await fetch(`${V1}/compliance/scan`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ url: url.trim() }) });
      if (!r.ok) throw new Error((await r.json()).detail ?? "Scan failed");
      setReport(await r.json());
    } catch (e) { setErr(e instanceof Error ? e.message : "Scan failed"); } finally { setBusy(false); }
  };

  return (
    <section aria-label="Trust and compliance auditor" className="mt-4 rounded-2xl border border-edge bg-panel p-4 sm:p-5">
      <h2 className="text-lg font-medium">Trust &amp; compliance auditor</h2>
      <p className="mt-1 text-sm text-mute">Scans a live storefront URL for legal pages, consent, tracking disclosure, accessibility, review/claim integrity, business identity and DPDP Act 2023 readiness.</p>
      <div className="mt-3 flex flex-wrap gap-2">
        <input value={url} onChange={(e) => setUrl(e.target.value)} onKeyDown={(e) => e.key === "Enter" && run()}
          placeholder="https://yourbrand.com" aria-label="Storefront URL to audit"
          className="min-w-0 flex-1 rounded-xl border border-edge bg-ink px-3 py-2 text-sm placeholder:text-mute/70" />
        <button onClick={run} disabled={busy} className="rounded-xl bg-volt px-4 py-2 text-sm font-semibold text-ink hover:opacity-90 disabled:opacity-50">
          {busy ? "Scanning…" : "Run audit"}
        </button>
      </div>
      {err && <p className="mt-3 text-sm text-coral" role="alert">{err}</p>}

      {report && (
        <div className="mt-4">
          <div className="flex flex-wrap items-center gap-4">
            <div className="rounded-xl border border-edge bg-ink/60 px-4 py-2">
              <div className="text-xs text-mute">Overall score</div>
              <div className="font-mono text-2xl">{report.score}<span className="text-sm text-mute">/100</span></div>
            </div>
            <div className="rounded-xl border border-edge bg-ink/60 px-4 py-2">
              <div className="text-xs text-mute">DPDP Act readiness</div>
              <div className="font-mono text-2xl">{report.dpdp_score}<span className="text-sm text-mute">/100</span></div>
            </div>
            <div className="flex flex-wrap gap-2 text-xs">
              {Object.entries(report.counts).filter(([, n]) => (n as number) > 0).map(([k, n]) => (
                <span key={k} className={`rounded-full border px-2.5 py-1 ${TONE[k]}`}>{ICON[k]} {n as number} {k}</span>
              ))}
            </div>
          </div>

          <ul className="mt-4 grid gap-2 sm:grid-cols-2">
            {report.checks.map((c: any) => (
              <li key={c.key} className={`rounded-xl border p-3 ${TONE[c.status] ?? TONE.unknown}`}>
                <div className="flex items-start gap-2">
                  <span aria-hidden>{ICON[c.status] ?? "❔"}</span>
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-soft">{c.label}</p>
                    <p className="mt-0.5 text-xs text-mute">{c.detail}</p>
                    {c.evidence?.length > 0 && (
                      <details className="mt-1">
                        <summary className="cursor-pointer text-xs text-mute hover:text-soft">Evidence</summary>
                        <ul className="mt-1 space-y-0.5 text-xs text-mute">{c.evidence.map((e: string, i: number) => <li key={i} className="truncate">{e}</li>)}</ul>
                      </details>
                    )}
                  </div>
                </div>
              </li>
            ))}
          </ul>
          <p className="mt-3 text-center text-xs text-mute">*{report.disclaimer}</p>
        </div>
      )}
    </section>
  );
}
