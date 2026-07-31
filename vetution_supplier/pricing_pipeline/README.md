# Pricing pipeline (Vetution → Odoo → Shopify)

Odoo is the **single source of truth**. Shopify receives the exact reread Odoo
sale price — the equation is never recalculated in the Shopify sync step.

## Package

| Path | Role |
|------|------|
| `pricing_pipeline/equation.py` | Pure equation + LE1 rejection + Shopify format helper |
| `pricing_pipeline/config.example.yaml` | Non-secret config template |
| `tests/test_pricing_pipeline_equation.py` | Unit tests |

Operational runners and evidence dumps live outside this module:

`/home/sabry/vetution-import/pricing-pipeline/`

(`artifacts/` must not be committed — secrets, rollbacks, customer-adjacent dumps).

## Equation

```
markup_price   = landed_cost × 1.20
margin_floor   = landed_cost ÷ 0.85
profit_floor   = landed_cost + 50
existing_floor = activated Odoo sale > 1.01 (LE1 ignored)
final_price    = ceil_to_5(max(...))
```

`landed_cost` must be `vetution.supplier.offer.effective_cost` **> 1.01**.

## Modes

Use the operational runner with `--dry-run` or `--apply`. Control-set freeze for
the approved 2,839 variants is enforced by the repair runner.
