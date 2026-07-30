# Phase 15A.4 — Vetution Fulfillment Bridge (Shadow, Giza origin)

Module: `petspot_fulfillment_vetution` 19.0.1.3.0

Read-only assessments on Availability Inquiries. No quotes, PO, messages, or price publishes.

## Operating model (ecommerce)

```
Vetution supplier → PetSpot Giza fulfillment → customer via ShipBlu
or customer pickup from the approved Giza location (Haram clinic)
```

North Coast remains the public clinic/Shopify entity address — **not** the ecommerce ShipBlu origin.

## Product price worksheet (gross margin)

When the customer is charged for delivery (order-level EGP 118):

```
product_landed =
  supplier_cost
  + supplier_shipping (Vetution → Giza; unknown until verified)
  + payment_gateway_fee
  + packaging + tax + return_risk + handling
  + delivery_shortfall

delivery_profit_or_subsidy =
  customer_delivery_charge - ShipBlu_cost - COD_fee

delivery_shortfall = max(0, -delivery_profit_or_subsidy)
```

Full ShipBlu cost is **not** added to product price when delivery is charged separately.

```
selling_price = max(product_landed / (1 - 0.25), product_landed + 50)
```

then round nearest EGP 5. Final margin must remain >= 20%.

### Store pickup (Giza)

- ShipBlu = NOT_APPLICABLE  
- COD = NOT_APPLICABLE  
- delivery revenue = 0 unless an approved pickup fee exists  

### TEST provisional ShipBlu baseline

`Giza → Giza` / package `small` / **EGP 95** = `APPROVED_PROVISIONAL_ESTIMATE`  
(not a final invoice or universal tariff). Package-size IDs 1–4 remain unverified.

Unknown landed-cost components set `landed_cost_incomplete` and block auto-quote / price publish / supplier purchase.
