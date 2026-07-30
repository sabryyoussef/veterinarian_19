# -*- coding: utf-8 -*-
from odoo import fields, models


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    petspot_fulfillment_case_id = fields.Many2one(
        "petspot.fulfillment.case",
        string="Fulfillment Case",
        index=True,
        copy=False,
    )
