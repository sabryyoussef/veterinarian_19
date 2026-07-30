# -*- coding: utf-8 -*-
"""Mocked ShipBlu AWB orchestration — real create stays OFF until package sizes verified."""

from odoo import api, fields, models
from odoo.exceptions import UserError


class PetspotVetutionShipbluMockAwb(models.Model):
    _name = "petspot.vetution.shipblu.mock.awb"
    _description = "Mock ShipBlu AWB (TEST only)"
    _order = "id desc"

    name = fields.Char(required=True, default="MOCK-AWB")
    case_id = fields.Many2one("petspot.fulfillment.case", required=True, index=True, ondelete="cascade")
    inquiry_id = fields.Many2one("petspot.availability.inquiry", index=True)
    tracking_number = fields.Char(index=True)
    shipblu_order_id = fields.Char(index=True)
    package_size_verified = fields.Boolean(default=False)
    state = fields.Selection(
        [
            ("blocked", "Blocked"),
            ("mocked_created", "Mock created"),
            ("tracking_synced", "Tracking synced (sim)"),
            ("delivered", "Delivered (sim)"),
            ("cancelled", "Cancelled"),
        ],
        default="blocked",
        required=True,
        index=True,
    )
    block_reason = fields.Char()
    destination_governorate = fields.Char()
    delivery_margin = fields.Float()
    delivery_review_required = fields.Boolean(default=False)
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    _sql_constraints = [
        (
            "petspot_vetution_mock_awb_case_uniq",
            "unique(case_id, company_id)",
            "Exactly one mock AWB per fulfillment case.",
        ),
    ]

    @api.model
    def create_for_case(self, case, *, package_size_verified=False, assessment=None):
        case.ensure_one()
        existing = self.search([("case_id", "=", case.id)], limit=1)
        if existing:
            return existing

        reasons = []
        backend = self.env["shipblu.backend"].sudo().search([], limit=1)
        if backend and backend.shipment_creation_enabled:
            # Still force mock path — never call live create from this model
            pass
        if not package_size_verified:
            reasons.append("package_size_ids_unverified")
        if case.delivery_method == "store_pickup":
            reasons.append("store_pickup_no_awb")
        if case.payment_status not in ("paid", "manual_paid") and case.delivery_method != "store_pickup":
            # COD may proceed under policy — treat unpaid non-COD as block
            if getattr(case, "payment_method", None) != "cod":
                reasons.append("payment_gate")
        if assessment and assessment.delivery_decision_code == "DELIVERY_PRICE_REVIEW_REQUIRED":
            reasons.append("delivery_margin_gate")
        if assessment and getattr(assessment, "delivery_review_required", False):
            reasons.append("delivery_margin_gate")

        vals = {
            "name": f"MOCK-AWB/{case.name or case.id}",
            "case_id": case.id,
            "inquiry_id": case.inquiry_id.id if case.inquiry_id else False,
            "package_size_verified": package_size_verified,
            "destination_governorate": assessment.economics_scenario if assessment else False,
            "delivery_margin": assessment.delivery_margin if assessment else 0.0,
            "delivery_review_required": bool(
                assessment and assessment.delivery_decision_code == "DELIVERY_PRICE_REVIEW_REQUIRED"
            ),
        }
        if reasons:
            vals["state"] = "blocked"
            vals["block_reason"] = "|".join(reasons)
            return self.create(vals)

        # Mock create — no remote API
        vals.update(
            {
                "state": "mocked_created",
                "tracking_number": f"MOCK{case.id:08d}",
                "shipblu_order_id": f"9{case.id:07d}",
            }
        )
        return self.create(vals)

    def action_simulate_tracking_sync(self):
        for rec in self:
            if rec.state != "mocked_created":
                continue
            rec.state = "tracking_synced"

    def action_simulate_delivered(self):
        for rec in self:
            if rec.state not in ("mocked_created", "tracking_synced"):
                continue
            rec.state = "delivered"
