# AxioNex: startup notes

**Name:** AxioNex — "autonomous commerce intelligence, verified." The new trust/compliance auditor gives it a second wedge: not just pricing, but proving a storefront is legally and technically sound.

## Who pays
D2C and marketplace brands in India first (apparel, footwear, beauty, home) that reprice by hand or with spreadsheets. The pain is real: thin margins, festive-season volatility, rivals repricing daily, stock-outs and overstock.

## What is sold
Decisions with guardrails, not a dashboard. Each run returns a price, a reorder quantity and a warehouse, plus a risk verdict and a "why this price" trail, so a founder or category manager can trust it.

## Revenue model (suggested, test with real customers)
| Stream | Price point | Notes |
|---|---|---|
| SaaS tiers | Starter $0, Growth $99/mo, Scale $499/mo | Already enforced in code: per-key rate limits and monthly run quotas (`/billing/plans`, `/billing/usage`). |
| Performance fee | 5 to 15% of verified profit uplift | Needs a controlled A/B baseline; the price lab and simulator are the measurement layer. |
| Onboarding | One-off setup for catalogue and competitor feeds | Good early cash while the product matures. |

Illustration only: 40 customers on Growth is about $3,960 a month. That figure is arithmetic, not a forecast.

## Honest gaps before charging money
1. **Multi-tenancy and auth:** API keys map to plans, but tenants share one catalogue. Add tenant IDs on every table and OIDC login.
2. **Real data connectors:** Shopify, WooCommerce, Amazon/Flipkart seller APIs and a compliant competitor-price source. Respect each site's terms.
3. **Validated models:** the CNN heads need fine-tuning on customer imagery; the elasticity model needs enough price variation in real data.
4. **Payments:** Stripe or Razorpay subscriptions tied to the `plan` on each API key.
5. **Compliance:** terms of service, privacy policy, and data-processing terms.

## 90-day plan
- **Days 1 to 30:** publish the browser demo, record a 2-minute walkthrough, and get 5 D2C founders to try it on their real SKUs.
- **Days 31 to 60:** build a Shopify read-only connector, run shadow-mode pricing (recommend, don't apply), and measure the gap.
- **Days 61 to 90:** convert 2 to 3 pilots to paid, then add the performance fee for the ones with measured uplift.

Designed and developed by NIKHIL CHARY SRIRAMOJU.
