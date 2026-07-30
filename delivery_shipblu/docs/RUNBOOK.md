# ShipBlu ↔ Odoo (Pet Spot)

## Status
**TEST** (`test.drpaws.ai` / :8028): modules **19.0.1.3.0**, Duplicate AWB Guard active, Odoo Owned + creation ON.  
**Production**: creation **OFF** — do not enable both Shopify and Odoo create.

## Duplicate AWB Guard
Canonical key: `shipblu:<store>:so:<shopify|odoo_so>:pick:<picking_id>`  
Sent as `merchant_order_reference`. Pre-create checks local + Shopify markers + remote filter; reconciles instead of creating. Ambiguous timeout → `verification_required` (no blind retry).

Verdict: **SAFE_ONLY_WITH_SINGLE_CREATION_OWNER** (ShipBlu has no verified server-side idempotency shared with Shopify).

Evidence: `~/.cursor/evidence/shipblu-dup-guard-20260730/`

## Modules
- `petspot_shipblu_base` — API key, client, filtered delivery lookup
- `delivery_shipblu` — Inventory → ShipBlu Shipping + Duplicate Guard

## Secrets
`~/.cursor/secrets/shipblu-petspot.env` (mode 600)
