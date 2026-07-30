# -*- coding: utf-8 -*-
"""Configurable customer-facing delivery revenue (not carrier cost).

EGP 118 is the default PetSpot customer delivery charge — order-level revenue,
separate from product catalog price and from estimated ShipBlu carrier cost.
"""

from odoo import api, fields, models


RULE_STATUS = [
    ("unknown", "Unknown"),
    ("configured", "Configured provisional"),
    ("verified", "Verified"),
]


class PetspotVetutionDeliveryRevenueRule(models.Model):
    _name = "petspot.vetution.delivery.revenue.rule"
    _description = "PetSpot Customer Delivery Revenue Rule"
    _order = "sequence, id"

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)
    policy_id = fields.Many2one(
        "petspot.vetution.landed.cost.policy",
        required=True,
        ondelete="cascade",
        index=True,
    )
    company_id = fields.Many2one(
        related="policy_id.company_id", store=True, readonly=True
    )

    carrier = fields.Selection(
        [
            ("shipblu", "ShipBlu"),
            ("bosta", "Bosta"),
            ("standard", "Standard / any"),
            ("any", "Any carrier"),
        ],
        default="any",
        required=True,
    )
    destination_governorate = fields.Char(
        help="Empty = all destinations (default rule).",
    )
    payment_method = fields.Selection(
        [
            ("any", "Any"),
            ("cod", "COD"),
            ("prepaid", "Prepaid (non-COD)"),
            ("paymob", "Paymob"),
            ("card", "Card"),
            ("wallet", "Wallet"),
            ("bank_transfer", "Bank Transfer"),
        ],
        default="any",
        required=True,
    )
    min_order_value = fields.Float(default=0.0)
    max_order_value = fields.Float(
        default=0.0,
        help="0 = no upper bound.",
    )
    customer_charge = fields.Float(
        required=True,
        help="Customer-facing delivery revenue (EGP). Not ShipBlu carrier cost.",
    )
    effective_from = fields.Date(required=True, default=fields.Date.context_today)
    effective_to = fields.Date()
    source = fields.Char(
        default="Odoo delivery.carrier fixed_price (ShipBlu/Bosta/Standard list_price)",
    )
    status = fields.Selection(RULE_STATUS, default="configured", required=True)
    note = fields.Text()

    @api.model
    def resolve_charge(self, policy, context=None):
        """Return (amount, status, source, rule|False) for shadow/order economics.

        Context keys:
          customer_delivery_charge — explicit override (incl. 0 for free shipping)
          destination_governorate, payment_method, order_value, carrier
          shipping_promotion — free | discounted | standard
        """
        ctx = dict(context or {})
        if "customer_delivery_charge" in ctx and ctx.get("customer_delivery_charge") is not None:
            amt = float(ctx["customer_delivery_charge"])
            return (
                amt,
                "configured",
                "context.customer_delivery_charge override",
                self.browse(),
            )

        promo = (ctx.get("shipping_promotion") or "").lower()
        if promo in ("free", "free_shipping"):
            return 0.0, "configured", "shipping_promotion=free", self.browse()

        today = fields.Date.context_today(self)
        dest = (ctx.get("destination_governorate") or "").strip()
        pay = ctx.get("payment_method") or "any"
        order_value = float(ctx.get("order_value") or ctx.get("estimated_collect_amount") or 0.0)
        carrier = ctx.get("carrier") or "shipblu"

        domain = [
            ("policy_id", "=", policy.id),
            ("active", "=", True),
            ("effective_from", "<=", today),
            "|",
            ("effective_to", "=", False),
            ("effective_to", ">=", today),
        ]
        rules = self.search(domain, order="sequence, id")

        def _pay_ok(rule):
            rp = rule.payment_method or "any"
            if rp == "any":
                return True
            if rp == "prepaid":
                return pay != "cod"
            return pay == rp

        def _match(rule):
            if rule.destination_governorate:
                if not dest or rule.destination_governorate.strip().lower() != dest.lower():
                    return False
            if not _pay_ok(rule):
                return False
            if rule.carrier not in ("any", "standard", False, None):
                if carrier and rule.carrier != carrier:
                    return False
            if order_value < float(rule.min_order_value or 0.0):
                return False
            max_v = float(rule.max_order_value or 0.0)
            if max_v > 0 and order_value > max_v:
                return False
            return True

        # Prefer specific destination matches over blank (all destinations)
        specific = [r for r in rules if r.destination_governorate and _match(r)]
        general = [r for r in rules if not r.destination_governorate and _match(r)]
        chosen = (specific + general)[:1]
        if chosen:
            rule = chosen[0]
            return (
                float(rule.customer_charge or 0.0),
                rule.status or "configured",
                rule.source or f"delivery.revenue.rule#{rule.id}",
                rule,
            )

        # Policy fallback
        amt = float(getattr(policy, "customer_delivery_charge_amount", 0.0) or 0.0)
        st = getattr(policy, "customer_delivery_charge_status", None) or "configured"
        src = getattr(policy, "customer_delivery_charge_source", None) or "policy fallback"
        return amt, st, src, self.browse()
