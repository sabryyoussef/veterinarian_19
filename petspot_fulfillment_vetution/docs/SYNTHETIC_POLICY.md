# Synthetic TEST Policy — `TEST-SYNTHETIC-E2E-NOT-FOR-COMMERCE`

**Module:** `petspot_fulfillment_vetution` (Phase 15B)
**Status:** TEST fixture only. **NEVER FOR PRODUCTION / COMMERCE.**

## What it is

A single `petspot.vetution.landed.cost.policy` record (external id
`petspot_fulfillment_vetution.landed_cost_policy_synthetic_test`,
`name = "TEST-SYNTHETIC-E2E-NOT-FOR-COMMERCE"`) that exists **only** to
exercise the full synthetic commercial workflow end-to-end on a TEST
database:

```
shadow assessment → auto-quote → customer message (mock) → payment trust →
draft RFQ → synthetic Giza receipt → store pickup / mock ShipBlu AWB
```

Every amount on this record is an artificial fixture value. None of them
represent an approved commercial figure and none may ever be copied onto a
non-synthetic Production policy.

## Why it is safe by construction

Three independent layers keep this policy from ever touching real customers
or real money, even if someone activates it by mistake:

1. **`is_synthetic_test = True` + database allowlist.**
   `landed_cost_policy.get_active_policy()` explicitly **excludes** any
   policy with `is_synthetic_test = True` and only ever returns it as a last
   resort, and only when the current database name is present in the
   comma-separated ICP
   `petspot_fulfillment_vetution.synthetic_policy_allowed_dbs` (default:
   `pet_spot_elsahel_test` — the TEST database only).
   `get_synthetic_test_policy()` performs the same allowlist check again
   before returning the record. There is no code path that returns this
   policy for a normal (non-explicit) shadow assessment on Production.

2. **Per-action transactional gates in `services/workflow_engine.py`.**
   Every `WorkflowEngine` method that would create a commercial side effect
   (`run_auto_quote_if_eligible`, `run_send_message`, `run_draft_rfq`,
   `run_synthetic_giza_receipt`, `run_mock_shipblu_awb`, …) calls
   `_require_flag()`, which re-checks:
   - if the active policy is **not** synthetic: the corresponding
     `allow_*` flag on that (non-synthetic) policy must be `True` — and
     those flags default to `False` and are asserted to stay `False` for
     any Production seed (see `shadow_assessment.assess_inquiry`, which
     raises `UserError` if a non-synthetic policy ever has
     `allow_auto_quotation`/`allow_customer_message` set);
   - if the active policy **is** synthetic: `policy._synthetic_test_allowed_here()`
     must be `True` (same database allowlist as above) — otherwise it raises.

3. **Hard-coded "never live" transports**, independent of any policy flag:
   - `ChatwootTransport.send_template()` always writes `transport="mock"`
     and raises `UserError` rather than sending if the ICP
     `chatwoot_transport` is ever set to `live` (no HTTP client is even
     imported in this module).
   - `WorkflowEngine.run_mock_shipblu_awb()` raises `UserError` immediately
     if ICP `shipblu_create_transport` is `live` — live AWB creation is **not
     implemented** in this module, by design, regardless of any flag.
   - `PricePublishQueue.publish_mock()` raises `UserError` if ICP
     `shopify_publish_transport` is `live` — live Shopify price publishing
     is **not implemented** in this module.
   - `allow_price_publish` is hard-enforced to `False` for **every** policy
     (synthetic or not) inside `shadow_assessment.assess_inquiry()`; there is
     no way to publish a price to Shopify from this module today.

## Seeded values (all synthetic, all in `data/synthetic_test_policy_data.xml`)

| Field | Value | Note |
|---|---|---|
| `is_synthetic_test` | `True` | never returned by `get_active_policy()` off-allowlist |
| `policy_environment` | `test_only` | |
| `version` | `TEST-SYNTHETIC-E2E` | |
| `supplier_shipping_mode` | `included` | supplier price already includes shipping |
| `default_packaging_type` | `small_box` | EGP 10 for shipped orders |
| packaging (pickup) | `envelope` EGP 5 | used when `packaging_type=envelope` in context |
| `tax_mode` | `exempt` | EGP 0 tax |
| `handling_amount` | EGP 10 | `handling_status=configured` |
| `risk_return_allowance_rate` | 3.0% | `risk_mode=percent` |
| Paymob fee | 3% + EGP 3 | `configured`, synthetic |
| Bank transfer / COD fee | EGP 0 | `verified_zero` |
| `customer_delivery_charge_amount` | EGP 118 | order-level revenue, never product COGS |
| `max_auto_delivery_subsidy` | EGP 0 | break-even gate — see below |
| `allow_auto_quotation` | `True` | **only** on this record, still ICP/allowlist-gated |
| `allow_customer_message` | `True` | **only** on this record, transport is always mock |
| `allow_supplier_po` | `True` | draft PO only — never sent |
| `allow_price_publish` | `False` | **always** — see safety layer #3 above |
| origin / destination | Giza / Giza | `default_package_size_code=small` |
| Delivery revenue rule | EGP 118, any carrier/payment | seeded, `noupdate="0"` |

## Delivery price-review gate (Phase 15B)

`services/landed_cost_engine.py` computes, after the carrier estimate:

```
delivery_subsidy        = max(0, carrier_cost + delivery_fees - customer_delivery_charge)
proposed_delivery_charge = carrier_cost + delivery_fees + max_auto_delivery_subsidy
delivery_gate_passed     = delivery_subsidy <= max_auto_delivery_subsidy
```

With `max_auto_delivery_subsidy = 0` (the synthetic default and the
Production-safe default for every new policy):

- **Giza → Giza** (small package, ~EGP 95 carrier cost) vs EGP 118 charge:
  subsidy = 0 → **gate passes**.
- **Giza → North Coast** (~EGP 196 carrier cost) vs EGP 118 charge: subsidy =
  EGP 78 → **gate fails**, `delivery_decision_code` is forced to
  `DELIVERY_PRICE_REVIEW_REQUIRED`, and `quotation_ledger.create_auto_quotation()`
  refuses to auto-quote (`assessment.delivery_gate_passed` is checked
  explicitly). The subsidy is **never** folded into `product_landed_cost`.

## How to exercise it safely

1. Confirm you are on the TEST database (`pet_spot_elsahel_test`) — check
   with `SELECT current_database();` or `self.env.cr.dbname` in a shell.
2. Confirm the ICP allowlist includes this database:
   `petspot_fulfillment_vetution.synthetic_policy_allowed_dbs` should contain
   `pet_spot_elsahel_test` (seeded by default in
   `data/ir_config_parameter_workflow.xml`).
3. Use `WorkflowEngine(env)` methods, or the automated test suite
   (`tests/test_workflow_e2e.py`, `tests/test_synthetic_e2e.py`), to run the
   pipeline. Every step remains mock/local-only; nothing calls Chatwoot,
   Shopify, Paymob, or ShipBlu over the network.
4. **Never** flip `petspot_fulfillment_vetution.auto_quote_enabled`,
   `chatwoot_transport`, `shopify_publish_transport`, or
   `shipblu_create_transport` to a live/enabled value on a database that is
   not an explicitly-approved TEST environment.

## What must never happen

- Copying any field value from `landed_cost_policy_synthetic_test` onto a
  non-synthetic (Production) policy record.
- Adding `pet_spot_elsahel` (Production) — or any other Production database
  name — to `synthetic_policy_allowed_dbs`.
- Setting `allow_price_publish = True` on any policy, synthetic or not.
- Implementing a "live" branch inside `ChatwootTransport`,
  `run_mock_shipblu_awb`, or `PricePublishQueue.publish_mock` without a
  separate, explicitly-reviewed change (this module intentionally leaves
  those branches unimplemented today).
