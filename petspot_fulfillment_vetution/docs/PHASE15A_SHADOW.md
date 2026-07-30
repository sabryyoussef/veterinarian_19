# Phase 15A — Vetution Fulfillment Bridge (Shadow)

Module: `petspot_fulfillment_vetution` 19.0.1.1.0

Read-only assessments on Availability Inquiries. No quotes, PO, messages, or price publishes.

## Provisional TEST sell formula (gross margin)

```
landed_cost = supplier_cost + delivery + payment_fee + packaging + nonrecoverable_tax + risk_allowance
selling_price = max(landed_cost / (1 - 0.25), landed_cost + 50)
```
then round nearest EGP 5. Final margin must remain >= 20%.

Unknown landed-cost components set `landed_cost_incomplete` and block auto-quote / price publish / supplier purchase.
