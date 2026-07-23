# -*- coding: utf-8 -*-
from odoo import fields, models


class WhatsappMessageEvent(models.Model):
    _name = "whatsapp.message.event"
    _description = "WhatsApp Message Event"
    _order = "id desc"

    message_id = fields.Many2one(
        "whatsapp.message", required=True, ondelete="cascade", index=True
    )
    event_type = fields.Selection(
        [
            ("ingested", "Ingested"),
            ("outbound_sent", "Outbound Sent"),
            ("status_update", "Status Update"),
            ("consumer_notified", "Consumer Notified"),
        ],
        required=True,
        index=True,
    )
    payload_snapshot = fields.Text()
    create_date = fields.Datetime(readonly=True)
