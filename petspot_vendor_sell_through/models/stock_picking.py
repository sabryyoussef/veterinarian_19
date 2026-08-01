# -*- coding: utf-8 -*-
from odoo import models


class StockPicking(models.Model):
    _inherit = "stock.picking"

    def _action_done(self):
        res = super()._action_done()
        from odoo.addons.petspot_vendor_sell_through.services.allocator import (
            allocate_outgoing_move,
            reverse_customer_return,
        )

        for picking in self:
            for move in picking.move_ids.filtered(lambda m: m.state == "done"):
                try:
                    with self.env.cr.savepoint():
                        if move.location_id.usage == "internal" and move.location_dest_id.usage == "customer":
                            allocate_outgoing_move(self.env, move)
                        elif move.location_id.usage == "customer" and move.location_dest_id.usage == "internal":
                            reverse_customer_return(self.env, move)
                        elif (
                            "pos_order_id" in picking._fields
                            and picking.pos_order_id
                            and move.state == "done"
                        ):
                            allocate_outgoing_move(self.env, move)
                except Exception:
                    continue
        return res
