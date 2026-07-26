# -*- coding: utf-8 -*-
"""Variant-level Vetution pricing audit fields on product.product."""

from odoo import fields, models


class ProductProduct(models.Model):
    _inherit = "product.product"

    vetution_variant_price_activated = fields.Boolean(
        string="Vetution Variant Price Activated",
        copy=False,
        help="True after Phase 4 wrote this variant's price_extra.",
    )
    vetution_variant_price_extra = fields.Float(
        string="Vetution Variant Price Extra",
        copy=False,
        help="price_extra written by the multi-variant activation (audit mirror).",
    )
    vetution_variant_sale_price = fields.Float(
        string="Vetution Variant Sale Price",
        copy=False,
        help="Resolved PetSpot selling price for this pack size (audit mirror).",
    )
    vetution_variant_blocked_by_pricing = fields.Boolean(
        string="Vetution Blocked (Ineligible)",
        copy=False,
        help="True when this variant was archived by pricing activation because it was "
        "commercially ineligible. Cleared on rollback.",
    )
