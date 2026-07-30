# -*- coding: utf-8 -*-
"""Controlled mapping review — never bulk title-match."""

from __future__ import annotations

from odoo import api, fields, models
from odoo.exceptions import UserError


class PetspotVetutionMappingReview(models.Model):
    _name = "petspot.vetution.mapping.review"
    _description = "Vetution Product Mapping Review"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(required=True, default="Mapping Review")
    state = fields.Selection(
        [
            ("pending", "Pending"),
            ("confirmed", "Confirmed"),
            ("rejected", "Rejected"),
        ],
        default="pending",
        required=True,
        tracking=True,
        index=True,
    )
    product_id = fields.Many2one("product.product", required=True, index=True, tracking=True)
    product_tmpl_id = fields.Many2one(related="product_id.product_tmpl_id", store=True)
    default_code = fields.Char(related="product_id.default_code", store=True)
    shopify_variant_id = fields.Char(index=True)
    current_vetution_size_id = fields.Integer(
        compute="_compute_current_ids", store=False
    )
    current_vetution_id = fields.Integer(compute="_compute_current_ids", store=False)
    proposed_vetution_size_id = fields.Integer(tracking=True)
    proposed_vetution_drug_id = fields.Integer(tracking=True)
    proposed_offer_id = fields.Many2one("vetution.supplier.offer", tracking=True)
    reason = fields.Selection(
        [
            ("missing_size_id", "Missing vetution_size_id"),
            ("ambiguous", "Ambiguous mapping"),
            ("pack_mismatch", "Pack / variant mismatch"),
            ("inactive_offer", "Inactive / missing offer"),
            ("no_vetution_equivalent", "No Vetution equivalent"),
            ("manual", "Manual review"),
        ],
        required=True,
        default="missing_size_id",
    )
    note = fields.Text()
    confirmed_by = fields.Many2one("res.users", copy=False)
    confirmed_at = fields.Datetime(copy=False)
    inquiry_id = fields.Many2one("petspot.availability.inquiry", ondelete="set null")
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company
    )

    @api.depends("product_id", "product_id.vetution_size_id", "product_id.product_tmpl_id")
    def _compute_current_ids(self):
        for rec in self:
            rec.current_vetution_size_id = rec.product_id.vetution_size_id or 0
            tmpl = rec.product_id.product_tmpl_id
            rec.current_vetution_id = getattr(tmpl, "vetution_id", 0) or 0

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "Mapping Review") == "Mapping Review":
                code = vals.get("default_code") or vals.get("product_id") or "NEW"
                vals["name"] = f"MAP/{code}"
        return super().create(vals_list)

    def action_confirm_mapping(self):
        """Apply exact size mapping with audit — no title matching."""
        for rec in self:
            if not rec.proposed_vetution_size_id:
                raise UserError("Proposed Vetution size ID is required for confirmation.")
            product = rec.product_id
            # Uniqueness: another product already owning this size?
            conflict = self.env["product.product"].search(
                [
                    ("vetution_size_id", "=", rec.proposed_vetution_size_id),
                    ("id", "!=", product.id),
                ],
                limit=1,
            )
            if conflict:
                raise UserError(
                    f"Size {rec.proposed_vetution_size_id} already mapped to "
                    f"{conflict.display_name} ({conflict.default_code})."
                )
            # Offer must exist and size must match proposed drug if set
            offer = rec.proposed_offer_id
            if not offer:
                offer = self.env["vetution.supplier.offer"].search(
                    [
                        ("offer_type", "=", "vetution"),
                        ("vetution_size_id", "=", rec.proposed_vetution_size_id),
                    ],
                    limit=1,
                )
            if not offer:
                raise UserError("No Vetution primary offer found for the proposed size ID.")
            if (
                rec.proposed_vetution_drug_id
                and offer.vetution_drug_id
                and offer.vetution_drug_id != rec.proposed_vetution_drug_id
            ):
                raise UserError("Proposed drug ID does not match the offer's drug ID.")
            old_size = product.vetution_size_id
            product.write({"vetution_size_id": rec.proposed_vetution_size_id})
            # Link offer if unmapped
            if not offer.product_id:
                offer.write({"product_id": product.id})
            elif offer.product_id != product:
                raise UserError(
                    f"Offer already linked to {offer.product_id.display_name}."
                )
            rec.write(
                {
                    "state": "confirmed",
                    "confirmed_by": self.env.uid,
                    "confirmed_at": fields.Datetime.now(),
                    "proposed_offer_id": offer.id,
                }
            )
            rec.message_post(
                body=(
                    f"Mapping confirmed: size {old_size or '∅'} → "
                    f"{rec.proposed_vetution_size_id} "
                    f"(offer {offer.id}, drug {offer.vetution_drug_id})."
                )
            )
        return True

    def action_reject(self):
        self.write({"state": "rejected"})
        return True

    @api.model
    def ensure_pending(self, product, reason, inquiry=None, shopify_variant_id=False, note=False):
        existing = self.search(
            [
                ("product_id", "=", product.id),
                ("state", "=", "pending"),
                ("reason", "=", reason),
            ],
            limit=1,
        )
        if existing:
            if inquiry and not existing.inquiry_id:
                existing.inquiry_id = inquiry.id
            return existing
        return self.create(
            {
                "product_id": product.id,
                "reason": reason,
                "inquiry_id": inquiry.id if inquiry else False,
                "shopify_variant_id": shopify_variant_id or False,
                "note": note or False,
                "name": f"MAP/{product.default_code or product.id}",
            }
        )

    @api.model
    def build_coverage_report(self):
        """Return sanitized coverage counters for evidence / UI."""
        Product = self.env["product.product"]
        Offer = self.env["vetution.supplier.offer"]
        Map = self.env["shopify.variant.map"] if "shopify.variant.map" in self.env else None

        with_size = Product.search_count([("vetution_size_id", "!=", False)])
        shopify_mapped = 0
        shopify_with_size = 0
        shopify_missing_size = 0
        if Map is not None:
            maps = Map.search([])
            shopify_mapped = len(maps)
            for m in maps:
                if m.product_id and m.product_id.vetution_size_id:
                    shopify_with_size += 1
                elif m.product_id:
                    shopify_missing_size += 1

        offers = Offer.search([("offer_type", "=", "vetution")])
        mapped_offers = offers.filtered(lambda o: o.product_id)
        unmapped_offers = offers - mapped_offers
        pending = self.search_count([("state", "=", "pending")])
        return {
            "variants_with_vetution_size_id": with_size,
            "shopify_mapped_variants": shopify_mapped,
            "shopify_and_vetution_size": shopify_with_size,
            "shopify_missing_vetution_size": shopify_missing_size,
            "primary_offers": len(offers),
            "offers_with_product": len(mapped_offers),
            "offers_unmapped": len(unmapped_offers),
            "mapping_reviews_pending": pending,
        }

    @api.model
    def action_export_coverage_report(self):
        """Combined mapping + automation-allowlist coverage counters.

        Read-only aggregation used by the Vetution Data Health dashboard and
        by manual audits; never writes any commercial data.
        """
        report = self.build_coverage_report()
        allowlist = self.env["petspot.vetution.automation.allowlist"].coverage_report()
        report.update(
            {
                "allowlist_count": allowlist.get("allowlist_count", 0),
                "allowlist_skus": allowlist.get("skus", []),
                "allowlist_size_ids": allowlist.get("size_ids", []),
                "mapping_reviews_confirmed": self.search_count([("state", "=", "confirmed")]),
                "mapping_reviews_rejected": self.search_count([("state", "=", "rejected")]),
            }
        )
        return report
