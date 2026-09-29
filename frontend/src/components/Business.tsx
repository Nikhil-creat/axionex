"use client";

import { useState } from "react";
import { inr } from "@/lib/config";

const PLANS = [
  { id: "starter", name: "Starter", price: "$0", blurb: "For trying it on a few products", feats: ["3 SKUs", "50 agent runs a month", "Forecasts and simulator"] },
  { id: "growth", name: "Growth", price: "$99/mo", blurb: "For D2C brands with a live catalogue", feats: ["100 SKUs", "2,000 agent runs a month", "Webhook automation and price lab"], hot: true },
  { id: "scale", name: "Scale", price: "$499/mo", blurb: "For multi-brand and marketplace sellers", feats: ["2,000 SKUs", "50,000 runs a month", "Custom guardrails, priority support"] },
];

export function PlansAndRoi() {
  const [skus, setSkus] = useState(100);
  const [profit, setProfit] = useState(40000);
  const [uplift, setUplift] = useState(3);
  const gain = skus * profit * (uplift / 100);
  return (
    <section aria-label="Plans and ROI" className="mt-4 rounded-2xl border border-edge bg-panel p-4 sm:p-5">
      <div className="grid gap-6 lg:grid-cols-[1.4fr_1fr]">
        <div>
          <h2 className="text-lg font-medium">Plans</h2>
          <p className="mt-1 text-sm text-mute">Priced on the catalogue you manage, with an optional share of verified profit uplift on Scale.</p>
          <ul className="mt-4 grid gap-3 sm:grid-cols-3">
            {PLANS.map((p) => (
              <li key={p.id} className={`rounded-xl border p-3 ${p.hot ? "border-volt bg-raise" : "border-edge"}`}>
                <div className="flex items-baseline justify-between"><span className="font-medium">{p.name}</span><span className="font-mono text-sm text-volt">{p.price}</span></div>
                <p className="mt-1 text-xs text-mute">{p.blurb}</p>
                <ul className="mt-2 space-y-1 text-xs">{p.feats.map((f) => <li key={f}>{f}</li>)}</ul>
              </li>
            ))}
          </ul>
        </div>
        <div>
          <h2 className="text-lg font-medium">What could it be worth?</h2>
          <div className="mt-3 space-y-3 text-sm">
            {[["Products managed", skus, setSkus, 10, 2000, 10], ["Monthly profit per product (₹)", profit, setProfit, 5000, 200000, 5000], ["Profit uplift from agents (%)", uplift, setUplift, 0.5, 10, 0.5]].map(([label, val, set, min, max, step]: any) => (
              <label key={label} className="block">
                <span className="flex justify-between text-mute"><span>{label}</span><span className="font-mono text-soft">{val}</span></span>
                <input type="range" min={min} max={max} step={step} value={val} onChange={(e) => set(Number(e.target.value))} className="mt-1 w-full accent-[#8577FF]" />
              </label>
            ))}
          </div>
          <p className="mt-4 font-mono text-2xl text-mint">{inr.format(gain)}<span className="text-sm text-mute"> extra profit a month</span></p>
          <p className="mt-1 text-xs text-mute">Illustrative only. Measure real uplift with the what-if simulator and a controlled price test before promising results to a customer.</p>
        </div>
      </div>
    </section>
  );
}
