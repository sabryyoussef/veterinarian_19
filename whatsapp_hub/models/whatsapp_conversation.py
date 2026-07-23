# -*- coding: utf-8 -*-
from odoo import api, fields, models


class WhatsappConversation(models.Model):
    _name = "whatsapp.conversation"
    _description = "WhatsApp Conversation"
    _order = "last_message_at desc, id desc"

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    conversation_type = fields.Selection(
        [("group", "Group"), ("dm", "Direct")],
        default="group",
        required=True,
        index=True,
    )
    group_id = fields.Many2one("whatsapp.group", ondelete="set null", index=True)
    contact_id = fields.Many2one("whatsapp.contact", ondelete="set null", index=True)
    instance_id = fields.Many2one("whatsapp.instance", ondelete="set null")
    chatwoot_account_id = fields.Integer(index=True)
    chatwoot_inbox_id = fields.Integer(index=True)
    chatwoot_conversation_id = fields.Integer(index=True)
    last_message_at = fields.Datetime()
    message_ids = fields.One2many("whatsapp.message", "conversation_id")

    @api.model
    def find_or_create_from_payload(self, payload, group=None, contact=None):
        account = int(payload.get("chatwoot_account_id") or payload.get("account_id") or 0)
        conv_id = int(
            payload.get("chatwoot_conversation_id") or payload.get("conversation_id") or 0
        )
        inbox = int(payload.get("chatwoot_inbox_id") or payload.get("inbox_id") or 0)
        if account and conv_id:
            existing = self.search(
                [
                    ("chatwoot_account_id", "=", account),
                    ("chatwoot_conversation_id", "=", conv_id),
                ],
                limit=1,
            )
            if existing:
                return existing
        group_jid = (payload.get("group_jid") or "").strip()
        if group and group_jid:
            existing = self.search(
                [("group_id", "=", group.id), ("conversation_type", "=", "group")],
                order="id desc",
                limit=1,
            )
            if existing and not conv_id:
                return existing
        name = (
            (group.name if group else False)
            or (contact.name if contact else False)
            or group_jid
            or f"CW-{conv_id or 'new'}"
        )
        return self.create(
            {
                "name": name,
                "conversation_type": "group" if group else "dm",
                "group_id": group.id if group else False,
                "contact_id": contact.id if contact else False,
                "chatwoot_account_id": account or False,
                "chatwoot_inbox_id": inbox or False,
                "chatwoot_conversation_id": conv_id or False,
                "last_message_at": fields.Datetime.now(),
            }
        )
