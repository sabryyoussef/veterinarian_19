# -*- coding: utf-8 -*-
from odoo import fields, models

COMPONENT_STATES = [
    ("unknown", "Unknown"),
    ("verified_zero", "Verified zero"),
    ("configured", "Configured"),
]

PACKAGING_TYPES = [
    ("envelope", "Envelope"),
    ("flyer", "Flyer"),
    ("small_box", "Small box"),
    ("medium_box", "Medium box"),
    ("large_box", "Large box"),
    ("custom", "Custom packaging"),
]


class PetspotVetutionPackagingCost(models.Model):
    _name = "petspot.vetution.packaging.cost"
    _description = "Packaging Cost Schedule"
    _order = "packaging_type"

    policy_id = fields.Many2one(
        "petspot.vetution.landed.cost.policy", required=True, ondelete="cascade", index=True
    )
    packaging_type = fields.Selection(PACKAGING_TYPES, required=True)
    amount = fields.Float(default=0.0)
    status = fields.Selection(COMPONENT_STATES, default="unknown", required=True)
    source_note = fields.Char()
    active = fields.Boolean(default=True)

    _sql_constraints = [
        (
            "petspot_pkg_type_uniq",
            "unique(policy_id, packaging_type)",
            "Packaging type already defined for this policy.",
        ),
    ]
