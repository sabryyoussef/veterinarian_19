# ShipBlu ↔ Odoo (Pet Spot)

## Status
Installed on **TEST** (`test.drpaws.ai` / :8028). Creation **OFF** by default.

Official API: https://docs.shipblu.com/  
Shopify app settings: https://admin.shopify.com/store/ucbah1-5e/apps/shipblu-2/Settings

## Modules
- `petspot_shipblu_base` — API key, client, logs
- `delivery_shipblu` — carrier, Inventory → ShipBlu Shipping, picking actions

## Secrets
`~/.cursor/secrets/shipblu-petspot.env` (mode 600): `SHIPBLU_API_KEY`, portal user/pass for Shopify app only.

**Rotate the portal password** — it was pasted in chat.

## Safety
- Owner mode: `track_only` on TEST (import + sync only)
- `shipment_creation_enabled=False`
- Before enabling Odoo create: set owner to `odoo_owned`, set **Default Package Size ID**, disable Shopify app auto-create to avoid dual AWBs

## Verified live (API key)
- Merchant: pet spot (#9040)
- Default **drop-off** zone on TEST: **83** (Haram / الهرم) — for Giza deliveries (e.g. 451 Haram St, Nasr Eldin)
- Merchant pickup point still: id **10066**, zone **204** (Sahel / North Coast) unless pickup is changed in ShipBlu