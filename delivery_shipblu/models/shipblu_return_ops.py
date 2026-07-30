# -*- coding: utf-8 -*-
from odoo import fields, models


class ShipBluReturnOrderOps(models.Model):
    _inherit = "shipblu.return.order"

    workflow_state = fields.Selection(
        [
            ("customer_refused", "Customer refused"),
            ("return_requested", "Return requested"),
            ("return_in_transit", "Return in transit"),
            ("return_delivered", "Return delivered"),
            ("return_received", "Return received"),
            ("return_closed", "Return closed"),
        ],
        default="return_requested",
    )
    sale_order_id = fields.Many2one("sale.order", index=True)
    picking_id = fields.Many2one("stock.picking", index=True)
    shipment_id = fields.Many2one("shipblu.shipment", index=True)
    rejection_reason = fields.Char()
    return_collection_amount = fields.Float(digits=(16, 2))
    customer_payment_state = fields.Selection(
        [
            ("unknown", "Unknown"),
            ("paid", "Paid"),
            ("not_paid", "Not paid"),
        ],
        default="unknown",
    )
    estimated_return_fee = fields.Float(digits=(16, 2))
    estimated_refusal_charge = fields.Float(digits=(16, 2))
    final_confirmed_charge = fields.Float(digits=(16, 2))
    return_tracking_ref = fields.Char()
    settlement_impact = fields.Text()
    note = fields.Text(
        default="Return charges are estimates only — do not auto-post accounting entries.",
    )

    def action_estimate_return_charges(self):
        for rec in self:
            backend = rec.backend_id
            shipping = 0.0
            if rec.shipment_id:
                shipping = float(rec.shipment_id.cost_base_fee or 0.0) + float(
                    rec.shipment_id.cost_size_surcharge or 0.0
                )
            rec.estimated_return_fee = float(backend.return_service_fee or 0.0)
            if rec.customer_payment_state == "not_paid":
                pct = float(backend.return_refusal_charge_percent or 90.0)
                rec.estimated_refusal_charge = round(shipping * pct / 100.0, 2)
            else:
                rec.estimated_refusal_charge = 0.0
        return True
