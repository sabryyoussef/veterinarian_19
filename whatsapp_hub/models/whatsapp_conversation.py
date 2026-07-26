# -*- coding: utf-8 -*-
"""Canonical WhatsApp conversations with deterministic identity resolution."""
from __future__ import annotations

import hashlib
import re

from odoo import api, fields, models

CONVERSATION_PURPOSE = [
    ("crm", "CRM / Partner"),
    ("discuss", "Discuss WA"),
    ("campaign", "Campaign"),
    ("clinic", "Clinic"),
    ("developer", "Developer"),
    ("chatwoot", "Chatwoot"),
    ("other", "Other"),
]


def _normalize_remote_jid(value):
    """Normalize phone or JID into a stable remote identity string."""
    raw = (value or "").strip()
    if not raw:
        return False
    if "@" in raw:
        local, _, domain = raw.partition("@")
        digits = re.sub(r"\D", "", local) or local
        domain = domain.strip().lower()
        if domain in ("g.us", "s.whatsapp.net", "c.us", "lid"):
            if domain == "c.us":
                domain = "s.whatsapp.net"
            return f"{digits}@{domain}"
        return f"{digits}@{domain}" if digits else raw
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return False
    return f"{digits}@s.whatsapp.net"


def _instance_key(instance_id=None, instance_reference=None):
    if instance_id:
        return f"id:{int(instance_id)}"
    ref = (instance_reference or "").strip()
    if ref:
        return f"ref:{ref}"
    return "default"


def build_conversation_identity_key(
    *,
    instance_id=None,
    instance_reference=None,
    remote_jid=None,
    purpose="other",
):
    """
    Canonical conversation identity:

        instance_key + remote_jid + purpose
    """
    remote = _normalize_remote_jid(remote_jid) or ""
    purpose_key = (purpose or "other").strip() or "other"
    raw = "|".join(
        [
            _instance_key(instance_id, instance_reference),
            remote,
            purpose_key,
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


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
    instance_id = fields.Many2one("whatsapp.instance", ondelete="set null", index=True)
    instance_reference = fields.Char(index=True)
    remote_jid = fields.Char(
        index=True,
        help="Normalized peer JID (@g.us or @s.whatsapp.net) for identity.",
    )
    purpose = fields.Selection(
        CONVERSATION_PURPOSE,
        default="other",
        required=True,
        index=True,
        help="Business context — keeps CRM/campaign/clinic threads distinct.",
    )
    identity_key = fields.Char(
        index=True,
        help="SHA256(instance_key|remote_jid|purpose) — stable conversation identity.",
    )
    partner_id = fields.Many2one("res.partner", ondelete="set null", index=True)
    chatwoot_account_id = fields.Integer(index=True)
    chatwoot_inbox_id = fields.Integer(index=True)
    chatwoot_conversation_id = fields.Integer(index=True)
    last_message_at = fields.Datetime()
    message_ids = fields.One2many("whatsapp.message", "conversation_id")

    def action_open_chat(self):
        """Open OWL Conversation Chat client action for this conversation."""
        self.ensure_one()
        return {
            "type": "ir.actions.client",
            "tag": "whatsapp_hub_conversation_chat",
            "name": self.name or "Chat",
            "target": "current",
            "context": {
                "active_id": self.id,
                "active_model": "whatsapp.conversation",
                "conversation_id": self.id,
                "focus_message_id": self.env.context.get("focus_message_id") or False,
            },
        }

    def get_thread_messages(
        self,
        offset=0,
        limit=50,
        hide_noise=True,
        show_hidden=False,
        media_filter="all",
        before_id=None,
        focus_message_id=None,
    ):
        """
        Return chronological thread slice for the OWL chat UI.

        Newest page by default (offset from end). Use before_id to load older.
        media_filter: all | text | media
        """
        self.ensure_one()
        Message = self.env["whatsapp.message"]
        domain = [("conversation_id", "=", self.id)]
        if hide_noise:
            domain = domain + ["!"] + Message._noise_domain()
        if not show_hidden:
            domain.append(("is_hidden", "=", False))
        if media_filter == "text":
            domain.append(("has_media", "=", False))
            domain.append(("media_kind", "=", "none"))
        elif media_filter == "media":
            domain.append(("has_media", "=", True))

        total = Message.search_count(domain)
        order = "message_timestamp asc, id asc"
        messages = Message.browse()
        focus_id = int(focus_message_id or 0) or False

        if before_id:
            pivot = Message.browse(int(before_id))
            if pivot.exists() and pivot.conversation_id.id == self.id:
                older_domain = domain + [
                    "|",
                    ("message_timestamp", "<", pivot.message_timestamp),
                    "&",
                    ("message_timestamp", "=", pivot.message_timestamp),
                    ("id", "<", pivot.id),
                ]
                # fetch older page then keep ascending for UI
                older = Message.search(
                    older_domain,
                    order="message_timestamp desc, id desc",
                    limit=int(limit) or 50,
                )
                messages = older.sorted(
                    key=lambda m: (m.message_timestamp or fields.Datetime.from_string("1970-01-01"), m.id)
                )
        else:
            # First load: last N messages (newest page), returned ascending
            limit = int(limit) or 50
            offset = int(offset) or 0
            newest = Message.search(
                domain,
                order="message_timestamp desc, id desc",
                limit=limit,
                offset=offset,
            )
            messages = newest.sorted(
                key=lambda m: (m.message_timestamp or fields.Datetime.from_string("1970-01-01"), m.id)
            )
            if focus_id:
                focus = Message.browse(focus_id)
                if focus.exists() and focus.conversation_id.id == self.id:
                    if focus_id not in messages.ids:
                        # Expand window around focus
                        around = Message.search(
                            domain
                            + [
                                "|",
                                ("message_timestamp", "<=", focus.message_timestamp),
                                "&",
                                ("message_timestamp", "=", focus.message_timestamp),
                                ("id", "<=", focus.id),
                            ],
                            order="message_timestamp desc, id desc",
                            limit=limit,
                        )
                        messages = around.sorted(
                            key=lambda m: (
                                m.message_timestamp
                                or fields.Datetime.from_string("1970-01-01"),
                                m.id,
                            )
                        )

        has_older = False
        if messages:
            first = messages[0]
            older_count = Message.search_count(
                domain
                + [
                    "|",
                    ("message_timestamp", "<", first.message_timestamp),
                    "&",
                    ("message_timestamp", "=", first.message_timestamp),
                    ("id", "<", first.id),
                ]
            )
            has_older = older_count > 0

        return {
            "conversation_id": self.id,
            "conversation_name": self.name,
            "conversation_type": self.conversation_type,
            "remote_jid": self.remote_jid or False,
            "group_id": self.group_id.id if self.group_id else False,
            "group_name": self.group_id.name if self.group_id else False,
            "total": total,
            "has_older": has_older,
            "focus_message_id": focus_id,
            "messages": [m._thread_payload() for m in messages],
        }

    _identity_unique = models.UniqueIndex(
        "(identity_key) WHERE identity_key IS NOT NULL",
        "WhatsApp conversation identity must be unique.",
    )

    @api.model
    def normalize_remote_jid(self, value):
        return _normalize_remote_jid(value)

    @api.model
    def resolve_conversation(
        self,
        *,
        remote_jid=None,
        purpose="other",
        instance_id=False,
        instance_reference=False,
        conversation_type=None,
        group=None,
        contact=None,
        partner=None,
        name=None,
        chatwoot_account_id=0,
        chatwoot_inbox_id=0,
        chatwoot_conversation_id=0,
    ):
        """
        Deterministic conversation resolver reusable by ingest, mirror, and outbound.

        Priority:
        1. Chatwoot account+conversation id (platform inbox thread)
        2. identity_key = instance + remote_jid + purpose
        """
        account = int(chatwoot_account_id or 0)
        conv_id = int(chatwoot_conversation_id or 0)
        inbox = int(chatwoot_inbox_id or 0)
        if account and conv_id:
            existing = self.search(
                [
                    ("chatwoot_account_id", "=", account),
                    ("chatwoot_conversation_id", "=", conv_id),
                ],
                limit=1,
            )
            if existing:
                updates = {}
                if remote_jid and not existing.remote_jid:
                    updates["remote_jid"] = _normalize_remote_jid(remote_jid)
                if instance_id and not existing.instance_id:
                    updates["instance_id"] = int(instance_id)
                if instance_reference and not existing.instance_reference:
                    updates["instance_reference"] = instance_reference
                if purpose and existing.purpose == "other" and purpose != "other":
                    updates["purpose"] = purpose
                if updates:
                    existing.write(updates)
                return existing

        remote = _normalize_remote_jid(remote_jid)
        if group and not remote:
            remote = _normalize_remote_jid(group.jid)
        purpose_key = purpose or "other"
        identity = build_conversation_identity_key(
            instance_id=instance_id,
            instance_reference=instance_reference,
            remote_jid=remote,
            purpose=purpose_key,
        )
        existing = self.search([("identity_key", "=", identity)], limit=1)
        if existing:
            updates = {}
            if contact and not existing.contact_id:
                updates["contact_id"] = contact.id
            if partner and not existing.partner_id:
                updates["partner_id"] = (
                    partner.id if hasattr(partner, "id") else int(partner)
                )
            if group and not existing.group_id:
                updates["group_id"] = group.id
            if updates:
                existing.write(updates)
            return existing

        if conversation_type is None:
            conversation_type = (
                "group"
                if (group or (remote and str(remote).endswith("@g.us")))
                else "dm"
            )
        display = (
            name
            or (group.name if group else False)
            or (contact.name if contact else False)
            or (
                partner.name
                if partner is not None and hasattr(partner, "name")
                else False
            )
            or remote
            or f"CW-{conv_id or 'new'}"
        )
        vals = {
            "name": display,
            "conversation_type": conversation_type,
            "group_id": group.id if group else False,
            "contact_id": contact.id if contact else False,
            "partner_id": (
                partner.id
                if partner is not None and hasattr(partner, "id")
                else (int(partner) if partner else False)
            ),
            "instance_id": int(instance_id) if instance_id else False,
            "instance_reference": (instance_reference or "").strip() or False,
            "remote_jid": remote or False,
            "purpose": purpose_key,
            "identity_key": identity if remote else False,
            "chatwoot_account_id": account or False,
            "chatwoot_inbox_id": inbox or False,
            "chatwoot_conversation_id": conv_id or False,
            "last_message_at": fields.Datetime.now(),
        }
        return self.create(vals)

    @api.model
    def find_or_create_from_payload(self, payload, group=None, contact=None):
        """Compat wrapper used by Hub ingest — delegates to resolve_conversation."""
        instance_ref = (payload.get("instance_reference") or payload.get("evolution_instance") or "").strip()
        instance = self.env["whatsapp.instance"].browse()
        if instance_ref:
            instance = self.env["whatsapp.instance"].sudo().search(
                [("instance_name", "=", instance_ref)], limit=1
            )
        remote = (
            payload.get("group_jid")
            or payload.get("remote_jid")
            or payload.get("sender_jid")
            or payload.get("sender")
        )
        return self.resolve_conversation(
            remote_jid=remote,
            purpose="chatwoot",
            instance_id=instance.id if instance else False,
            instance_reference=instance_ref or False,
            group=group,
            contact=contact,
            name=(
                (group.name if group else False)
                or (contact.name if contact else False)
                or payload.get("group_name")
            ),
            chatwoot_account_id=int(
                payload.get("chatwoot_account_id") or payload.get("account_id") or 0
            ),
            chatwoot_inbox_id=int(
                payload.get("chatwoot_inbox_id") or payload.get("inbox_id") or 0
            ),
            chatwoot_conversation_id=int(
                payload.get("chatwoot_conversation_id")
                or payload.get("conversation_id")
                or 0
            ),
        )
