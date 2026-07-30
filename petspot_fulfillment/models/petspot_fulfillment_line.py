# -*- coding: utf-8 -*-
from odoo import fields, models

from .petspot_fulfillment_constants import LINE_SOURCE


class PetspotFulfillmentLine(models.Model):
    _name = "petspot.fulfillment.line"
    _description = "PetSpot Fulfillment Line"
    _order = "id"

    case_id = fields.Many2one(
        "petspot.fulfillment.case",
        required=True,
        ondelete="cascade",
        index=True,
    )
    sale_line_id = fields.Many2one("sale.order.line", ondelete="set null", index=True)
    product_id = fields.Many2one("product.product", required=True)
    product_uom_qty = fields.Float(default=1.0)
    source = fields.Selection(LINE_SOURCE, default="unclassified", required=True)
    vendor_id = fields.Many2one("res.partner", string="Supplier")
    purchase_line_id = fields.Many2one("purchase.order.line", ondelete="set null")
    note = fields.Char()

    _sql_constraints = [
        (
            "petspot_ff_line_sale_unique",
            "unique(case_id, sale_line_id)",
            "Sale line already linked on this fulfillment case.",
        ),
    ]
