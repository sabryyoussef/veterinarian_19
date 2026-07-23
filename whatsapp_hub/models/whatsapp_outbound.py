# -*- coding: utf-8 -*-
"""WhatsApp-specific outbound queue."""
from __future__ import annotations

import json
import logging
from datetime import timedelta
from urllib.parse import quote

import requests

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

_logger = logging.getLogger(__name__)


class WhatsappOutboundMessage(models.Model):
    _name = "whatsapp.outbound.message"
    _description = "WhatsApp Outbound Queue"
    _order = "priority desc, id asc"

    name = fields.Char(required=True)
    state = fields.Selection(
        [
            ("pending", "Pending"),
            ("sent", "Sent"),
            ("failed", "Failed"),
            ("cancelled", "Cancelled"),
        ],
        default="pending",
        required=True,
        index=True,
    )
    priority = fields.Integer(default=5)
    destination = fields.Char(
        required=True,
        help="Phone digits or full @g.us / @s.whatsapp.net JID",
    )
    body = fields.Text(required=True)
    instance_id = fields.Many2one("whatsapp.instance", ondelete="set null")
    purpose = fields.Selection(
        [
            ("clinic", "Clinic"),
            ("developer", "Developer"),
            ("other", "Other"),
        ],
        default="other",
    )
    message_id = fields.Many2one("whatsapp.message", ondelete="set null")
    conversation_id = fields.Many2one("whatsapp.conversation", ondelete="set null")
    related_model = fields.Char()
    related_res_id = fields.Integer()
    retry_count = fields.Integer(default=0)
    max_retries = fields.Integer(default=3)
    error_message = fields.Text()
    sent_at = fields.Datetime()
    next_retry_at = fields.Datetime()
    response_data = fields.Text()
    evolution_message_id = fields.Char(index=True)

    def _require_send_access(self):
        if self.env.is_superuser():
            return
        if not (
            self.env.user.has_group("whatsapp_hub.group_whatsapp_manager")
            or self.env.user.has_group("whatsapp_hub.group_whatsapp_user")
        ):
            raise AccessError("WhatsApp send requires WhatsApp Hub user access.")

    @api.model
    def service_queue_outbound(self, vals):
        """
        Queue an outbound WhatsApp message.

        vals: destination, body, purpose?, instance_id?, related_model?, related_res_id?,
              conversation_id?, send_now?
        """
        self._require_send_access()
        if not isinstance(vals, dict):
            raise ValidationError("vals must be an object.")
        destination = (vals.get("destination") or "").strip()
        body = (vals.get("body") or vals.get("text") or "").strip()
        if not destination or not body:
            raise ValidationError("destination and body are required.")
        purpose = vals.get("purpose") or "other"
        instance = self.env["whatsapp.instance"].browse()
        if vals.get("instance_id"):
            instance = self.env["whatsapp.instance"].browse(int(vals["instance_id"]))
        name = vals.get("name") or f"WA → {destination[:40]}"
        outbound = self.create(
            {
                "name": name,
                "destination": destination,
                "body": body,
                "purpose": purpose,
                "instance_id": instance.id if instance else False,
                "related_model": vals.get("related_model") or False,
                "related_res_id": int(vals.get("related_res_id") or 0) or False,
                "conversation_id": int(vals.get("conversation_id") or 0) or False,
                "priority": int(vals.get("priority") or 5),
            }
        )
        # Create linked whatsapp.message (outbound) for canonical store
        Message = self.env["whatsapp.message"].sudo()
        conversation = outbound.conversation_id
        if not conversation:
            # Minimal DM conversation stub
            contact = (
                self.env["whatsapp.contact"]
                .sudo()
                .get_or_create_from_sender(phone=destination)
            )
            conversation = self.env["whatsapp.conversation"].sudo().create(
                {
                    "name": f"Outbound {destination}",
                    "conversation_type": "dm"
                    if not destination.endswith("@g.us")
                    else "group",
                    "contact_id": contact.id,
                }
            )
            outbound.conversation_id = conversation
        dedupe = hashlib_sha(
            f"out:{outbound.id}:{destination}:{body[:80]}"
        )
        msg = Message.create(
            {
                "direction": "out",
                "state": "queued",
                "delivery_state": "pending",
                "body": body,
                "conversation_id": conversation.id,
                "contact_id": conversation.contact_id.id,
                "group_id": conversation.group_id.id,
                "dedupe_key": dedupe,
                "provider": "evolution",
                "provider_message_id": f"outbound-{outbound.id}",
                "group_jid": destination if destination.endswith("@g.us") else False,
                "sender_jid": False,
            }
        )
        outbound.message_id = msg
        if vals.get("send_now"):
            outbound.action_send()
        return {
            "outbound_id": outbound.id,
            "message_id": msg.id,
            "state": outbound.state,
        }

    def action_send(self):
        for rec in self:
            rec._send_one()
        return True

    def _send_one(self):
        self.ensure_one()
        if self.state == "sent":
            return True
        cfg = (
            self.instance_id.get_config_dict()
            if self.instance_id
            else self.env["whatsapp.instance"].get_config_for_purpose(self.purpose)
        )
        url = (cfg.get("url") or "").rstrip("/")
        key = cfg.get("key") or ""
        instance = cfg.get("instance") or ""
        if not url or not key or not instance:
            self.write(
                {
                    "state": "failed",
                    "error_message": "Evolution instance not configured",
                }
            )
            return False
        endpoint = f"{url}/message/sendText/{quote(instance, safe='')}"
        try:
            resp = requests.post(
                endpoint,
                headers={"apikey": key, "Content-Type": "application/json"},
                json={"number": self.destination, "text": self.body},
                timeout=20,
            )
            evo_id = ""
            try:
                data = resp.json()
                evo_id = (
                    (data.get("key") or {}).get("id")
                    or data.get("messageId")
                    or ""
                )
            except Exception:
                data = {"raw": resp.text[:2000]}
            if resp.status_code >= 400:
                self._mark_retry(f"HTTP {resp.status_code}: {resp.text[:500]}")
                return False
            self.write(
                {
                    "state": "sent",
                    "sent_at": fields.Datetime.now(),
                    "error_message": False,
                    "response_data": json.dumps(data, default=str)[:8000],
                    "evolution_message_id": evo_id or False,
                }
            )
            if self.message_id:
                self.message_id.write(
                    {
                        "state": "sent",
                        "delivery_state": "sent",
                        "evolution_message_id": evo_id or False,
                    }
                )
                self.message_id._on_outbound_sent()
            return True
        except Exception as exc:
            self._mark_retry(str(exc))
            return False

    def _mark_retry(self, error):
        self.ensure_one()
        retries = self.retry_count + 1
        vals = {
            "retry_count": retries,
            "error_message": error,
            "next_retry_at": fields.Datetime.now() + timedelta(minutes=5 * retries),
        }
        if retries >= self.max_retries:
            vals["state"] = "failed"
            if self.message_id:
                self.message_id.write({"state": "failed", "delivery_state": "failed"})
        self.write(vals)
        _logger.warning("whatsapp outbound %s failed: %s", self.id, error)

    @api.model
    def process_pending(self, limit=50):
        now = fields.Datetime.now()
        pending = self.search(
            [
                ("state", "=", "pending"),
                "|",
                ("next_retry_at", "=", False),
                ("next_retry_at", "<=", now),
            ],
            limit=limit,
        )
        for rec in pending:
            rec._send_one()
        return len(pending)


def hashlib_sha(value):
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()
