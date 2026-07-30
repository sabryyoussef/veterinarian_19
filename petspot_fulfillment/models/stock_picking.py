# -*- coding: utf-8 -*-
from odoo import models


class StockPicking(models.Model):
    _inherit = "stock.picking"

    def action_petspot_mark_receipt_done_hook(self):
        """Optional helper after supplier receipt — does not auto-create ShipBlu."""
        Case = self.env["petspot.fulfillment.case"]
        for picking in self:
            so = picking.sale_id
            if not so:
                continue
            case = Case.search([("sale_order_id", "=", so.id)], limit=1)
            if case and case.state == "awaiting_receipt" and picking.state == "done":
                case.action_mark_ready_for_delivery()
        return True
