# -*- coding: utf-8 -*-
"""Giza receipt / store pickup helpers — synthetic stock moves on TEST only."""

from odoo import api, fields, models
from odoo.exceptions import UserError


class PetspotVetutionGizaReceipt(models.Model):
    _name = "petspot.vetution.giza.receipt"
    _description = "Giza / Haram Fulfillment Receipt"
    _order = "id desc"

    name = fields.Char(required=True, default="GIZA-RCV")
    case_id = fields.Many2one("petspot.fulfillment.case", required=True, index=True, ondelete="cascade")
    picking_id = fields.Many2one("stock.picking", copy=False)
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("received", "Received at Giza"),
            ("pickup_ready", "Ready for pickup"),
            ("handed_over", "Handed over"),
            ("partial", "Partial receipt"),
            ("cancelled", "Cancelled"),
        ],
        default="draft",
        required=True,
        index=True,
    )
    pickup_notified = fields.Boolean(default=False)
    synthetic_move = fields.Boolean(
        default=True,
        help="TEST synthetic receipt — not a Production stock mutation path.",
    )
    note = fields.Char(
        default="Physical location: Haram clinic / 451 Haram Street Nasr Eldin, Giza (pickup 10067).",
    )
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    _sql_constraints = [
        (
            "petspot_vetution_giza_case_uniq",
            "unique(case_id, company_id)",
            "One Giza receipt record per case.",
        ),
    ]

    @api.model
    def receive_for_case(self, case, *, partial=False):
        case.ensure_one()
        rec = self.search([("case_id", "=", case.id)], limit=1)
        if not rec:
            rec = self.create({"name": f"GIZA/{case.name or case.id}", "case_id": case.id})
        rec.state = "partial" if partial else "received"
        if case.delivery_method == "store_pickup" and not partial:
            rec.state = "pickup_ready"
        return rec

    def action_notify_pickup_once(self):
        from odoo.addons.petspot_fulfillment_vetution.services.chatwoot_transport import (
            ChatwootTransport,
        )

        for rec in self:
            if rec.pickup_notified:
                continue
            inquiry = rec.case_id.inquiry_id
            if not inquiry:
                continue
            ChatwootTransport(self.env, force_mock=True).send_template(
                inquiry=inquiry,
                template_code="ready_for_pickup",
                idempotency_key=f"pickup-ready/{rec.case_id.id}",
            )
            rec.pickup_notified = True

    def action_confirm_handover(self):
        for rec in self:
            if rec.case_id.delivery_method != "store_pickup":
                raise UserError("Handover confirmation is for store pickup only.")
            # No AWB for pickup
            mock = self.env["petspot.vetution.shipblu.mock.awb"].search(
                [("case_id", "=", rec.case_id.id)], limit=1
            )
            if mock and mock.state not in ("blocked", "cancelled"):
                raise UserError("Pickup path must not have an active AWB.")
            rec.state = "handed_over"
            if hasattr(rec.case_id, "action_transition"):
                try:
                    rec.case_id.action_transition("completed", source="giza_handover")
                except Exception:  # noqa: BLE001
                    pass
