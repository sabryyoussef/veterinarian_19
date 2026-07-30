# Phase 14 Preflight — Chatwoot availability intake

Date: 2026-07-30  
Evidence: `/home/sabry/.cursor/evidence/petspot-ff-wa-intake-20260730-153123`

## Architecture (confirmed)

```text
Shopify CTA (wa.me/201000059085)
  → WhatsApp / Evolution instance
  → Chatwoot inbox (canonical)
  → authenticated webhook
  → Odoo petspot_fulfillment @ test.drpaws.ai
```

**Decision:** Chatwoot is the sole intake source. No parallel Evolution→Odoo path.

## Existing facilities

| Component | Finding |
|-----------|---------|
| CTA marker | `Request availability — pet.spot` (stable EN marker in live snippet) |
| WA number | `+201000059085` |
| Chatwoot | account_id=`2`, inbox_id=`2` (platform.env) |
| TEST Odoo | `https://test.drpaws.ai` → `:8028` / `pet_spot_elsahel_test` |
| Auth patterns | Bridge uses `X-Bridge-Token`; Phase 14 uses dedicated webhook secret header |
| Product map | `shopify.variant.map` (`shopify_variant_id` → `product.product`) |
| Clinic intake | `petspot_wa_intake` is separate (pets/visits) — not reused for stock |

## Sanitized CTA sample (English)

```text
Request availability — pet.spot

Product: Adult dinner dog
Variant / pack size: 12.5 Kg
SKU: SHP-1377-3140
URL: https://shopify.drpaws.ai/products/adult-dinner-dog
Requested quantity: 5
```

Arabic messages still start with the same English marker line from the theme snippet.

## Safety (unchanged)

- Intake creates inquiry (+ orchestration case) only
- Never quotation / RFQ / payment / ShipBlu from webhook
- Production automation stays OFF; this phase deploys to TEST only
