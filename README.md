# AxioNex

**Autonomous commerce intelligence for D2C brands** — agentic pricing, inventory coordination and risk
auditing, backed by real-time RAG, a CNN vision pipeline, Redis Streams eventing and PostGIS spatial routing.

> Designed and developed by **NIKHIL CHARY SRIRAMOJU**
> [GitHub](https://github.com/Nikhil-creat) · [LinkedIn](https://in.linkedin.com/in/nikhil-chary-sriramoju-95041b38a) · [sriramojunikhil66@gmail.com](mailto:sriramojunikhil66@gmail.com)

## Architecture

```
 Next.js 14 dashboard ──SSE──┐
                             ▼
 Webhooks (HMAC) ─► FastAPI ─► Redis Streams ─► Worker (consumer group)
                      │                              │
                      ▼                              ▼
        LangGraph supervisor ◄──────── triggers autonomous runs
   context → pricing → inventory → risk audit ─┐
        ▲                       (reject: tighten step, retry ≤3)
        │                                       ▼
   Qdrant RAG memory                        finalize → decision
   PostGIS warehouses / Postgres            
   PyTorch CNN (ResNet-50 / EfficientNet)
```

| Concern | Implementation |
|---|---|
| Agent orchestration | LangGraph `StateGraph` with a conditional retry edge from the Risk Auditor back to Pricing |
| Pricing | Log-log elasticity fit with Bayesian shrinkage, Lerner-rule optimum, competitor anchoring, trend + stock-cover adjustments, hard margin/MAP/step constraints, x9 price endings |
| Inventory | Safety stock and reorder point (service level 95%), PO sizing, `ST_Distance` nearest-warehouse routing on PostGIS geography |
| Risk auditor | Seven independent checks: margin, MAP, step size, volume drop, profit regression, competitor ceiling, PO budget |
| RAG | Chunking (LangChain splitter), sentence-transformers embeddings (hash fallback offline), Qdrant, recency-weighted rerank, optional Claude synthesis |
| Trust & compliance auditor | Real URL scan: legal pages, cookie consent, tracking/embeds disclosure, WCAG contrast+alt-text+label checks, review/claim integrity, business-ID disclosure, India DPDP Act 2023 readiness score |
| Vision | ResNet-50 / EfficientNet-B0 backbone, multi-task heads (attributes, defects, aesthetic), sharpness/exposure signals, palette, 2048-d embedding search |
| Forecasting | Holt-Winters (weekly seasonality, damped trend), 80% bands, rolling backtest, MAD anomaly detection |
| What-if simulator | Monte Carlo over elasticity uncertainty: chance of uplift, 90% range, worst-5% loss |
| Price lab | Thompson-sampling bandit over five price points, state in Redis |
| Explainability | Every decision carries a step-by-step "why this price" trail |
| Reliability | Retry with backoff, circuit breaker around the LLM, idempotent runs (`Idempotency-Key`), fail-open rate limiting, `/health`, `/ready`, `/metrics` (Prometheus) |
| Commercial layer | API keys mapped to plans, per-minute rate limits, monthly run quotas, `/billing/plans` and `/billing/usage` |
| Browser demo | Whole dashboard runs in-browser for GitHub Pages (`NEXT_PUBLIC_DEMO_MODE=true`) |
| Eventing | Redis Streams: per-run trace streams (SSE to the UI) and a webhook queue with consumer group + dead-letter stream |
| Data | Async SQLAlchemy 2, Alembic, PostGIS |

## Publish it

See [docs/GITHUB_PAGES_GUIDE.md](docs/GITHUB_PAGES_GUIDE.md) to push to GitHub and get a live Pages URL, and [docs/BUSINESS_PLAN.md](docs/BUSINESS_PLAN.md) for pricing and go-to-market notes.

## Run it

```bash
cp .env.example .env          # optional; set WEBHOOK_SECRET and ANTHROPIC_API_KEY
docker compose up --build
```

- Dashboard: http://localhost:3000
- API docs: http://localhost:8000/docs
- Health: http://localhost:8000/health

The first start seeds five apparel SKUs, five Indian warehouses, 60 days of demand history, competitor prices and
market-intel documents. The first request that touches embeddings downloads the model (`BAAI/bge-small-en-v1.5`);
set `EMBEDDING_BACKEND=hash` to skip the download.

## Try the autonomous loop

```bash
docker compose exec backend python scripts/send_webhook.py OMX-TEE-001 NorthLoop 999
```

The signed webhook lands on a Redis Stream, the worker records the competitor price, indexes it into RAG and, because
it moved more than 5% against your price, launches an agent run. Open the dashboard to see the resulting decision.

## Key endpoints (`/api/v1`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/insights/forecast/{sku}` | Demand forecast with bands and anomalies |
| POST | `/insights/simulate` | Monte Carlo what-if for a candidate price |
| GET/POST | `/insights/experiments/{sku}[/simulate\|/reset]` | Price lab (bandit) |
| GET | `/billing/plans`, `/billing/usage` | Plans and metered usage |
| GET | `/agents/products` | Catalogue with stock and last decision |
| POST | `/agents/run` | Start a run (`202`, returns SSE stream URL) |
| GET | `/agents/runs/{id}/stream` | Live execution trace (SSE) |
| POST | `/agents/runs/{id}/apply` | Apply an approved price |
| POST | `/rag/ingest`, `/rag/query` | Index and query market intelligence |
| POST | `/vision/analyze`, `/vision/similar` | CNN analysis and visual similarity |
| POST | `/compliance/scan` | Audit a storefront URL against the trust/legal/accessibility checklist |
| GET | `/compliance/checklist` | The static list of everything it checks |
| POST | `/webhooks/{source}` | HMAC-signed events (`X-Timestamp`, `X-Signature: sha256=…`) |

Signature: `HMAC_SHA256(secret, f"{timestamp}.{raw_body}")`, 5-minute replay window.

## Things to know before production

- **CNN heads are untrained.** The backbone is pretrained; the attribute, defect and style heads need fine-tuning on
  your labelled catalogue. Until `CNN_HEAD_CHECKPOINT` points at a checkpoint, the API returns only photo-quality
  signals, palette and embeddings, and marks `calibrated: false`.
- **Demo data is synthetic.** The demand history and competitor prices are generated for the demo.
- **Redis** runs single-node in Compose. Set `REDIS_CLUSTER=true` and a cluster URL to use Redis Cluster.
- **Auth is API-key only and tenants share one catalogue.** Add OIDC login and tenant IDs before selling it. Set keys with `API_KEYS='{"sk_live_xxx":"growth"}'`.
- **Migrations:** `0001` creates PostGIS and the schema; use `alembic revision --autogenerate` for later changes.
- Set a strong `WEBHOOK_SECRET`. This code has not been load-tested or run in this packaging environment, so
  treat the first `docker compose up` as your integration test.

## Layout

```
axionex/
├── backend/   FastAPI app, agents, services, Alembic, Dockerfile
├── frontend/  Next.js 14 dashboard (src/app/dashboard/page.tsx)
└── docker-compose.yml
```

MIT licensed. © 2026 NIKHIL CHARY SRIRAMOJU
