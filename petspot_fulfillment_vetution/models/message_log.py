# -*- coding: utf-8 -*-
"""Idempotent customer message send log (mock transport by default)."""

from __future__ import annotations

import hashlib
import json

from odoo import fields, models


class PetspotVetutionMessageLog(models.Model):
    _name = "petspot.vetution.message.log"
    _description = "Vetution Message Send Log (idempotent)"
    _inherit = ["mail.thread"]
    _order = "id desc"

    name = fields.Char(required=True, default="MSG")
    inquiry_id = fields.Many2one(
        "petspot.availability.inquiry", ondelete="cascade", index=True
    )
    case_id = fields.Many2one("petspot.fulfillment.case", index=True)
    template_key = fields.Char(required=True, index=True)
    lang = fields.Selection([("en", "English"), ("ar", "Arabic")], required=True)
    channel = fields.Selection([("chatwoot", "Chatwoot")], default="chatwoot", required=True)
    transport = fields.Selection(
        [("mock", "Mock"), ("live", "Live")], default="mock", required=True
    )
    body_text = fields.Text()
    payload_hash = fields.Char(required=True, index=True)
    idempotency_key = fields.Char(required=True, index=True)
    external_message_id = fields.Char(help="Mock or live transport correlation id.")
    state = fields.Selection(
        [("sent", "Sent"), ("failed", "Failed"), ("skipped_duplicate", "Skipped (duplicate)")],
        default="sent",
        required=True,
    )
    error = fields.Char()
    sent_at = fields.Datetime(default=fields.Datetime.now)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company
    )

    _sql_constraints = [
        (
            "petspot_msg_log_idem_uniq",
            "unique(idempotency_key)",
            "A message with this idempotency key was already sent.",
        ),
    ]

    @staticmethod
    def build_idempotency_key(inquiry_id, template_key, payload_hash):
        return f"{inquiry_id}:{template_key}:{payload_hash}"

    @staticmethod
    def hash_payload(context_dict):
        return hashlib.sha256(
            json.dumps(context_dict or {}, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()[:32]
