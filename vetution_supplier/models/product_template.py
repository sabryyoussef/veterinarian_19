# -*- coding: utf-8 -*-
"""Pricing-engine shell fields on product.template (preview only)."""

from odoo import api, fields, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    vetution_sale_price_locked = fields.Boolean(
        string="Lock Sale Price",
        help="When set, future pricing engine must not change list_price.",
        copy=False,
    )
    vetution_preview_sale_price = fields.Float(
        string="Vetution Preview Sale Price",
        compute="_compute_vetution_preview_sale_price",
        help="Computed preview from supplier cost × markup. Phase 1 never writes list_price.",
    )
    vetution_offer_count = fields.Integer(compute="_compute_vetution_offer_count")
    vetution_primary_availability = fields.Char(
        compute="_compute_vetution_primary_availability",
    )

    def _compute_vetution_offer_count(self):
        Offer = self.env["vetution.supplier.offer"]
        for tmpl in self:
            tmpl.vetution_offer_count = Offer.search_count(
                [("product_tmpl_id", "=", tmpl.id)]
            )

    def _compute_vetution_primary_availability(self):
        Offer = self.env["vetution.supplier.offer"]
        for tmpl in self:
            offer = Offer.search(
                [
                    ("product_tmpl_id", "=", tmpl.id),
                    ("offer_type", "=", "vetution"),
                ],
                limit=1,
                order="id",
            )
            tmpl.vetution_primary_availability = (
                offer.availability_state if offer else False
            )

    def _compute_vetution_preview_sale_price(self):
        Offer = self.env["vetution.supplier.offer"]
        Connection = self.env["vetution.connection"]
        conn = Connection.search([("active", "=", True)], limit=1)
        for tmpl in self:
            offer = Offer.search(
                [
                    ("product_tmpl_id", "=", tmpl.id),
                    ("offer_type", "=", "vetution"),
                    ("effective_cost", ">", 0),
                ],
                limit=1,
                order="effective_cost asc",
            )
            if offer and conn:
                tmpl.vetution_preview_sale_price = conn.preview_sale_price(
                    offer.effective_cost
                )
            elif offer:
                tmpl.vetution_preview_sale_price = offer.preview_sale_price
            else:
                tmpl.vetution_preview_sale_price = 0.0
