# Phase 14 — Chatwoot Availability Intake Report

**Verdict: `TEST_READY_AWAITING_PRODUCTION_APPROVAL`**

## Architecture

```text
Shopify CTA (Request availability — pet.spot)
  → WhatsApp / Evolution (+201000059085)
  → Chatwoot account 2 / inbox 2  (canonical)
  → POST /petspot/fulfillment/chatwoot/webhook  (X-PetSpot-Webhook-Secret)
  → petspot.availability.inquiry + petspot.fulfillment.case
  → optional bilingual Chatwoot acknowledgement (once)
```

No Evolution→Odoo parallel path.

## Data mapping

| Source | Odoo field |
|--------|------------|
| CTA marker | recognition gate |
| SKU / Variant ID | product resolve (variant map → exact SKU) |
| URL / qty | `product_url`, `requested_qty` |
| sender phone | normalized EG `phone` + partner |
| account/inbox/conversation/message/contact | stored on inquiry + webhook event |
| idempotency | `cw:{account}:{conversation}:{message}` |

## Safety confirmed

- Intake creates inquiry + case only
- No quotation / SO / RFQ / payment / ShipBlu from webhook
- Product title never used alone for resolution
- Production remains on `petspot_fulfillment` 19.0.1.0.0 without Chatwoot ICP; automation OFF; ShipBlu create OFF / `odoo_owned`

## Module / commits

- Module version: **19.0.1.1.0**
- Branch: `feature/petspot-fulfillment-orchestration`
- Commit: `0240143740d5b410c4415a79351bc03b209a737a`

## Automated tests

`0 failed, 0 error(s) of 11 tests` (tag `petspot_ff_chatwoot`) — log `tests_phase14_3.log`

## TEST UAT

| Check | Result |
|-------|--------|
| Health | intake_enabled true |
| Valid CTA webhook | INQ/2026/00029 + case FF/2026/00102, phone +201005551234, SKU SHP-445-985 |
| Replay | same inquiry_id, `replay: true` |
| Unauthorized | HTTP 401 |
| has_so | false |
| ack_sent | true (test mode local ack) |

Endpoint: `https://test.drpaws.ai/petspot/fulfillment/chatwoot/webhook`

## Rollback

1. Set `petspot_fulfillment.chatwoot_intake_enabled=False` on TEST
2. Remove Chatwoot webhook subscription pointing at TEST
3. Optionally `-u` rollback / uninstall 19.0.1.1.0 features by reverting commit

## Production

**Not deployed.** Awaiting separate approval.
commit=0240143740d5b410c4415a79351bc03b209a737a
