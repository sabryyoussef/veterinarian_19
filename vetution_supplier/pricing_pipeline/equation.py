# Pure pricing equation helpers (no I/O).
# landed_cost must be a valid Vetution effective_cost (> 1.01).

from __future__ import annotations

import math
from typing import Optional

PLACEHOLDER_MAX = 1.01
MARKUP_PCT = 20.0
MIN_MARGIN_PCT = 15.0
MIN_PROFIT = 50.0
ROUNDING = 5.0


def ceil_to_next_multiple_of_5(value: float) -> float:
    """Round upward to the next multiple of LE5. Never round down."""
    if value <= 0:
        return 0.0
    return float(math.ceil(value / ROUNDING - 1e-9) * ROUNDING)


def is_valid_landed_cost(value: float) -> bool:
    """LE1 and below are never valid Vetution landed costs."""
    try:
        return float(value) > PLACEHOLDER_MAX
    except (TypeError, ValueError):
        return False


def compute_sale_candidates(landed_cost: float) -> dict:
    cost = float(landed_cost)
    return {
        "markup_price": cost * (1.0 + MARKUP_PCT / 100.0),
        "margin_floor": cost / (1.0 - MIN_MARGIN_PCT / 100.0),
        "profit_floor": cost + MIN_PROFIT,
    }


def compute_final_sale_price(
    landed_cost: float,
    existing_activated_sale: Optional[float] = None,
) -> dict:
    """Odoo-side equation. Shopify must receive this exact result after Odoo reread.

    existing_activated_sale is ignored when <= PLACEHOLDER_MAX (LE1 placeholder).
    Never reduces a higher valid activated floor.
    """
    if not is_valid_landed_cost(landed_cost):
        return {
            "ok": False,
            "reason": "invalid_landed_cost_le1_or_below",
            "final_price": None,
        }
    c = compute_sale_candidates(landed_cost)
    floor = float(existing_activated_sale or 0.0)
    if floor <= PLACEHOLDER_MAX:
        floor = 0.0
    raw = max(c["markup_price"], c["margin_floor"], c["profit_floor"], floor)
    final = ceil_to_next_multiple_of_5(raw)
    profit = final - float(landed_cost)
    margin = profit / final if final else 0.0
    return {
        "ok": True,
        "reason": "ok",
        "landed_cost": float(landed_cost),
        "markup_price": round(c["markup_price"], 4),
        "margin_floor": round(c["margin_floor"], 4),
        "profit_floor": round(c["profit_floor"], 4),
        "existing_floor": floor or None,
        "calculated_raw": round(raw, 4),
        "final_price": final,
        "gross_profit": round(profit, 4),
        "gross_margin": round(margin, 6),
        "margin_ok": margin + 1e-12 >= 0.15,
        "profit_ok": profit + 1e-9 >= MIN_PROFIT or final >= ceil_to_next_multiple_of_5(
            float(landed_cost) + MIN_PROFIT
        ),
        "below_cost": final < float(landed_cost),
    }


def shopify_price_from_odoo_reread(odoo_sale_price: float) -> Optional[str]:
    """Shopify sync must not recalculate — only format the Odoo reread price."""
    if not is_valid_landed_cost(odoo_sale_price) and float(odoo_sale_price or 0) <= PLACEHOLDER_MAX:
        # Selling price itself must also not be LE1 placeholder
        return None
    if float(odoo_sale_price or 0) <= PLACEHOLDER_MAX:
        return None
    return f"{float(odoo_sale_price):.2f}"
