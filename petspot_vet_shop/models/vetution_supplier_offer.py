# -*- coding: utf-8 -*-
"""Recompute shop commercial state when supplier offers change."""

from odoo import api, models


class VetutionSupplierOffer(models.Model):
    _inherit = "vetution.supplier.offer"

    def write(self, vals):
        res = super().write(vals)
        commercial_keys = {
            "availability_state", "show", "show_price", "effective_cost",
            "is_stale", "is_expired", "is_near_expiry", "expiry_date",
            "is_express", "product_id", "active",
        }
        if commercial_keys.intersection(vals):
            products = self.mapped("product_id")
            if products:
                products._compute_petspot_shop_state()
                products.mapped("product_tmpl_id")._compute_petspot_shop_has_sellable()
        return res

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        products = records.mapped("product_id")
        if products:
            products._compute_petspot_shop_state()
            products.mapped("product_tmpl_id")._compute_petspot_shop_has_sellable()
        return records
