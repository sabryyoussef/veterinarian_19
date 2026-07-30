# Phase 15B — Master Execution Runbook

`petspot_fulfillment_vetution` synthetic commercial workflow orchestration.

**Scope:** how to safely install/upgrade this module, run the synthetic
end-to-end (E2E) workflow on the TEST database, read the resulting audit
trail, and what to check before ever considering flipping a flag toward
Production.

See also: [`SYNTHETIC_POLICY.md`](SYNTHETIC_POLICY.md) for the full safety
model of the `TEST-SYNTHETIC-E2E-NOT-FOR-COMMERCE` policy, and
[`PHASE15A_SHADOW.md`](PHASE15A_SHADOW.md) for the shadow landed-cost engine.

## 1. Pipeline overview

```
run_shadow_path(inquiry)
  → petspot.vetution.shadow.assessment  (read-only: no SO/RFQ/messages/payments)

run_auto_quote_if_eligible(inquiry)
  → petspot.vetution.quotation.ledger   (gated: synthetic OR allow_auto_quotation+ICP,
                                          freshness ≤2h, allowlist, delivery gate, exact mapping)

run_send_message(inquiry, key, context)
  → petspot.vetution.message.log        (mock Chatwoot transport only, idempotent)

run_payment_trust(case, source, ...)
  → petspot.vetution.payment.trust      (shopify_paid / paymob_callback / cash_pickup / cod_policy)

run_draft_rfq(case)
  → purchase.order (draft only)         (requires paid/manual_paid + accepted ledger;
                                          re-checks supplier price → exception on drift)

run_synthetic_giza_receipt(case)
  → stock.picking (validated)           (synthetic TEST policy only; existing WH location)

run_store_pickup_complete(case)  /  run_mock_shipblu_awb(case)
  → case handover  /  shipblu.shipment  (mock AWB only; ICP-gated; exactly one per case)
```

Every step is implemented in `services/workflow_engine.py` (`WorkflowEngine`
class) and is safe to call repeatedly — each is idempotent or explicitly
duplicate-guarded (see §4).

## 2. Preconditions before running anything

1. **Confirm the database.** Run in an Odoo shell or via `self.env.cr.dbname`:
   ```python
   env.cr.dbname  # must be "pet_spot_elsahel_test" for the synthetic policy to be reachable
   ```
2. **Confirm the ICP defaults** (seeded by `data/ir_config_parameter_workflow.xml`,
   `noupdate="1"` — a human must change these deliberately):

   | ICP key | Default | Meaning |
   |---|---|---|
   | `auto_quote_enabled` | `False` | non-synthetic auto-quote master switch |
   | `chatwoot_transport` | `mock` | `live` is unimplemented — always raises |
   | `shopify_publish_transport` | `mock` | `live` is unimplemented — always raises |
   | `shipblu_create_transport` | `mock` | `live` is unimplemented — always raises |
   | `shipblu_package_size_verified` | `False` | extra guard, still irrelevant while live is unimplemented |
   | `synthetic_policy_allowed_dbs` | `pet_spot_elsahel_test` | comma list — TEST databases only |
   | `rfq_send_enabled` | `False` | reserved; RFQs are always created as draft only today |
   | `paymob_hmac_secret` | *(empty)* | when empty, only `synthetic_mock_signed` payloads verify |

3. **Confirm the synthetic policy is active** and, if you need it reachable
   from `get_active_policy()` as a last resort, that no other non-synthetic
   policy is active for the company (normally you should instead call
   `Policy.get_synthetic_test_policy(company)` explicitly rather than
   relying on `get_active_policy()` fallback).

## 3. Running the synthetic E2E workflow

Preferred: run the automated suite, which sets up its own fixtures and never
requires manual state:

```bash
# from the Odoo server host, TEST database only, service stopped or via a
# dedicated one-off process (never against a live Production DB):
odoo-bin -c pet_spot_elsahel_test.conf -d pet_spot_elsahel_test \
  -u petspot_fulfillment_vetution \
  --test-enable --test-tags /petspot_fulfillment_vetution \
  --stop-after-init --no-http
```

Manually, from an Odoo shell (`odoo-bin shell -c ... -d pet_spot_elsahel_test`):

```python
from odoo.addons.petspot_fulfillment_vetution.services.workflow_engine import WorkflowEngine

engine = WorkflowEngine(env)
inquiry = env["petspot.availability.inquiry"].create({...})  # see tests for required fields

assessment = engine.run_shadow_path(inquiry)
assert assessment.state == "ok" and assessment.eligible_future_automation

ledger = engine.run_auto_quote_if_eligible(inquiry)
msg = engine.run_send_message(inquiry, "quotation_ready", {"product_price": ledger.product_price})
ledger.action_accept()

case = ledger.case_id
engine.run_payment_trust(case, "cash_pickup", user=env.user)

# Store pickup path:
engine.run_store_pickup_complete(case)

# OR ShipBlu delivery path (requires case.delivery_method == "shipblu_delivery"):
engine.run_mock_shipblu_awb(case)

# Supplier-sourced path (requires case.line_ids with source=supplier_b2b):
engine.run_draft_rfq(case)
po = case.purchase_order_ids.filtered(lambda p: p.state == "draft")
po.button_confirm()
engine.run_synthetic_giza_receipt(case)
```

Every call above is safe to re-run; see §4 for what happens on a repeat call.

## 4. Idempotency / duplicate-guard reference

| Action | Guard mechanism | Repeat-call result |
|---|---|---|
| `run_auto_quote_if_eligible` | `idempotency_key = autoquote:{inquiry}:{assessment}:{version}` + open-quote lookup | same ledger row returned, no duplicate |
| `run_send_message` | `idempotency_key = inquiry_id:template_key:sha256(payload)[:32]` on `message.log` | same log row returned, no second send |
| `run_payment_trust` (any source) | unique `(source, reference)` accepted lookup in `payment.trust` | new row created with `state=duplicate` |
| `run_draft_rfq` | `case.purchase_order_ids` filtered to `draft/sent` per vendor, plus an `origin` marker search | existing draft PO reused, no duplicate PO |
| `run_synthetic_giza_receipt` | operates on pickings not already `done/cancel` | re-run after completion finds no pending pickings → raises (nothing to do) |
| `run_mock_shipblu_awb` | one `shipblu.shipment` per `sale_order_id` | raises `UserError` ("Duplicate Guard") on second call |
| `price.publish.queue.enqueue` | same product + price within a 1h rolling window | existing pending/approved row reused |

## 5. Exception matrix (see `tests/test_workflow_e2e.py`, `tests/test_auto_quote_ledger.py`)

| Exception | Where it is enforced | Test |
|---|---|---|
| Duplicate CTA / message send | `message.log` idempotency key | `test_duplicate_cta_message_is_idempotent`, `test_message_transport.py` |
| Stale commercial data (>2h for auto-quote, >12h shadow) | `assessment.data_age_hours` check in `create_auto_quotation`; `stale_after_hours_*` in `evaluate_price_guards` | `test_stale_data_blocks`, `test_stale_offer_blocks_eligibility` |
| Missing / ambiguous mapping | `resolution_confidence` must be `exact/configured/barcode` | `test_missing_mapping_blocks_shadow`, `test_ambiguous_mapping_blocks` |
| Out of stock | `_price_vals` → `state=unavailable`, `eligible_future_automation=False` | `test_out_of_stock_blocks_eligibility` |
| Incomplete real cost | `landed_cost_incomplete` blocks auto-quote and price update | `test_incomplete_real_cost_blocks_eligibility`, `test_incomplete_landed_cost_blocks` |
| Price change 9% (within band) vs 11% (review required) | `policy.evaluate_price_guards` (`max_price_increase_percent`/`decrease` default 10%) | `test_price_change_9_percent_within_band`, `test_price_change_11_percent_requires_review` |
| Post-accept price change | `create_auto_quotation` checks any `accepted_price_lock=True` row before re-quoting | `test_accept_locks_price_and_blocks_further_supersede` |
| Negative margin | `evaluate_price_guards` → `negative_margin` blocker | `test_negative_margin_blocked` |
| North Coast delivery subsidy | delivery price-review gate (`max_auto_delivery_subsidy`) | `test_north_coast_subsidy_blocks_via_engine`, `test_delivery_gate.py` |
| Duplicate quotation / payment / RFQ / AWB | see §4 | multiple, per-model test files |
| Supplier price moved after quote accepted, before RFQ | `run_draft_rfq` re-checks `vetution.supplier.offer.effective_cost` vs the quoted `assessment.supplier_cost` (>1% delta) → case moved to `exception` | `test_draft_rfq_blocks_on_post_quote_supplier_price_change` |

## 6. Data-health monitoring

`petspot.vetution.data.health.take_snapshot()` captures, read-only:
commercial sync age, shadow-stale count, circuit-breaker state, allowlist
count, pending mapping-review count, and consecutive refresh failures. The
scheduled cron (`cron_vetution_data_health_snapshot`) is shipped **disabled**
(`active=False`); enable it manually per environment once you have decided
on a snapshot cadence. Trigger a one-off snapshot any time via
`action_take_snapshot_now()` on the model, or from the *Vetution Data
Health* menu.

## 7. Before ever touching Production

Do **not** perform any of the following without a separate, explicitly
reviewed and approved change:

- Adding a Production database name to `synthetic_policy_allowed_dbs`.
- Setting `auto_quote_enabled`, `chatwoot_transport`, `shopify_publish_transport`,
  or `shipblu_create_transport` to a live/enabled value anywhere outside an
  approved TEST database.
- Copying any `TEST-SYNTHETIC-E2E-NOT-FOR-COMMERCE` field value onto a
  non-synthetic policy.
- Setting `allow_price_publish=True` on any policy (there is currently no
  live Shopify publish path implemented in this module at all).
- Implementing the `live` branches inside `ChatwootTransport.send_template`,
  `WorkflowEngine.run_mock_shipblu_awb`, or
  `PricePublishQueue.publish_mock` — these are intentionally left as
  hard `UserError`s pending a dedicated, reviewed rollout.
