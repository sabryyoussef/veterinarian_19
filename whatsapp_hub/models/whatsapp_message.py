# -*- coding: utf-8 -*-
"""Canonical WhatsApp message store + normalized ingest RPC."""
from __future__ import annotations

import hashlib
import json
import logging

from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError

_logger = logging.getLogger(__name__)


def _require_ingest_service(env):
    if env.is_superuser():
        return
    if env.user.has_group("whatsapp_hub.group_whatsapp_ingest_service"):
        return
    # Also allow Dev Hub intake service when that module is installed
    try:
        if env.ref(
            "devhub_whatsapp.group_dev_hub_whatsapp_intake", raise_if_not_found=False
        ) and env.user.has_group("devhub_whatsapp.group_dev_hub_whatsapp_intake"):
            return
    except Exception:
        pass
    raise AccessError(
        "This operation requires the WhatsApp Hub Ingest Service role."
    )


def _clean(value, limit=6000):
    text = (value or "").strip() if isinstance(value, str) else str(value or "").strip()
    if len(text) > limit:
        text = text[: limit - 20] + "\n...[truncated]..."
    return text


def _dedupe_key(payload):
    """Stable idempotency key.

    Prefer Chatwoot message id when present so later enrichment with an
    Evolution id does not create a second hub row for the same Chatwoot event.
    """
    chatwoot_message_id = payload.get("chatwoot_message_id") or payload.get("message_id")
    evolution_message_id = payload.get("evolution_message_id") or payload.get(
        "provider_message_id"
    )
    account = int(payload.get("chatwoot_account_id") or payload.get("account_id") or 0)
    group = _clean(payload.get("group_jid"), 80)
    if chatwoot_message_id:
        raw = json.dumps(
            {
                "account": account,
                "cw_msg": str(chatwoot_message_id),
                "group": group,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    else:
        raw = json.dumps(
            {
                "account": account,
                "cw_msg": "",
                "evo_msg": str(evolution_message_id or ""),
                "group": group,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class WhatsappMessage(models.Model):
    _name = "whatsapp.message"
    _description = "WhatsApp Message"
    _order = "message_timestamp desc, id desc"
    _rec_name = "display_name"

    display_name = fields.Char(compute="_compute_display_name", store=False)
    direction = fields.Selection(
        [("in", "Inbound"), ("out", "Outbound")],
        required=True,
        index=True,
        default="in",
    )
    state = fields.Selection(
        [
            ("received", "Received"),
            ("queued", "Queued"),
            ("sent", "Sent"),
            ("delivered", "Delivered"),
            ("read", "Read"),
            ("failed", "Failed"),
        ],
        default="received",
        required=True,
        index=True,
    )
    delivery_state = fields.Selection(
        [
            ("pending", "Pending"),
            ("sent", "Sent"),
            ("delivered", "Delivered"),
            ("read", "Read"),
            ("failed", "Failed"),
        ],
        default="pending",
        index=True,
    )
    body = fields.Text()
    message_timestamp = fields.Datetime(default=fields.Datetime.now, index=True)
    conversation_id = fields.Many2one(
        "whatsapp.conversation", required=True, ondelete="cascade", index=True
    )
    group_id = fields.Many2one("whatsapp.group", ondelete="set null", index=True)
    contact_id = fields.Many2one("whatsapp.contact", ondelete="set null", index=True)
    instance_id = fields.Many2one("whatsapp.instance", ondelete="set null")
    reply_to_id = fields.Many2one("whatsapp.message", ondelete="set null")

    # External IDs
    dedupe_key = fields.Char(required=True, index=True)
    evolution_message_id = fields.Char(index=True)
    chatwoot_account_id = fields.Integer(index=True)
    chatwoot_inbox_id = fields.Integer(index=True)
    chatwoot_conversation_id = fields.Integer(index=True)
    chatwoot_message_id = fields.Integer(index=True)
    provider = fields.Selection(
        [("chatwoot", "Chatwoot"), ("evolution", "Evolution"), ("other", "Other")],
        default="chatwoot",
        index=True,
    )
    provider_message_id = fields.Char(index=True)
    instance_reference = fields.Char()
    group_jid = fields.Char(index=True)
    sender_jid = fields.Char(index=True)
    attachment_references = fields.Text()
    raw_payload = fields.Text()
    # Legacy bridge to wa.message.log
    wa_message_log_id = fields.Integer(index=True)

    _dedupe_unique = models.Constraint(
        "unique(dedupe_key)",
        "Duplicate WhatsApp message (dedupe_key).",
    )

    @api.depends("direction", "group_jid", "sender_jid", "body")
    def _compute_display_name(self):
        for rec in self:
            arrow = "←" if rec.direction == "in" else "→"
            who = rec.sender_jid or rec.group_jid or "?"
            snippet = (rec.body or "")[:40]
            rec.display_name = f"{arrow} {who}: {snippet}"

    def _on_message_ingested(self):
        """Extension hook for consumers (override / inherit)."""
        self.ensure_one()
        self.env["whatsapp.message.event"].sudo().create(
            {
                "message_id": self.id,
                "event_type": "ingested",
                "payload_snapshot": self.raw_payload or "",
            }
        )

    def _on_outbound_sent(self):
        self.ensure_one()
        self.env["whatsapp.message.event"].sudo().create(
            {
                "message_id": self.id,
                "event_type": "outbound_sent",
            }
        )

    @api.model
    def service_ingest_normalized(self, payload):
        """
        Canonical Chatwoot-normalized WhatsApp ingress.

        Idempotent on dedupe_key derived from Chatwoot/Evolution message ids + group.
        Returns: {message_id, conversation_id, group_id, contact_id, duplicate}
        """
        _require_ingest_service(self.env)
        if not isinstance(payload, dict):
            raise ValidationError("payload must be an object.")

        group_jid = _clean(payload.get("group_jid"), 80)
        text = _clean(
            payload.get("text")
            or payload.get("content")
            or payload.get("body")
            or payload.get("message_text")
        )
        chatwoot_message_id = payload.get("chatwoot_message_id") or payload.get("message_id")
        evolution_message_id = _clean(
            payload.get("evolution_message_id") or payload.get("provider_message_id"), 300
        )
        if not chatwoot_message_id and not evolution_message_id:
            raise ValidationError(
                "chatwoot_message_id or evolution_message_id is required."
            )
        if not text and not payload.get("allow_empty"):
            return {"skipped": True, "reason": "empty_text"}

        dedupe = _dedupe_key(payload)
        existing = self.sudo().search([("dedupe_key", "=", dedupe)], limit=1)
        if not existing and chatwoot_message_id:
            # Secondary lookup: same Chatwoot message may have been stored under
            # an older dedupe scheme that included a missing Evolution id.
            existing = self.sudo().search(
                [("chatwoot_message_id", "=", int(chatwoot_message_id))], limit=1
            )
        if existing:
            # Enrich optional Evolution id when a later normalized event carries it
            # (Chatwoot id remains the primary idempotency key).
            if evolution_message_id and not existing.evolution_message_id:
                existing.sudo().write({"evolution_message_id": evolution_message_id})
            return {
                "message_id": existing.id,
                "conversation_id": existing.conversation_id.id,
                "group_id": existing.group_id.id or False,
                "contact_id": existing.contact_id.id or False,
                "duplicate": True,
                "skipped": True,
                "reason": "duplicate_message",
            }

        group = self.env["whatsapp.group"].sudo().browse()
        if group_jid:
            group = self.env["whatsapp.group"].sudo().get_or_create_by_jid(
                group_jid,
                {
                    "name": payload.get("group_name") or group_jid,
                    "chatwoot_inbox_id": int(
                        payload.get("chatwoot_inbox_id") or payload.get("inbox_id") or 0
                    )
                    or False,
                },
            )

        sender_jid = _clean(payload.get("sender_jid") or payload.get("sender"), 120)
        contact = (
            self.env["whatsapp.contact"]
            .sudo()
            .get_or_create_from_sender(
                sender_jid=sender_jid,
                phone=payload.get("sender_phone"),
                name=payload.get("sender_name") or payload.get("push_name"),
            )
        )

        conversation = (
            self.env["whatsapp.conversation"]
            .sudo()
            .find_or_create_from_payload(payload, group=group, contact=contact)
        )

        provider = "chatwoot" if chatwoot_message_id else "evolution"
        provider_message_id = str(chatwoot_message_id or evolution_message_id)
        ts = payload.get("message_timestamp") or fields.Datetime.now()

        reply_to = self.browse()
        quoted = payload.get("reply_to_chatwoot_message_id") or payload.get(
            "quoted_message_id"
        )
        if quoted:
            reply_to = self.sudo().search(
                [("chatwoot_message_id", "=", int(quoted))], limit=1
            )

        instance_ref = _clean(
            payload.get("instance_reference") or payload.get("evolution_instance"), 200
        )
        instance = self.env["whatsapp.instance"].sudo().browse()
        if instance_ref:
            instance = self.env["whatsapp.instance"].sudo().search(
                [("instance_name", "=", instance_ref)], limit=1
            )

        message = self.sudo().create(
            {
                "direction": "in",
                "state": "received",
                "delivery_state": "delivered",
                "body": text or "",
                "message_timestamp": ts,
                "conversation_id": conversation.id,
                "group_id": group.id if group else False,
                "contact_id": contact.id if contact else False,
                "instance_id": instance.id if instance else False,
                "reply_to_id": reply_to.id if reply_to else False,
                "dedupe_key": dedupe,
                "evolution_message_id": evolution_message_id or False,
                "chatwoot_account_id": int(
                    payload.get("chatwoot_account_id") or payload.get("account_id") or 0
                )
                or False,
                "chatwoot_inbox_id": int(
                    payload.get("chatwoot_inbox_id") or payload.get("inbox_id") or 0
                )
                or False,
                "chatwoot_conversation_id": int(
                    payload.get("chatwoot_conversation_id")
                    or payload.get("conversation_id")
                    or 0
                )
                or False,
                "chatwoot_message_id": int(chatwoot_message_id or 0) or False,
                "provider": provider,
                "provider_message_id": provider_message_id,
                "instance_reference": instance_ref or False,
                "group_jid": group_jid or False,
                "sender_jid": sender_jid or False,
                "attachment_references": _clean(
                    payload.get("attachment_references"), 4000
                )
                or False,
                "raw_payload": json.dumps(payload, ensure_ascii=False, default=str),
            }
        )
        conversation.write({"last_message_at": ts})
        message._on_message_ingested()
        _logger.info(
            "whatsapp_hub ingested message id=%s group=%s cw_msg=%s",
            message.id,
            group_jid,
            chatwoot_message_id,
        )
        return {
            "message_id": message.id,
            "conversation_id": conversation.id,
            "group_id": group.id if group else False,
            "contact_id": contact.id if contact else False,
            "duplicate": False,
            "skipped": False,
        }

    @api.model
    def update_delivery_status(self, evolution_message_id, status):
        """Map Evolution delivery webhook status onto hub messages."""
        mapping = {
            "PENDING": "pending",
            "SERVER_ACK": "sent",
            "SENT": "sent",
            "DELIVERY_ACK": "delivered",
            "DELIVERED": "delivered",
            "READ": "read",
            "PLAYED": "read",
            "ERROR": "failed",
            "FAILED": "failed",
        }
        key = (status or "").upper()
        delivery = mapping.get(key, False)
        if not delivery or not evolution_message_id:
            return False
        messages = self.sudo().search(
            [("evolution_message_id", "=", evolution_message_id)]
        )
        if not messages:
            return False
        vals = {"delivery_state": delivery}
        if delivery in ("sent", "delivered", "read", "failed"):
            vals["state"] = delivery if delivery != "pending" else "sent"
        messages.write(vals)
        return True
