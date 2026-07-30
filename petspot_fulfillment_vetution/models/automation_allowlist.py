# -*- coding: utf-8 -*-
"""Exact-mapping automation allowlist — never title-inferred."""

from odoo import api, fields, models
from odoo.exceptions import UserError


class PetspotVetutionAutomationAllowlist(models.Model):
    _name = "petspot.vetution.automation.allowlist"
    _description = "Vetution Automation Allowlist"
    _order = "id desc"

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    product_id = fields.Many2one("product.product", required=True, index=True)
    default_code = fields.Char(related="product_id.default_code", store=True)
    vetution_size_id = fields.Integer(required=True, index=True)
    vetution_drug_id = fields.Integer()
    offer_id = fields.Many2one("vetution.supplier.offer")
    proof_note = fields.Text(
        required=True,
        help="How the exact size identity was proven (never title similarity).",
    )
    confirmed_by = fields.Many2one("res.users", default=lambda self: self.env.user)
    confirmed_at = fields.Datetime(default=fields.Datetime.now)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company
    )

    _sql_constraints = [
        (
            "petspot_vetution_allowlist_product_uniq",
            "unique(product_id, company_id)",
            "Product already on the automation allowlist.",
        ),
        (
            "petspot_vetution_allowlist_size_uniq",
            "unique(vetution_size_id, company_id)",
            "Vetution size already on the automation allowlist.",
        ),
    ]

    @api.model
    def is_product_allowed(self, product):
        if not product:
            return False
        return bool(
            self.search_count(
                [("active", "=", True), ("product_id", "=", product.id)]
            )
        )

    @api.model
    def add_exact_mapping(self, product, proof_note):
        product.ensure_one()
        size_id = product.vetution_size_id
        if not size_id:
            raise UserError("Cannot allowlist without proven product.vetution_size_id.")
        offer = self.env["vetution.supplier.offer"].search(
            [("offer_type", "=", "vetution"), ("vetution_size_id", "=", size_id)],
            limit=1,
        )
        if not offer:
            raise UserError("No Vetution primary offer for this size ID.")
        if offer.product_id and offer.product_id != product:
            raise UserError("Offer is linked to a different product.")
        if offer.vetution_size_id != size_id:
            raise UserError("Offer size mismatch.")
        existing = self.search([("product_id", "=", product.id)], limit=1)
        vals = {
            "name": f"ALLOW/{product.default_code or product.id}",
            "product_id": product.id,
            "vetution_size_id": size_id,
            "vetution_drug_id": offer.vetution_drug_id or False,
            "offer_id": offer.id,
            "proof_note": proof_note,
            "active": True,
            "confirmed_by": self.env.uid,
            "confirmed_at": fields.Datetime.now(),
        }
        if existing:
            existing.write(vals)
            return existing
        return self.create(vals)

    @api.model
    def coverage_report(self):
        rows = self.search([("active", "=", True)])
        return {
            "allowlist_count": len(rows),
            "skus": rows.mapped("default_code"),
            "size_ids": rows.mapped("vetution_size_id"),
        }
