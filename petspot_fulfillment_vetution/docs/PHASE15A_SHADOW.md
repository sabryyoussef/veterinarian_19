# Phase 15A / 15A.4 — Vetution Shadow Assessment

## Operating model (ecommerce)

```
Vetution supplier → PetSpot Giza fulfillment (451 Haram St)
  → customer via ShipBlu
  OR customer pickup from approved Giza location
```

Do **not** treat the North Coast clinic / Shopify store address as the ecommerce ShipBlu origin.

## Separated economics

### Product selling price

```
product_landed =
  supplier_cost
  + supplier_shipping (Vetution → Giza)
  + payment_gateway_fee (non-COD)
  + packaging
  + tax
  + return_risk
  + handling

recommended_product_price =
  round_nearest_5( max(product_landed / 0.75, product_landed + 50) )
```

Outbound ShipBlu cost and the customer delivery charge are **not** in product landed cost.

### Delivery economics (order-level)

```
customer_delivery_charge = rule/policy (default 118 EGP) | 0 pickup | promo override
estimated_carrier_cost   = ShipBlu CostEngine (Giza→dest / package)
delivery_specific_fees   = COD commission (when COD)
delivery_margin          = charge - carrier - fees
delivery_subsidy         = max(0, carrier + fees - charge)
order_total              = recommended_product_price + customer_delivery_charge
```

Giza→Giza / package `small` / EGP **95** is labeled
`APPROVED_PROVISIONAL_ESTIMATE` (not invoice / not universal tariff).

### Completeness

- `product_cost_completeness` — product keys only
- `delivery_cost_completeness` — ShipBlu + COD
- `overall_completeness` — mean of both

Missing carrier cost does **not** erase a product-price worksheet; delivery margin stays incomplete.

## Locks (must remain OFF)

auto quote · price publish · PO · customer message · Shopify writes · ShipBlu create
