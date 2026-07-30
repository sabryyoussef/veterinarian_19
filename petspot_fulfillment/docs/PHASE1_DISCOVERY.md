# PetSpot Fulfillment — Phase 1 Discovery (as-built)

Date: 2026-07-30  
Evidence: `/home/sabry/.cursor/evidence/petspot-fulfillment-20260730-125718`  
Repo: `pet_spot_elsahel` (`veterinarian_19`) branch `feature/petspot-fulfillment-orchestration`

## Existing workflow (before this module)

### Shopify ↔ Odoo
- Module: `custom_odoo_shopify_connector` (symlink → worldposta-dev/shopify_19)
- Sale orders keyed by immutable `shopify_order_id` (+ instance)
- Webhook queue with event-id uniqueness; import creates/updates one SO
- Financial / fulfillment status preserved on SO fields
- **No** purchase RFQ creation from Shopify demand
- **No** Draft Order API in connector (gap for Path B optional link)

### Purchase / Sales
- Standard Odoo `sale` + `purchase`
- `vetution_supplier` = catalog/pricing offers, not order-linked RFQ orchestration

### ShipBlu
- `delivery_shipblu` 19.0.1.4.0 + Duplicate AWB Guard
- Odoo is intended AWB owner; Shopify ShipBlu auto-create must stay OFF
- Canonical shipment: `shipblu.shipment` linked to picking / sale_order

### WhatsApp / Chatwoot
- `petspot_wa_intake` / WhatsApp hub = clinic intake, **not** stock availability
- Storefront “Request availability” → WhatsApp only (theme/metafield — **do not touch**)
- No automatic inquiry capture from free-text; manual Odoo form is intentional

### Idempotency identities (chosen)

| Entity | Key |
|--------|-----|
| Shopify order | `shopify:<store_id>:<order_id>` |
| Fulfillment case | `idempotency_key` + SQL unique; also `(shopify_store_id, shopify_order_id)` |
| Odoo SO | native `sale.order.id` + optional `shopify_order_id` |
| RFQ/PO | origin marker `petspot-ff:<case_id>:vendor:<vendor_id>` + case M2M |
| Availability inquiry | `inquiry:msg:<message_id>` or `inquiry:conv:<id>:var:<variant>` |
| Stock picking | native picking id / SO pickings |
| ShipBlu | existing Duplicate AWB Guard / `shipblu.shipment` |

## New module
`petspot_fulfillment` 19.0.1.0.0 — orchestration only; **no** catalog/theme/`availability_mode` changes.
