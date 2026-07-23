# -*- coding: utf-8 -*-
"""Compatibility helpers when legacy modules are installed alongside the hub."""
from odoo import api, models


class WhatsappHubCompat(models.AbstractModel):
    _name = "whatsapp.hub.compat"
    _description = "WhatsApp Hub Compatibility Helpers"

    @api.model
    def mirror_wa_message_log(self, wa_log):
        """Best-effort mirror of wa.message.log into whatsapp.message (optional)."""
        if not wa_log or "whatsapp.message" not in self.env:
            return self.env["whatsapp.message"].browse()
        Message = self.env["whatsapp.message"].sudo()
        if wa_log.wa_message_id:
            existing = Message.search(
                [("evolution_message_id", "=", wa_log.wa_message_id)], limit=1
            )
            if existing:
                return existing
        contact = (
            self.env["whatsapp.contact"]
            .sudo()
            .get_or_create_from_sender(
                phone=wa_log.phone,
                name=wa_log.partner_id.name if wa_log.partner_id else None,
            )
        )
        conversation = self.env["whatsapp.conversation"].sudo().create(
            {
                "name": wa_log.partner_id.name or wa_log.phone,
                "conversation_type": "dm",
                "contact_id": contact.id,
            }
        )
        import hashlib

        dedupe = hashlib.sha256(
            f"walog:{wa_log.id}:{wa_log.wa_message_id or wa_log.phone}".encode()
        ).hexdigest()
        return Message.create(
            {
                "direction": wa_log.direction or "out",
                "state": "sent" if wa_log.direction == "out" else "received",
                "delivery_state": wa_log.delivery_status or "pending",
                "body": wa_log.message_text or "",
                "conversation_id": conversation.id,
                "contact_id": contact.id,
                "dedupe_key": dedupe,
                "evolution_message_id": wa_log.wa_message_id or False,
                "provider": "evolution",
                "provider_message_id": wa_log.wa_message_id or f"walog-{wa_log.id}",
                "wa_message_log_id": wa_log.id,
            }
        )
