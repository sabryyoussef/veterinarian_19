# -*- coding: utf-8 -*-
"""Variant-level Vetution pricing audit fields on product.product."""

from odoo import api, fields, models

PETSPOT_PRICING_STATUSES = [
    ("priced", "Priced"),
    ("blocked_missing_offer", "Blocked — missing offer"),
    ("blocked_invalid_offer", "Blocked — invalid offer"),
    ("blocked_mapping", "Blocked — mapping"),
    ("blocked_stale_offer", "Blocked — stale offer"),
    ("blocked_source_hidden", "Blocked — source price hidden"),
    ("manual_review", "Manual review"),
    ("non_retail", "Non-retail"),
]


class ProductProduct(models.Model):
    _inherit = "product.product"

    vetution_variant_price_activated = fields.Boolean(
        string="Catalog variant Price Activated",
        copy=False,
        help="True after Phase 4 wrote this variant's price_extra.",
    )
    vetution_variant_price_extra = fields.Float(
        string="Catalog variant Price Extra",
        copy=False,
        help="price_extra written by the multi-variant activation (audit mirror).",
    )
    vetution_variant_sale_price = fields.Float(
        string="Catalog variant Sale Price",
        copy=False,
        help="Resolved PetSpot selling price for this pack size (audit mirror).",
    )
    vetution_variant_blocked_by_pricing = fields.Boolean(
        string="Catalog blocked (Ineligible)",
        copy=False,
        help="True when this variant was archived by pricing activation because it was "
        "commercially ineligible. Cleared on rollback.",
    )
    petspot_pricing_status = fields.Selection(
        selection=PETSPOT_PRICING_STATUSES,
        string="PetSpot pricing status",
        copy=False,
        index=True,
        help="Odoo-controlled retail pricing state synchronized to Shopify variant metafield "
        "petspot.pricing_status. Storefront must not show LE1 or allow purchase when not priced.",
    )

    def _petspot_resolved_sale_price(self):
        self.ensure_one()
        if (self.vetution_variant_sale_price or 0.0) > 1.01:
            return float(self.vetution_variant_sale_price)
        return float(self.lst_price or self.list_price or 0.0)

    @api.model
    def petspot_pricing_status_for_variant(self, variant, offer=None):
        """Deterministic status classifier used by repair/containment jobs."""
        variant.ensure_one()
        tmpl = variant.product_tmpl_id
        if tmpl.type == "service":
            return "non_retail"
        code = (variant.default_code or "").strip().upper()
        if code in {"EXAM", "TIPS", "ULTRASOUND"} or code.startswith("DIAG"):
            return "non_retail"
        sale = variant._petspot_resolved_sale_price()
        activated = bool(
            variant.vetution_variant_price_activated or tmpl.vetution_price_activated
        )
        if activated and sale > 1.01:
            return "priced"
        if not tmpl.vetution_id and not variant.vetution_size_id:
            return "manual_review"
        if tmpl.vetution_id and not variant.vetution_size_id:
            return "blocked_mapping"
        Offer = self.env["vetution.supplier.offer"]
        if offer is None:
            offer = Offer.search(
                [
                    ("product_id", "=", variant.id),
                    ("offer_type", "=", "vetution"),
                    ("active", "=", True),
                ],
                order="effective_cost asc, id asc",
                limit=1,
            )
        if not offer:
            return "blocked_missing_offer"
        cost = float(offer.effective_cost or 0.0)
        if offer.is_stale:
            return "blocked_stale_offer"
        if cost > 0 and cost <= 1.01:
            return "blocked_invalid_offer"
        if not offer.show or not offer.show_price or cost <= 0:
            return "blocked_source_hidden"
        return "manual_review"
