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

    # --- Phase 4: multi-variant pricing audit ---
    change_kind = fields.Selection(
        [
            ("template_single", "Single-variant template base price"),
            ("template_base", "Multi-variant template base (anchor)"),
            ("variant_extra", "Variant price_extra"),
            ("variant_archived", "Ineligible variant archived"),
        ],
        default="template_single",
        index=True,
    )
    is_multi_variant = fields.Boolean(index=True)
    is_base_anchor = fields.Boolean(
        help="True for the variant chosen as the template base-price anchor.",
    )
    ptav_id = fields.Many2one(
        "product.template.attribute.value",
        string="Pack Size Attribute Value",
        ondelete="set null",
    )
    old_price_extra = fields.Float()
    new_price_extra = fields.Float()
    variant_archived = fields.Boolean(
        help="True when an ineligible variant was archived to prevent sale.",
    )
    variant_active_old = fields.Boolean(
        help="product.product.active state before this change (for rollback).",
    )
    eligibility_flags = fields.Char(
        help="Non-blocking flags recorded at activation (e.g. expiry_unknown).",
    )
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
