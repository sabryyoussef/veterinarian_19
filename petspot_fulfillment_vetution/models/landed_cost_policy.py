# -*- coding: utf-8 -*-
"""Configurable landed-cost + shadow pricing policy (Phase 15A/B gates)."""

from __future__ import annotations

import math

from odoo import api, fields, models
from odoo.exceptions import UserError

COMPONENT_STATES = [
    ("unknown", "Unknown — blocks automation"),
    ("verified_zero", "Verified genuinely zero"),
    ("configured", "Configured verified value"),
]


class PetspotVetutionLandedCostPolicy(models.Model):
    _name = "petspot.vetution.landed.cost.policy"
    _description = "PetSpot Vetution Landed Cost Policy"
    _order = "active desc, id desc"

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    version = fields.Char(required=True, default="15A.2-TEST")
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
    )

    pricing_method = fields.Selection(
        [
            ("gross_margin", "Gross margin"),
            ("markup", "Markup"),
        ],
        default="gross_margin",
        required=True,
    )
    target_gross_margin_percent = fields.Float(
        default=25.0,
        help="Target margin used in: selling = landed / (1 - target/100)",
    )
    markup_percent = fields.Float(default=20.0)
    fixed_markup_amount = fields.Float(default=0.0)
    min_gross_margin_percent = fields.Float(default=20.0)
    min_gross_profit_amount = fields.Float(default=50.0)
    price_rounding = fields.Float(default=5.0)
    rounding_mode = fields.Selection(
        [("nearest", "Nearest"), ("ceil", "Ceil up")],
        default="nearest",
        required=True,
    )

    max_price_increase_percent = fields.Float(default=10.0)
    max_price_decrease_percent = fields.Float(default=10.0)
    min_change_threshold_amount = fields.Float(default=1.0)

    stale_after_hours_shadow = fields.Float(
        default=12.0,
        help="Max commercial data age for shadow assessment freshness.",
    )
    stale_after_hours_auto_quote = fields.Float(
        default=2.0,
        help="Max age for future automatic quotation (not enabled in 15A).",
    )
    quotation_validity_hours = fields.Float(
        default=2.0,
        help="Future quotation validity window (hours). Not creating quotes in 15A.",
    )

    # --- Landed cost components with explicit verification state ---
    supplier_delivery_allocation = fields.Float(default=0.0)
    supplier_delivery_status = fields.Selection(COMPONENT_STATES, default="unknown", required=True)
    supplier_delivery_source = fields.Char(
        help="Evidence note for delivery charge / free-delivery threshold.",
    )

    non_recoverable_tax_rate = fields.Float(default=0.0)
    non_recoverable_tax_status = fields.Selection(COMPONENT_STATES, default="unknown", required=True)
    non_recoverable_tax_source = fields.Char()

    payment_fee_rate = fields.Float(default=0.0)
    payment_fee_fixed = fields.Float(default=0.0)
    payment_fee_status = fields.Selection(COMPONENT_STATES, default="unknown", required=True)
    payment_fee_source = fields.Char()

    packaging_handling = fields.Float(default=0.0)
    packaging_handling_status = fields.Selection(COMPONENT_STATES, default="unknown", required=True)
    packaging_handling_source = fields.Char()

    risk_return_allowance_rate = fields.Float(default=0.0)
    risk_return_allowance_status = fields.Selection(COMPONENT_STATES, default="unknown", required=True)
    risk_return_allowance_source = fields.Char()

    optional_fixed_cost = fields.Float(default=0.0)
    optional_fixed_cost_status = fields.Selection(
        COMPONENT_STATES, default="verified_zero", required=True
    )
    optional_fixed_cost_source = fields.Char(default="Explicitly unused optional bucket.")

    # Freshness / refresh
    allow_on_demand_refresh = fields.Boolean(default=True)
    refresh_lock_seconds = fields.Integer(default=120)
    refresh_max_retries = fields.Integer(default=3)
    circuit_breaker_failures = fields.Integer(default=5)
    circuit_breaker_cooldown_minutes = fields.Integer(default=30)
    supplier_lead_time_days = fields.Integer(default=3)

    allow_price_publish = fields.Boolean(default=False)
    allow_auto_quotation = fields.Boolean(default=False)
    allow_customer_message = fields.Boolean(default=False)
    allow_supplier_po = fields.Boolean(default=False)

    availability_wording = fields.Char(
        default="Available from supplier, subject to final confirmation",
        required=True,
    )
    pending_decisions = fields.Text(compute="_compute_pending_decisions")

    @api.depends(
        "supplier_delivery_status",
        "non_recoverable_tax_status",
        "payment_fee_status",
        "packaging_handling_status",
        "risk_return_allowance_status",
    )
    def _compute_pending_decisions(self):
        for rec in self:
            lines = []
            for label, status in [
                ("Vetution delivery / free-delivery threshold", rec.supplier_delivery_status),
                ("Non-recoverable VAT/tax", rec.non_recoverable_tax_status),
                ("Payment fee (Shopify/Paymob)", rec.payment_fee_status),
                ("Packaging/handling", rec.packaging_handling_status),
                ("Return/risk allowance", rec.risk_return_allowance_status),
            ]:
                if status == "unknown":
                    lines.append(f"- UNKNOWN: {label}")
            rec.pending_decisions = "\n".join(lines) or "- All landed-cost components verified."

    @api.model
    def get_active_policy(self, company=None):
        company = company or self.env.company
        policy = self.search(
            [("active", "=", True), ("company_id", "=", company.id)],
            limit=1,
            order="id desc",
        )
        if not policy:
            raise UserError("No active PetSpot Vetution landed-cost policy found.")
        return policy

    def _component_amount(self, status, amount):
        """Unknown → incomplete (amount ignored for completeness). Verified zero/configured → use amount."""
        if status == "unknown":
            return 0.0, True
        return float(amount or 0.0), False

    def compute_landed_cost(self, supplier_cost):
        self.ensure_one()
        cost = float(supplier_cost or 0.0)
        incomplete = False
        missing = []

        delivery, inc = self._component_amount(
            self.supplier_delivery_status, self.supplier_delivery_allocation
        )
        if inc:
            incomplete = True
            missing.append("supplier_delivery")

        tax_base, inc = self._component_amount(
            self.non_recoverable_tax_status, self.non_recoverable_tax_rate
        )
        tax = cost * (tax_base / 100.0) if self.non_recoverable_tax_status != "unknown" else 0.0
        if inc:
            incomplete = True
            missing.append("non_recoverable_tax")

        fee_rate, inc_r = self._component_amount(self.payment_fee_status, self.payment_fee_rate)
        fee_fixed, inc_f = self._component_amount(self.payment_fee_status, self.payment_fee_fixed)
        # payment fee uses same status for rate+fixed
        if self.payment_fee_status == "unknown":
            payment = 0.0
            incomplete = True
            missing.append("payment_fee")
        else:
            payment = cost * (fee_rate / 100.0) + fee_fixed

        packaging, inc = self._component_amount(
            self.packaging_handling_status, self.packaging_handling
        )
        if inc:
            incomplete = True
            missing.append("packaging_handling")

        risk_rate, inc = self._component_amount(
            self.risk_return_allowance_status, self.risk_return_allowance_rate
        )
        risk = cost * (risk_rate / 100.0) if self.risk_return_allowance_status != "unknown" else 0.0
        if inc:
            incomplete = True
            missing.append("risk_return_allowance")

        optional, inc = self._component_amount(
            self.optional_fixed_cost_status, self.optional_fixed_cost
        )
        if inc:
            incomplete = True
            missing.append("optional_fixed_cost")

        if cost <= 0:
            incomplete = True
            missing.append("supplier_cost")

        landed = cost + delivery + payment + packaging + tax + risk + optional
        return {
            "supplier_cost": cost,
            "supplier_delivery_allocation": delivery,
            "payment_fee": payment,
            "packaging_handling": packaging,
            "non_recoverable_tax": tax,
            "risk_return_allowance": risk,
            "optional_fixed_cost": optional,
            "landed_cost": landed,
            "landed_cost_incomplete": incomplete,
            "missing_components": missing,
            "formula": (
                "landed_cost = supplier_cost + delivery + payment_fee + "
                "packaging + nonrecoverable_tax + risk_allowance (+ optional_fixed)"
            ),
        }

    def _round_price(self, value):
        rounding = float(self.price_rounding or 1.0)
        if rounding <= 0:
            return value
        if self.rounding_mode == "ceil":
            return math.ceil(value / rounding - 1e-9) * rounding
        # nearest
        return round(value / rounding) * rounding

    def compute_suggested_sale_price(self, landed_cost):
        """Gross-margin method (default):
        selling_price = max(landed / (1 - target), landed + min_profit) then round.
        Markup method retained for compatibility.
        """
        self.ensure_one()
        cost = float(landed_cost or 0.0)
        result = {
            "landed_cost": cost,
            "target_margin_price": 0.0,
            "minimum_profit_price": 0.0,
            "markup_price": 0.0,
            "candidate": 0.0,
            "suggested_price": 0.0,
            "pricing_method": self.pricing_method,
            "target_gross_margin_percent": self.target_gross_margin_percent or 0.0,
            "min_margin_percent": self.min_gross_margin_percent or 0.0,
            "min_profit_amount": self.min_gross_profit_amount or 0.0,
            "rounding": self.price_rounding or 1.0,
            "rounding_mode": self.rounding_mode,
            "sell_formula": "",
        }
        if cost <= 0:
            return result

        min_profit = result["min_profit_amount"] or 0.0
        profit_price = cost + min_profit

        if self.pricing_method == "gross_margin":
            target = result["target_gross_margin_percent"] or 0.0
            if target >= 100:
                margin_price = cost
            else:
                margin_price = cost / (1.0 - target / 100.0)
            candidate = max(margin_price, profit_price)
            result["sell_formula"] = (
                f"selling_price = max(landed_cost / (1 - {target/100:.2f}), "
                f"landed_cost + {min_profit:g}) then round {self.rounding_mode} {result['rounding']:g}"
            )
            result["target_margin_price"] = margin_price
            result["minimum_profit_price"] = profit_price
        else:
            markup = self.markup_percent or 0.0
            markup_price = cost * (1.0 + markup / 100.0) + (self.fixed_markup_amount or 0.0)
            min_margin = result["min_margin_percent"]
            if min_margin >= 100:
                margin_price = cost
            else:
                margin_price = cost / (1.0 - min_margin / 100.0)
            candidate = max(markup_price, margin_price, profit_price)
            result["markup_price"] = markup_price
            result["target_margin_price"] = margin_price
            result["minimum_profit_price"] = profit_price
            result["sell_formula"] = "max(markup, min_margin, min_profit) then round"

        suggested = self._round_price(candidate)
        result.update({"candidate": candidate, "suggested_price": suggested})
        return result

    def evaluate_price_guards(
        self,
        *,
        suggested_price,
        landed_cost,
        current_odoo_price,
        price_locked=False,
        landed_cost_incomplete=False,
        data_age_hours=0.0,
        for_auto_quote=False,
    ):
        self.ensure_one()
        blockers = []
        gates = {
            "block_auto_quotation": False,
            "block_odoo_price_update": False,
            "block_shopify_publish": False,
            "block_supplier_purchase": False,
            "price_review_required": False,
            "eligible_future_automation": False,
        }
        suggested = float(suggested_price or 0.0)
        landed = float(landed_cost or 0.0)
        current = float(current_odoo_price or 0.0)

        if self.allow_price_publish:
            blockers.append("allow_price_publish_must_be_false_until_approved")
        if landed_cost_incomplete:
            blockers.append("landed_cost_incomplete")
            gates["block_auto_quotation"] = True
            gates["block_odoo_price_update"] = True
            gates["block_shopify_publish"] = True
            gates["block_supplier_purchase"] = True
        if landed <= 0:
            blockers.append("cost_zero_or_missing")
        if suggested <= 0:
            blockers.append("suggested_price_zero")
        if price_locked:
            blockers.append("promotion_or_manual_price_locked")
            gates["block_shopify_publish"] = True
            gates["block_odoo_price_update"] = True

        profit = suggested - landed if suggested and landed else 0.0
        margin = (profit / suggested * 100.0) if suggested > 0 else 0.0
        if profit < 0:
            blockers.append("negative_margin")
        if suggested > 0 and margin + 1e-9 < (self.min_gross_margin_percent or 0.0):
            blockers.append("below_min_gross_margin")
        if landed > 0 and profit + 1e-9 < (self.min_gross_profit_amount or 0.0):
            blockers.append("below_min_profit")

        delta = suggested - current
        delta_pct = (abs(delta) / current * 100.0) if current > 0 else 0.0
        unchanged = abs(delta) < (self.min_change_threshold_amount or 0.0)
        if current > 1.01 and delta > 0 and delta_pct > (self.max_price_increase_percent or 0.0):
            blockers.append("excessive_price_increase")
            gates["price_review_required"] = True
        if current > 1.01 and delta < 0 and delta_pct > (self.max_price_decrease_percent or 0.0):
            blockers.append("excessive_price_decrease")
            gates["price_review_required"] = True

        shadow_limit = self.stale_after_hours_shadow or 12.0
        auto_limit = self.stale_after_hours_auto_quote or 2.0
        if data_age_hours > shadow_limit:
            blockers.append("stale_data_shadow")
        if data_age_hours > auto_limit:
            gates["block_auto_quotation"] = True
            if for_auto_quote:
                blockers.append("stale_data_auto_quote")

        # Always keep Phase 15A commercial writes blocked
        gates["block_auto_quotation"] = True if not self.allow_auto_quotation else gates["block_auto_quotation"]
        gates["block_odoo_price_update"] = True
        gates["block_shopify_publish"] = True
        gates["block_supplier_purchase"] = True if not self.allow_supplier_po else gates["block_supplier_purchase"]

        ok = not blockers
        within_band = not gates["price_review_required"]
        gates["eligible_future_automation"] = bool(
            ok
            and within_band
            and not landed_cost_incomplete
            and data_age_hours <= auto_limit
            and not price_locked
        )

        return ok, blockers, {
            "expected_gross_profit": profit,
            "expected_gross_margin_percent": margin,
            "price_delta_amount": delta,
            "price_delta_percent": delta_pct if current > 0 else 0.0,
            "price_unchanged": unchanged,
            "gates": gates,
        }
