# -*- coding: utf-8 -*-
"""Availability inquiry actions for Vetution shadow assessment (Phase 15A)."""

from odoo import fields, models
from odoo.exceptions import UserError


class PetspotAvailabilityInquiry(models.Model):
    _inherit = "petspot.availability.inquiry"

    vetution_assessment_id = fields.Many2one(
        "petspot.vetution.shadow.assessment",
        string="Active Vetution Assessment",
        copy=False,
    )
    vetution_assessment_state = fields.Selection(
        related="vetution_assessment_id.state",
        store=True,
        string="Vetution Assessment State",
    )
    vetution_size_id_resolved = fields.Integer(copy=False)
    vetution_resolution_method = fields.Char(copy=False)
    vetution_assessment_ids = fields.One2many(
        "petspot.vetution.shadow.assessment",
        "inquiry_id",
        string="Assessment History",
    )

    def action_assess_vetution_availability(self):
        Assessment = self.env["petspot.vetution.shadow.assessment"]
        for inquiry in self:
            Assessment.assess_inquiry(inquiry, force_refresh=False)
        return self._action_open_assessment()

    def action_refresh_and_reassess_vetution(self):
        Assessment = self.env["petspot.vetution.shadow.assessment"]
        for inquiry in self:
            Assessment.assess_inquiry(inquiry, force_refresh=True)
        return self._action_open_assessment()

    def action_open_vetution_mapping_review(self):
        self.ensure_one()
        review = self.vetution_assessment_id.mapping_review_id
        if not review and self.product_id:
            review = self.env["petspot.vetution.mapping.review"].ensure_pending(
                self.product_id,
                "missing_size_id",
                inquiry=self,
                shopify_variant_id=self.shopify_variant_id,
            )
        if not review:
            raise UserError("No mapping review available for this inquiry.")
        return {
            "type": "ir.actions.act_window",
            "name": "Mapping Review",
            "res_model": "petspot.vetution.mapping.review",
            "res_id": review.id,
            "view_mode": "form",
            "target": "current",
        }

    def _action_open_assessment(self):
        self.ensure_one()
        assessment = self.vetution_assessment_id
        if not assessment:
            raise UserError("Assessment was not created.")
        return {
            "type": "ir.actions.act_window",
            "name": "Vetution Shadow Assessment",
            "res_model": "petspot.vetution.shadow.assessment",
            "res_id": assessment.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_source_supplier(self):
        """Prefer shadow assessment when bridge is installed; keep original stub safe."""
        # Do not create RFQ/PO — Phase 15A shadow only.
        if self.env.context.get("petspot_skip_vetution_bridge"):
            return super().action_source_supplier()
        for inquiry in self:
            self.env["petspot.vetution.shadow.assessment"].assess_inquiry(
                inquiry, force_refresh=False
            )
            inquiry.message_post(
                body=(
                    "Vetution shadow assessment completed (Phase 15A). "
                    "No quotation, PO, or customer message was created. "
                    "Supplier stock is not reserved."
                )
            )
            if inquiry.state in ("draft", "review_required", "store_check"):
                inquiry.state = "supplier_check"
        return True if len(self) > 1 else self._action_open_assessment()
