# -*- coding: utf-8 -*-
from odoo import fields, models

COMPONENT_STATES = [
    ("unknown", "Unknown"),
    ("verified_zero", "Verified zero"),
    ("configured", "Configured"),
    ("estimated", "Estimated"),
]

PAYMENT_METHODS = [
    ("cod", "COD"),
    ("paymob", "Paymob"),
    ("card", "Card"),
    ("wallet", "Wallet"),
    ("bank_transfer", "Bank Transfer"),
]


class PetspotVetutionPaymentFee(models.Model):
    _name = "petspot.vetution.payment.fee"
    _description = "Payment Method Fee Schedule"
    _order = "payment_method"

    policy_id = fields.Many2one(
        "petspot.vetution.landed.cost.policy", required=True, ondelete="cascade", index=True
    )
    payment_method = fields.Selection(PAYMENT_METHODS, required=True)
    percent = fields.Float(string="Fee %")
    fixed_amount = fields.Float(string="Fixed fee (EGP)")
    status = fields.Selection(COMPONENT_STATES, default="unknown", required=True)
    source_note = fields.Char()
    active = fields.Boolean(default=True)

    _sql_constraints = [
        (
            "petspot_payfee_method_uniq",
            "unique(policy_id, payment_method)",
            "Payment method already defined for this policy.",
        ),
    ]
