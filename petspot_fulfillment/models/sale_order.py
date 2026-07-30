# -*- coding: utf-8 -*-
from odoo import api, fields, models


class SaleOrder(models.Model):
    _inherit = "sale.order"

    petspot_fulfillment_case_id = fields.Many2one(
        "petspot.fulfillment.case",
        compute="_compute_petspot_case",
        string="Fulfillment Case",
    )
    petspot_fulfillment_state = fields.Selection(
        related="petspot_fulfillment_case_id.state",
        string="Fulfillment State",
        store=False,
    )
    petspot_fulfillment_path = fields.Selection(
        related="petspot_fulfillment_case_id.path",
        string="Fulfillment Path",
        store=False,
    )

    def _compute_petspot_case(self):
        Case = self.env["petspot.fulfillment.case"]
        for order in self:
            case = Case.search([("sale_order_id", "=", order.id)], limit=1)
            order.petspot_fulfillment_case_id = case

    def action_petspot_open_fulfillment(self):
        self.ensure_one()
        case = self.env["petspot.fulfillment.case"].get_or_create_for_sale_order(self)
        return {
            "type": "ir.actions.act_window",
            "res_model": "petspot.fulfillment.case",
            "view_mode": "form",
            "res_id": case.id,
        }

    @api.model_create_multi
    def create(self, vals_list):
        orders = super().create(vals_list)
        # Bind fulfillment case for Shopify imports without touching catalog
        Case = self.env["petspot.fulfillment.case"]
        for order in orders:
            if getattr(order, "shopify_order_id", False):
                if not Case._is_cutover_eligible(order):
                    continue
                Case.get_or_create_for_sale_order(order, classification_source="auto")
        return orders
