# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


class PetspotWaMarketingQueueItem(models.Model):
    _name = "petspot.wa.marketing.queue.item"
    _description = "WhatsApp Marketing Queue Item"
    _order = "scheduled_at, id"

    campaign_id = fields.Many2one(
        "petspot.wa.marketing.campaign", required=True, index=True, ondelete="cascade"
    )
    partner_id = fields.Many2one("res.partner", required=True, index=True, ondelete="restrict")
    mobile_normalized = fields.Char(required=True, index=True)
    template_id = fields.Many2one("petspot.wa.marketing.template", required=True)
    template_version = fields.Char(required=True, index=True)
    idempotency_key = fields.Char(required=True, index=True)
    rendered_body = fields.Text(required=True)
    state = fields.Selection(
        [
            ("pending", "Pending"),
            ("reserved", "Reserved"),
            ("sent", "Sent"),
            ("failed", "Failed"),
            ("cancelled", "Cancelled"),
            ("skipped", "Skipped"),
            ("uncertain", "Uncertain"),
        ],
        default="pending",
        required=True,
        index=True,
    )
    scheduled_at = fields.Datetime(required=True, index=True)
    sent_at = fields.Datetime()
    evolution_message_id = fields.Char()
    skip_reason = fields.Char()
    last_error = fields.Char()

    _idempotency_unique = models.Constraint(
        "UNIQUE(idempotency_key)",
        "Duplicate marketing queue idempotency key.",
    )

    @api.model
    def build_idempotency_key(self, campaign_id, template_version, partner_id, mobile):
        return f"{campaign_id}:{template_version}:{partner_id}:{mobile}"

    def action_cancel(self, reason=""):
        for item in self:
            if item.state in ("sent", "uncertain"):
                continue
            item.state = "cancelled"
            item.skip_reason = reason or "cancelled"
            self.env["petspot.wa.marketing.event"].sudo().create(
                {
                    "event_type": "campaign_cancel",
                    "campaign_id": item.campaign_id.id,
                    "queue_item_id": item.id,
                    "partner_id": item.partner_id.id,
                    "mobile_normalized": item.mobile_normalized,
                    "note": reason or "cancelled",
                }
            )
