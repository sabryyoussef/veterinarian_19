# My Work / Managed Activities — Technical Notes

Module: `petspot_fulfillment_vetution` **19.0.1.5.0**

## Architecture

```text
Availability Inquiry  →  Shadow Assessment  →  Ops orchestrator  →  mail.activity
                                                      ↓
                                                 My Work queue
```

* Orchestrator: `petspot.vetution.ops.activity` (`models/ops_activity.py`)
* Managed flag: `mail.activity.petspot_managed` + `petspot_action_code`
* Ownership: `res.company.petspot_ops_owner_*` (Settings → PetSpot Ops Owners)
* Hook: `_upsert_assessment` and inquiry assess actions call `_petspot_ops_sync()`

## Action code mapping (repo codes → ops codes)

| Repo signal | Ops action code |
|---|---|
| `mapping_review_required` / assessment `review` + mapping | `MAPPING_REQUIRED` |
| `stale` / `sync_failed` / `stale_data*` | `SUPPLIER_DATA_STALE` |
| `out_of_stock` / `unavailable` | `OOS_REVIEW` |
| `landed_cost_incomplete` / `INSUFFICIENT_*` | `INCOMPLETE_COST_PROFILE` |
| `negative_margin` / `below_min_*` | `NEGATIVE_MARGIN` |
| `price_review_required` / `excessive_price_*` | `PRICE_REVIEW_REQUIRED` |
| `DELIVERY_PRICE_REVIEW_REQUIRED` | `DELIVERY_PRICE_REVIEW_REQUIRED` |
| Eligible OK, no quote | `QUOTATION_READY` |
| Ledger `sent` / `expired` | `WAITING_CUSTOMER_ACCEPTANCE` / `QUOTATION_EXPIRED` |
| Accepted, unpaid | `PAYMENT_PENDING` |
| Trust rejected | `PAYMENT_REJECTED` |
| Case `exception` | `SUPPLIER_PRICE_CHANGED` |
| Paid, no PO | `READY_FOR_RFQ` |
| Awaiting receipt | `WAITING_GIZA_RECEIPT` |
| Package size unverified | `PACKAGE_SIZE_REQUIRED` |
| Delivery ready | `READY_FOR_SHIPMENT` |
| Store pickup ready | `READY_FOR_PICKUP_HANDOVER` |
| Missing owner config | `OPS_OWNER_CONFIG_REQUIRED` |

## Production Shadow

`Mark Done and Reassess` only runs `assess_inquiry` + activity sync.  
It never flips ICP transports or sends live messages / RFQs / AWBs / Shopify publishes.

## Repair cron

`cron_ops_activity_repair` — **inactive by default**. Syncs missing managed activities; dedupes; no commercial side effects.
