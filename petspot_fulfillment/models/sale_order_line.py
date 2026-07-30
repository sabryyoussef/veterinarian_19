# -*- coding: utf-8 -*-
from odoo import fields, models

from .petspot_fulfillment_constants import LINE_SOURCE


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    petspot_source = fields.Selection(
        LINE_SOURCE,
        string="Fulfillment Source",
        compute="_compute_petspot_source",
        readonly=False,
    )

    def _compute_petspot_source(self):
        Line = self.env["petspot.fulfillment.line"]
        for sol in self:
            fl = Line.search([("sale_line_id", "=", sol.id)], limit=1)
            sol.petspot_source = fl.source if fl else "unclassified"
