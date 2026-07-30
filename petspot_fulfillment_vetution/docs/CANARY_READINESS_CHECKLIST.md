# Limited Auto-Quote Canary — Readiness Checklist

Current verdict: **PRODUCTION_READY_SHADOW_MODE**

Do **not** flip canary flags until every item below is checked.

## Hard blockers (must clear)
- [ ] Production commercial cost policy has **no unknown** packaging / handling / tax / return-risk / payment-fee rows
- [ ] Real Paymob fee schedule verified (not synthetic 3%+3)
- [ ] Paymob HMAC secret configured and callback verified on a disposable TEST payment only
- [ ] ShipBlu official package-size IDs verified (`shipblu_package_size_verified=True` only after API proof)
- [ ] At least one SKU on automation allowlist with **exact** `vetution_size_id` (never SHP-139-144 until size proven)
- [ ] Commercial data freshness ≤2h for auto-quote path; shadow freshness ≤12h monitored
- [ ] Delivery gate: `max_auto_delivery_subsidy=0` still enforced; North Coast / lossy routes stay `DELIVERY_PRICE_REVIEW_REQUIRED`

## Soft / process
- [ ] Operator trained on mapping-review UI + exception queue
- [ ] Chatwoot templates reviewed (still mock transport until explicitly approved)
- [ ] Rollback drill from latest `pg_dump` completed once
- [ ] Canary scope written: allowlisted SKU list, max daily auto-quotes, kill switch owner

## Flags to flip for canary (only after hard blockers)
| Flag | Shadow now | Canary target |
|---|---|---|
| `auto_quote_enabled` | False | True (allowlisted SKUs only via policy+allowlist) |
| `chatwoot_transport` | mock | mock or approved disposable contact only |
| `shopify_publish_transport` | mock | mock (keep OFF) |
| `shipblu_create_transport` | mock | mock (keep OFF until package-size verified) |
| `rfq_send_enabled` | False | False (draft PO only) |
| ShipBlu `shipment_creation_enabled` | False | False |

## Explicitly never for canary
- Copying `TEST-SYNTHETIC-E2E-NOT-FOR-COMMERCE` amounts into Production policy
- Allowlisting Production DB in `synthetic_policy_allowed_dbs`
- Live ShipBlu AWB create / pickup automation
- Treating WhatsApp screenshots as payment evidence

## Exit criteria for `LIMITED_AUTO_QUOTE_CANARY_READY`
1. Hard blockers cleared with evidence under `~/.cursor/evidence/`
2. One allowlisted SKU auto-quotes correctly on TEST with real (non-synthetic) cost profile
3. Production shadow assessments show `eligible_future_automation=True` for that SKU without incomplete costs
4. Kill switch (`auto_quote_enabled=False`) verified within 60 seconds
