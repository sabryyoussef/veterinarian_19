# -*- coding: utf-8 -*-
"""Audit log for Vetution → PetSpot selling-price activations."""

from odoo import fields, models


class VetutionPriceChangeLog(models.Model):
    _name = "vetution.price.change.log"
    _description = "Vetution Selling Price Change Log"
    _order = "id desc"

    name = fields.Char(required=True, default="Price Activation")
    connection_id = fields.Many2one("vetution.connection", required=True, ondelete="cascade")
    product_tmpl_id = fields.Many2one("product.template", ondelete="set null", index=True)
    product_id = fields.Many2one("product.product", ondelete="set null", index=True)
    offer_id = fields.Many2one("vetution.supplier.offer", ondelete="set null", index=True)
    dry_run = fields.Boolean()
    placeholder_replacement = fields.Boolean(
        help="True when previous list_price was a placeholder (≤ 1.01).",
    )
    skipped = fields.Boolean()
    skip_reason = fields.Char()
    old_list_price = fields.Float()
    new_list_price = fields.Float()
    supplier_cost = fields.Float()
    markup_price = fields.Float()
    minimum_margin_price = fields.Float()
    minimum_profit_price = fields.Float()
    candidate = fields.Float()
    markup_percent = fields.Float()
    min_margin_percent = fields.Float()
    min_profit_amount = fields.Float()
    rounding = fields.Float()
    gross_profit = fields.Float()
    gross_margin_percent = fields.Float()
    note = fields.Text()
