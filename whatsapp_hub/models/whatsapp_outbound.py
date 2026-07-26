# -*- coding: utf-8 -*-
"""WhatsApp Hub outbound queue + Phase 3 unified send API.

Retry ownership (Phase 3)
-------------------------
* Hub owns business intent and retries on ``whatsapp.outbound.message``.
* Bridge ``evolution.instance.send_whatsapp_text`` performs a one-shot transport
  execution (no bridge-queue retry for unified jobs).
* Legacy ``service_queue_outbound`` / clinic path still uses Hub direct HTTP
  when not using the unified API — unchanged for Phase 3.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import timedelta
from urllib.parse import quote

import requests

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from .whatsapp_conversation import CONVERSATION_PURPOSE, _normalize_remote_jid
from .whatsapp_message import SOURCE_APP, build_business_key, _clean

_logger = logging.getLogger(__name__)

SUPPORTED_MESSAGE_TYPES = ("text",)
DEFERRED_MESSAGE_TYPES = ("media", "image", "document", "audio", "video", "buttons", "template")

OUTBOUND_PURPOSE = [
    ("clinic", "Clinic"),
    ("developer", "Developer"),
    ("crm", "CRM / Partner"),
    ("campaign", "Campaign"),
    ("discuss", "Discuss"),
    ("other", "Other"),
]


def hashlib_sha(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _icp_bool(env, key, default=False):
    raw = (env["ir.config_parameter"].sudo().get_param(key) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def _icp_csv(env, key):
    raw = (env["ir.config_parameter"].sudo().get_param(key) or "").strip()
    if not raw:
        return []
    return [p.strip() for p in raw.split(",") if p.strip()]


class WhatsappOutboundMessage(models.Model):
    _name = "whatsapp.outbound.message"
    _description = "WhatsApp Outbound Queue"
    _order = "priority desc, id asc"

    name = fields.Char(required=True)
    state = fields.Selection(
        [
            ("pending", "Pending"),
            ("processing", "Processing"),
            ("sent", "Sent"),
            ("failed", "Failed"),
            ("cancelled", "Cancelled"),
        ],
        default="pending",
        required=True,
        index=True,
    )
    transport_mode = fields.Selection(
        [
            ("legacy_direct", "Legacy Hub Direct HTTP"),
            ("unified_bridge", "Unified via Bridge"),
        ],
        default="legacy_direct",
        required=True,
        index=True,
        help="legacy_direct = pre-Phase-3 clinic path; unified_bridge = Phase 3 API.",
    )
    priority = fields.Integer(default=5)
    destination = fields.Char(
        required=True,
        help="Phone digits or full @g.us / @s.whatsapp.net JID",
    )
    body = fields.Text(required=True)
    message_type = fields.Selection(
        [
            ("text", "Text"),
            ("media", "Media (deferred)"),
            ("buttons", "Buttons (deferred)"),
            ("template", "Template (deferred)"),
        ],
        default="text",
        required=True,
    )
    instance_id = fields.Many2one("whatsapp.instance", ondelete="set null")
    purpose = fields.Selection(OUTBOUND_PURPOSE, default="other")
    message_id = fields.Many2one("whatsapp.message", ondelete="set null", index=True)
    conversation_id = fields.Many2one("whatsapp.conversation", ondelete="set null")
    related_model = fields.Char(index=True)
    related_res_id = fields.Integer(index=True)
    client_request_id = fields.Char(index=True)
    business_key = fields.Char(index=True)
    source_app = fields.Selection(SOURCE_APP, default="hub", index=True)
    partner_id = fields.Many2one("res.partner", ondelete="set null", index=True)
    campaign_id = fields.Integer(index=True)
    campaign_line_id = fields.Integer(index=True)
    discuss_channel_id = fields.Integer(index=True)
    bridge_queue_id = fields.Integer(
        index=True,
        help="Optional soft link to integration.outbound.queue (audit only).",
    )
    bridge_instance_id = fields.Integer(
        index=True,
        help="evolution.instance id used for last transport attempt.",
    )
    retry_count = fields.Integer(default=0)
    max_retries = fields.Integer(default=3)
    error_message = fields.Text()
    sent_at = fields.Datetime()
    next_retry_at = fields.Datetime()
    response_data = fields.Text()
    evolution_message_id = fields.Char(index=True)

    _business_key_outbound_unique = models.UniqueIndex(
        "(business_key) WHERE business_key IS NOT NULL",
        "Duplicate Hub outbound job (business_key).",
    )

    def _require_send_access(self):
        if self.env.is_superuser():
            return
        if not (
            self.env.user.has_group("whatsapp_hub.group_whatsapp_manager")
            or self.env.user.has_group("whatsapp_hub.group_whatsapp_user")
        ):
            raise AccessError("WhatsApp send requires WhatsApp Hub user access.")

    # ------------------------------------------------------------------ flags
    @api.model
    def _assert_unified_outbound_enabled(self, purpose, hub_instance):
        if not _icp_bool(self.env, "whatsapp_hub.unified_outbound_enabled", False):
            raise UserError(
                "Unified Hub outbound API is disabled. "
                "Set system parameter whatsapp_hub.unified_outbound_enabled=True "
                "on a Test/UAT database to enable."
            )
        allow = _icp_csv(self.env, "whatsapp_hub.unified_outbound_purposes")
        if allow and purpose and purpose not in allow:
            raise UserError(
                f"Unified Hub outbound is not enabled for purpose={purpose}."
            )
        if hub_instance and not hub_instance.unified_outbound_enabled:
            raise UserError(
                "Unified Hub outbound is disabled on this WhatsApp instance."
            )

    # ----------------------------------------------------------- legacy clinic
    @api.model
    def service_queue_outbound(self, vals):
        """
        Legacy Hub outbound (clinic notify etc.).

        Unchanged Phase-3 behavior: optional direct Evolution HTTP, not gated by
        unified outbound flags, does not cut over Campaign/Discuss.
        """
        self._require_send_access()
        if not isinstance(vals, dict):
            raise ValidationError("vals must be an object.")
        destination = (vals.get("destination") or "").strip()
        body = (vals.get("body") or vals.get("text") or "").strip()
        if not destination or not body:
            raise ValidationError("destination and body are required.")
        purpose = vals.get("purpose") or "other"
        if purpose not in dict(OUTBOUND_PURPOSE):
            purpose = "other"
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
                "transport_mode": "legacy_direct",
                "message_type": "text",
                "instance_id": instance.id if instance else False,
                "related_model": vals.get("related_model") or False,
                "related_res_id": int(vals.get("related_res_id") or 0) or False,
                "conversation_id": int(vals.get("conversation_id") or 0) or False,
                "priority": int(vals.get("priority") or 5),
                "source_app": vals.get("source_app") or "hub",
                "partner_id": int(vals.get("partner_id") or 0) or False,
                "campaign_id": int(vals.get("campaign_id") or 0) or False,
                "campaign_line_id": int(vals.get("campaign_line_id") or 0) or False,
                "discuss_channel_id": int(vals.get("discuss_channel_id") or 0) or False,
            }
        )
        Message = self.env["whatsapp.message"].sudo()
        Conversation = self.env["whatsapp.conversation"].sudo()
        conversation = outbound.conversation_id
        conv_purpose = purpose if purpose in dict(CONVERSATION_PURPOSE) else "other"
        instance_ref = instance.instance_name if instance else False
        if not conversation:
            contact = (
                self.env["whatsapp.contact"]
                .sudo()
                .get_or_create_from_sender(phone=destination)
            )
            conversation = Conversation.resolve_conversation(
                remote_jid=destination,
                purpose=conv_purpose,
                instance_id=instance.id if instance else False,
                instance_reference=instance_ref or False,
                conversation_type="group"
                if destination.endswith("@g.us")
                else "dm",
                contact=contact,
                partner=outbound.partner_id,
                name=f"Outbound {destination}",
            )
            outbound.conversation_id = conversation
        client_request_id = vals.get("client_request_id") or f"outbound-{outbound.id}"
        related_model = vals.get("related_model") or False
        related_res_id = int(vals.get("related_res_id") or 0) or False
        business_key = build_business_key(
            source_model=related_model or "whatsapp.outbound.message",
            source_res_id=related_res_id or outbound.id,
            client_request_id=client_request_id,
        )
        dedupe = hashlib_sha(f"out:{outbound.id}:{destination}:{body[:80]}")
        remote = _normalize_remote_jid(destination)
        msg = Message.create(
            {
                "direction": "out",
                "state": "queued",
                "delivery_state": "pending",
                "body": body,
                "conversation_id": conversation.id,
                "contact_id": conversation.contact_id.id,
                "group_id": conversation.group_id.id,
                "instance_id": instance.id if instance else False,
                "instance_reference": instance_ref or False,
                "dedupe_key": dedupe,
                "business_key": business_key or False,
                "provider": "evolution",
                "provider_message_id": f"outbound-{outbound.id}",
                "group_jid": destination if destination.endswith("@g.us") else False,
                "remote_jid": remote or False,
                "source_app": vals.get("source_app") or "hub",
                "purpose": conv_purpose,
                "related_model": related_model or "whatsapp.outbound.message",
                "related_res_id": related_res_id or outbound.id,
                "client_request_id": client_request_id,
                "partner_id": outbound.partner_id.id if outbound.partner_id else False,
                "campaign_id": outbound.campaign_id or False,
                "campaign_line_id": outbound.campaign_line_id or False,
                "discuss_channel_id": outbound.discuss_channel_id or False,
            }
        )
        outbound.write(
            {
                "message_id": msg.id,
                "client_request_id": client_request_id,
                "business_key": business_key or False,
            }
        )
        if vals.get("send_now"):
            outbound.action_send()
        return {
            "outbound_id": outbound.id,
            "message_id": msg.id,
            "state": outbound.state,
            "duplicate": False,
            "api": "service_queue_outbound",
        }

    # ----------------------------------------------------------- Phase 3 API
    @api.model
    def service_preview_send_message(self, vals):
        """
        Dry-run admission preview for Phase 4 shadow mode.

        Does NOT create messages, outbound jobs, or call transport.
        Does NOT require unified_outbound_enabled (validation-only).
        Does NOT reserve idempotency keys.
        """
        result = {
            "ok": False,
            "eligible": False,
            "errors": [],
            "classification": "validation_error",
            "candidate": {},
        }
        if not isinstance(vals, dict):
            result["errors"].append("vals must be an object")
            return result

        message_type = (vals.get("message_type") or "text").strip().lower()
        if message_type in DEFERRED_MESSAGE_TYPES or message_type not in SUPPORTED_MESSAGE_TYPES:
            result["errors"].append(f"unsupported message_type={message_type}")
            result["classification"] = "unsupported_message_type"
            return result

        destination_raw = (vals.get("destination") or vals.get("jid") or "").strip()
        body = (vals.get("body") or vals.get("text") or "").strip()
        if not destination_raw:
            result["errors"].append("destination is required")
            result["classification"] = "invalid_destination"
            return result
        if not body:
            result["errors"].append("body/text is required")
            return result

        remote = _normalize_remote_jid(destination_raw)
        if not remote:
            result["errors"].append("destination could not be normalized")
            result["classification"] = "invalid_destination"
            return result
        destination = remote if remote.endswith("@g.us") else remote.split("@", 1)[0]

        purpose = vals.get("purpose") or "other"
        if purpose not in dict(OUTBOUND_PURPOSE):
            result["errors"].append(f"invalid purpose={purpose}")
            return result

        hub_instance = self.env["whatsapp.instance"].browse()
        if vals.get("instance_id"):
            hub_instance = self.env["whatsapp.instance"].browse(int(vals["instance_id"]))
            if not hub_instance.exists() or not hub_instance.active:
                result["errors"].append("instance missing or inactive")
                result["classification"] = "missing_instance"
                return result
        elif vals.get("instance_reference"):
            hub_instance = self.env["whatsapp.instance"].search(
                [
                    ("instance_name", "=", vals["instance_reference"].strip()),
                    ("active", "=", True),
                ],
                limit=1,
            )

        client_request_id = _clean(vals.get("client_request_id"), 200)
        business_key = _clean(vals.get("business_key"), 300) or False
        related_model = _clean(vals.get("related_model") or vals.get("source_model"), 120) or False
        related_res_id = int(vals.get("related_res_id") or vals.get("source_res_id") or 0) or False
        if not business_key:
            if not client_request_id:
                result["errors"].append("client_request_id or business_key required")
                return result
            related_model = related_model or "whatsapp.hub.outbound"
            business_key = build_business_key(
                source_model=related_model,
                source_res_id=related_res_id or 0,
                client_request_id=client_request_id,
            )
        if not client_request_id:
            client_request_id = business_key

        from .whatsapp_conversation import build_conversation_identity_key

        instance_ref = (
            hub_instance.instance_name
            if hub_instance
            else (vals.get("instance_reference") or False)
        )
        conv_purpose = purpose if purpose in dict(CONVERSATION_PURPOSE) else "other"
        expected_identity = build_conversation_identity_key(
            instance_id=hub_instance.id if hub_instance else None,
            instance_reference=instance_ref or None,
            remote_jid=remote,
            purpose=conv_purpose,
        )

        existing = (
            self.env["whatsapp.message"]
            .sudo()
            .find_canonical_message(
                business_key=business_key,
                client_request_id=client_request_id,
                related_model=related_model,
                related_res_id=related_res_id,
            )
        )

        result.update(
            {
                "ok": True,
                "eligible": True,
                "classification": "matched",
                "candidate": {
                    "destination": destination,
                    "remote_jid": remote,
                    "purpose": purpose,
                    "source_app": vals.get("source_app") or "hub",
                    "business_key": business_key,
                    "client_request_id": client_request_id,
                    "related_model": related_model or False,
                    "related_res_id": related_res_id or False,
                    "partner_id": int(vals.get("partner_id") or 0) or False,
                    "discuss_channel_id": int(vals.get("discuss_channel_id") or 0)
                    or False,
                    "instance_id": hub_instance.id if hub_instance else False,
                    "instance_reference": instance_ref or False,
                    "message_type": "text",
                    "expected_conversation_identity_key": expected_identity,
                    "existing_message_id": existing.id if existing else False,
                },
            }
        )
        return result

    @api.model
    def service_send_message(self, vals):
        """
        Unified Hub outbound admission API (Phase 3).

        Required: destination, body/text, client_request_id (or business_key)
        Optional: instance_id, instance_reference, purpose, source_app,
                  related_model, related_res_id, partner_id, campaign_id,
                  campaign_line_id, discuss_channel_id, message_type, send_now,
                  priority, name

        Gated by whatsapp_hub.unified_outbound_enabled (default False).
        Does not alter Campaign/Discuss legacy send paths.
        """
        self._require_send_access()
        if not isinstance(vals, dict):
            raise ValidationError("vals must be an object.")

        message_type = (vals.get("message_type") or "text").strip().lower()
        if message_type in DEFERRED_MESSAGE_TYPES:
            raise ValidationError(
                f"message_type={message_type} is not supported in Phase 3 "
                f"(supported: {', '.join(SUPPORTED_MESSAGE_TYPES)})."
            )
        if message_type not in SUPPORTED_MESSAGE_TYPES:
            raise ValidationError(f"Unsupported message_type={message_type}.")

        destination_raw = (vals.get("destination") or vals.get("jid") or "").strip()
        body = (vals.get("body") or vals.get("text") or "").strip()
        if not destination_raw:
            raise ValidationError("destination is required.")
        if not body:
            raise ValidationError("body/text is required for text messages.")

        remote = _normalize_remote_jid(destination_raw)
        if not remote:
            raise ValidationError("destination could not be normalized to a JID/phone.")
        # Evolution number: digits or full group JID
        destination = remote if remote.endswith("@g.us") else remote.split("@", 1)[0]

        purpose = vals.get("purpose") or "other"
        if purpose not in dict(OUTBOUND_PURPOSE):
            raise ValidationError(f"Invalid purpose={purpose}.")

        hub_instance = self.env["whatsapp.instance"].browse()
        if vals.get("instance_id"):
            hub_instance = self.env["whatsapp.instance"].browse(int(vals["instance_id"]))
            if not hub_instance.exists():
                raise ValidationError("instance_id not found.")
            if not hub_instance.active:
                raise ValidationError("WhatsApp instance is inactive.")
        elif vals.get("instance_reference"):
            hub_instance = self.env["whatsapp.instance"].search(
                [
                    ("instance_name", "=", vals["instance_reference"].strip()),
                    ("active", "=", True),
                ],
                limit=1,
            )

        self._assert_unified_outbound_enabled(purpose, hub_instance)

        client_request_id = _clean(vals.get("client_request_id"), 200)
        business_key = _clean(vals.get("business_key"), 300) or False
        related_model = _clean(vals.get("related_model") or vals.get("source_model"), 120) or False
        related_res_id = int(vals.get("related_res_id") or vals.get("source_res_id") or 0) or False
        if not business_key:
            if not client_request_id:
                raise ValidationError(
                    "client_request_id or business_key is required for unified outbound idempotency."
                )
            if not related_model:
                related_model = "whatsapp.hub.outbound"
            business_key = build_business_key(
                source_model=related_model,
                source_res_id=related_res_id or 0,
                client_request_id=client_request_id,
            )
        if not client_request_id:
            client_request_id = business_key

        Message = self.env["whatsapp.message"].sudo()
        existing_msg = Message.find_canonical_message(
            business_key=business_key,
            related_model=related_model,
            related_res_id=related_res_id,
            client_request_id=client_request_id,
        )
        if existing_msg:
            existing_out = self.sudo().search(
                [("message_id", "=", existing_msg.id)], limit=1
            )
            if not existing_out:
                existing_out = self.sudo().search(
                    [("business_key", "=", business_key)], limit=1
                )
            return {
                "ok": True,
                "duplicate": True,
                "message_id": existing_msg.id,
                "outbound_id": existing_out.id if existing_out else False,
                "conversation_id": existing_msg.conversation_id.id,
                "state": existing_out.state if existing_out else existing_msg.state,
                "delivery_state": existing_msg.delivery_state,
                "evolution_message_id": existing_msg.evolution_message_id or False,
                "api": "service_send_message",
            }

        # Also block duplicate active outbound with same business_key
        existing_out = self.sudo().search([("business_key", "=", business_key)], limit=1)
        if existing_out:
            return {
                "ok": True,
                "duplicate": True,
                "message_id": existing_out.message_id.id if existing_out.message_id else False,
                "outbound_id": existing_out.id,
                "conversation_id": existing_out.conversation_id.id
                if existing_out.conversation_id
                else False,
                "state": existing_out.state,
                "delivery_state": existing_out.message_id.delivery_state
                if existing_out.message_id
                else False,
                "evolution_message_id": existing_out.evolution_message_id or False,
                "api": "service_send_message",
            }

        source_app = vals.get("source_app") or "hub"
        if source_app not in dict(SOURCE_APP):
            source_app = "hub"
        partner_id = int(vals.get("partner_id") or 0) or False
        campaign_id = int(vals.get("campaign_id") or 0) or False
        campaign_line_id = int(vals.get("campaign_line_id") or 0) or False
        discuss_channel_id = int(vals.get("discuss_channel_id") or 0) or False
        instance_ref = (
            hub_instance.instance_name
            if hub_instance
            else (vals.get("instance_reference") or False)
        )
        conv_purpose = purpose if purpose in dict(CONVERSATION_PURPOSE) else "other"

        partner = self.env["res.partner"].browse(partner_id) if partner_id else self.env["res.partner"]
        contact = (
            self.env["whatsapp.contact"]
            .sudo()
            .get_or_create_from_sender(
                phone=destination,
                name=partner.name if partner else None,
            )
        )
        if partner and not contact.partner_id:
            contact.sudo().write({"partner_id": partner.id})

        conversation = (
            self.env["whatsapp.conversation"]
            .sudo()
            .resolve_conversation(
                remote_jid=remote,
                purpose=conv_purpose,
                instance_id=hub_instance.id if hub_instance else False,
                instance_reference=instance_ref or False,
                conversation_type="group" if remote.endswith("@g.us") else "dm",
                contact=contact,
                partner=partner,
                name=(partner.name if partner else None) or destination,
            )
        )

        name = vals.get("name") or f"Hub WA → {destination[:40]}"
        outbound = self.sudo().create(
            {
                "name": name,
                "destination": destination,
                "body": body,
                "message_type": "text",
                "transport_mode": "unified_bridge",
                "purpose": purpose,
                "instance_id": hub_instance.id if hub_instance else False,
                "related_model": related_model or False,
                "related_res_id": related_res_id or False,
                "client_request_id": client_request_id,
                "business_key": business_key,
                "source_app": source_app,
                "partner_id": partner_id,
                "campaign_id": campaign_id or False,
                "campaign_line_id": campaign_line_id or False,
                "discuss_channel_id": discuss_channel_id or False,
                "conversation_id": conversation.id,
                "priority": int(vals.get("priority") or 5),
                "state": "pending",
                "max_retries": int(vals["max_retries"])
                if vals.get("max_retries") is not None
                else 3,
            }
        )

        dedupe = hashlib_sha(f"unified:{business_key}")
        msg = Message.create(
            {
                "direction": "out",
                "state": "queued",
                "delivery_state": "pending",
                "body": body,
                "conversation_id": conversation.id,
                "contact_id": contact.id,
                "instance_id": hub_instance.id if hub_instance else False,
                "instance_reference": instance_ref or False,
                "dedupe_key": dedupe,
                "business_key": business_key,
                "provider": "evolution",
                "provider_message_id": f"pending:{business_key}"[:200],
                "group_jid": remote if remote.endswith("@g.us") else False,
                "remote_jid": remote,
                "source_app": source_app,
                "purpose": conv_purpose,
                "related_model": related_model or False,
                "related_res_id": related_res_id or False,
                "client_request_id": client_request_id,
                "partner_id": partner_id,
                "campaign_id": campaign_id or False,
                "campaign_line_id": campaign_line_id or False,
                "discuss_channel_id": discuss_channel_id or False,
            }
        )
        outbound.message_id = msg
        conversation.write({"last_message_at": fields.Datetime.now()})

        send_now = bool(vals.get("send_now", True))
        if send_now:
            outbound.action_send()

        outbound.invalidate_recordset()
        msg.invalidate_recordset()
        return {
            "ok": True,
            "duplicate": False,
            "message_id": msg.id,
            "outbound_id": outbound.id,
            "conversation_id": conversation.id,
            "state": outbound.state,
            "delivery_state": msg.delivery_state,
            "evolution_message_id": outbound.evolution_message_id or False,
            "api": "service_send_message",
        }

    # alias
    @api.model
    def service_enqueue_message(self, vals):
        """Alias of service_send_message with send_now default False."""
        if not isinstance(vals, dict):
            raise ValidationError("vals must be an object.")
        payload = dict(vals)
        payload.setdefault("send_now", False)
        return self.service_send_message(payload)

    def action_send(self):
        for rec in self:
            rec._send_one()
        return True

    def _send_one(self):
        self.ensure_one()
        if self.state == "sent":
            return True
        if self.state == "cancelled":
            return False
        self.write({"state": "processing"})
        if self.transport_mode == "unified_bridge":
            return self._send_one_unified()
        return self._send_one_legacy_direct()

    def _send_one_unified(self):
        self.ensure_one()
        Transport = self.env["whatsapp.hub.transport"]
        try:
            result = Transport.send_text(
                destination=self.destination,
                body=self.body,
                purpose=self.purpose,
                instance_reference=self.instance_id.instance_name
                if self.instance_id
                else False,
                hub_instance=self.instance_id,
            )
        except UserError as exc:
            self._mark_retry(str(exc), permanent=True)
            return False
        except Exception as exc:
            self._mark_retry(str(exc), permanent=False)
            return False

        evo_id = result.get("provider_message_id") or False
        excerpt = result.get("response_excerpt") or ""
        if result.get("ok"):
            self.write(
                {
                    "state": "sent",
                    "sent_at": fields.Datetime.now(),
                    "error_message": False,
                    "response_data": json.dumps(
                        {
                            "http_status": result.get("http_status"),
                            "transport": result.get("transport"),
                            "bridge_instance_id": result.get("bridge_instance_id"),
                            "excerpt": excerpt,
                        },
                        default=str,
                    )[:8000],
                    "evolution_message_id": evo_id,
                    "bridge_instance_id": int(result.get("bridge_instance_id") or 0)
                    or False,
                }
            )
            if self.message_id:
                self.message_id.with_context(whatsapp_hub_mirroring=True).write(
                    {
                        "state": "sent",
                        "delivery_state": "sent",
                        "evolution_message_id": evo_id or False,
                        "provider_message_id": evo_id or self.message_id.provider_message_id,
                        "sent_at": fields.Datetime.now(),
                        "error_message": False,
                    }
                )
                self.message_id._on_outbound_sent()
            self._project_campaign_line_from_outbound()
            return True

        permanent = not result.get("temporary")
        err = result.get("error") or "transport_failed"
        self._mark_retry(err, permanent=permanent)
        return False

    def _send_one_legacy_direct(self):
        """Pre-Phase-3 clinic path — direct Evolution HTTP via Hub instance/ICP."""
        self.ensure_one()
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
            if self.message_id:
                self.message_id.write({"state": "failed", "delivery_state": "failed"})
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
                        "sent_at": fields.Datetime.now(),
                    }
                )
                self.message_id._on_outbound_sent()
            return True
        except Exception as exc:
            self._mark_retry(str(exc))
            return False

    def _mark_retry(self, error, permanent=False):
        self.ensure_one()
        retries = self.retry_count + 1
        vals = {
            "retry_count": retries,
            "error_message": _clean(error, 2000),
            "next_retry_at": fields.Datetime.now() + timedelta(minutes=5 * retries),
            "state": "pending",
        }
        if permanent or retries >= self.max_retries:
            vals["state"] = "failed"
            if self.message_id:
                self.message_id.with_context(whatsapp_hub_mirroring=True).write(
                    {
                        "state": "failed",
                        "delivery_state": "failed",
                        "error_message": _clean(error, 2000),
                        "retry_count": retries,
                    }
                )
        else:
            if self.message_id:
                self.message_id.with_context(whatsapp_hub_mirroring=True).write(
                    {
                        "state": "queued",
                        "delivery_state": "pending",
                        "error_message": _clean(error, 2000),
                        "retry_count": retries,
                    }
                )
        self.write(vals)
        _logger.warning(
            "whatsapp outbound %s failed (mode=%s): %s",
            self.id,
            self.transport_mode,
            error,
        )
        self._project_campaign_line_from_outbound()

    def _project_campaign_line_from_outbound(self):
        """
        P5B: project Hub outbound lifecycle onto wa.campaign.line (soft ints).

        Admission keeps line pending; provider sent → line sent; exhausted → failed.
        Idempotent; does not touch Discuss.
        """
        self.ensure_one()
        if self.purpose != "campaign":
            return
        if "wa.campaign.line" not in self.env:
            return
        line_id = self.campaign_line_id or False
        if not line_id and self.message_id:
            line_id = self.message_id.campaign_line_id or False
        if not line_id:
            return
        Line = self.env["wa.campaign.line"].sudo()
        line = Line.browse(int(line_id))
        if not line.exists():
            return
        vals = {}
        if line.hub_outbound_id != self.id:
            vals["hub_outbound_id"] = self.id
        if self.message_id and line.hub_message_id != self.message_id.id:
            vals["hub_message_id"] = self.message_id.id
        evo = (self.evolution_message_id or "").strip()
        if self.state == "sent":
            vals.update(
                {
                    "status": "sent",
                    "sent_date": self.sent_at or fields.Datetime.now(),
                    "error_msg": False,
                }
            )
            if evo:
                vals["wa_message_id"] = evo
        elif self.state == "failed":
            vals.update(
                {
                    "status": "failed",
                    "error_msg": _clean(self.error_message or "Hub outbound failed", 200),
                }
            )
        elif self.state in ("pending", "processing"):
            # Retrying / admitted — must not appear sent
            if line.status == "sent" and not evo:
                vals["status"] = "pending"
            if self.error_message and line.status == "pending":
                vals["error_msg"] = _clean(self.error_message, 200)
        elif self.state == "cancelled" and line.status == "pending":
            vals.update(
                {
                    "status": "skipped",
                    "error_msg": _clean(self.error_message or "Hub job cancelled", 200),
                }
            )
        if vals:
            line.write(vals)
        # Refresh hub_unified compat log delivery if present
        if "wa.message.log" in self.env and self.message_id:
            Log = self.env["wa.message.log"].sudo()
            log = Log.search(
                [
                    ("campaign_line_id", "=", line.id),
                    ("send_origin", "=", "hub_unified"),
                ],
                limit=1,
            )
            if log:
                delivery = "pending"
                if self.state == "sent":
                    delivery = "sent"
                elif self.state == "failed":
                    delivery = "failed"
                log_vals = {
                    "delivery_status": delivery,
                    "hub_message_id": self.message_id.id,
                }
                if evo:
                    log_vals["wa_message_id"] = evo
                log.write(log_vals)

    @api.model
    def service_quarantine_discuss_channel(self, channel_id, reason=""):
        """
        Quarantine incomplete unified_bridge Discuss jobs for one channel.

        Prevents Hub cron from sending already-admitted jobs after a channel
        leaves Hub mode. Does not alter sent provider-accepted jobs.
        Does not trigger legacy resend.
        """
        self._require_send_access()
        try:
            channel_id = int(channel_id)
        except (TypeError, ValueError) as exc:
            raise ValidationError("channel_id must be an integer.") from exc
        reason_clean = _clean(reason or "discuss channel quarantine", 500) or (
            "discuss channel quarantine"
        )

        jobs = self.sudo().search(
            [
                ("transport_mode", "=", "unified_bridge"),
                ("discuss_channel_id", "=", channel_id),
            ]
        )
        result = {
            "ok": True,
            "channel_id": channel_id,
            "jobs_found": len(jobs),
            "cancelled": 0,
            "already_sent": 0,
            "failed": 0,
            "uncertain": 0,
            "already_cancelled": 0,
            "job_ids": {
                "cancelled": [],
                "already_sent": [],
                "failed": [],
                "uncertain": [],
                "already_cancelled": [],
            },
            "reason": reason_clean,
        }

        for job in jobs:
            evo_id = (job.evolution_message_id or "").strip()
            if job.state == "sent" or (evo_id and job.state in ("pending", "processing")):
                if job.state != "sent" and evo_id:
                    # Provider id present → treat as accepted; stop retries.
                    job.write(
                        {
                            "state": "sent",
                            "next_retry_at": False,
                            "sent_at": job.sent_at or fields.Datetime.now(),
                        }
                    )
                result["already_sent"] += 1
                result["job_ids"]["already_sent"].append(job.id)
                continue
            if job.state == "failed":
                result["failed"] += 1
                result["job_ids"]["failed"].append(job.id)
                continue
            if job.state == "cancelled":
                result["already_cancelled"] += 1
                result["job_ids"]["already_cancelled"].append(job.id)
                continue
            if job.state == "processing" and not evo_id:
                # Uncertain mid-flight: stop automatic retry; manual review.
                job.write(
                    {
                        "state": "cancelled",
                        "next_retry_at": False,
                        "error_message": _clean(
                            f"uncertain quarantine (was processing): {reason_clean}",
                            2000,
                        ),
                    }
                )
                result["uncertain"] += 1
                result["job_ids"]["uncertain"].append(job.id)
                continue
            if job.state == "pending":
                job.write(
                    {
                        "state": "cancelled",
                        "next_retry_at": False,
                        "error_message": _clean(reason_clean, 2000),
                    }
                )
                result["cancelled"] += 1
                result["job_ids"]["cancelled"].append(job.id)
                continue
            # Any other incomplete state: fail closed cancel
            job.write(
                {
                    "state": "cancelled",
                    "next_retry_at": False,
                    "error_message": _clean(
                        f"quarantine ({job.state}): {reason_clean}", 2000
                    ),
                }
            )
            result["cancelled"] += 1
            result["job_ids"]["cancelled"].append(job.id)

        return result

    @api.model
    def service_quarantine_campaign(self, campaign_id, reason=""):
        """
        Quarantine incomplete unified_bridge Campaign jobs for one campaign.

        Filters by purpose=campaign and campaign_id. Never touches Discuss jobs.
        Does not alter provider-accepted (sent) jobs or trigger legacy resend.
        """
        self._require_send_access()
        try:
            campaign_id = int(campaign_id)
        except (TypeError, ValueError) as exc:
            raise ValidationError("campaign_id must be an integer.") from exc
        reason_clean = _clean(reason or "campaign quarantine", 500) or (
            "campaign quarantine"
        )

        jobs = self.sudo().search(
            [
                ("transport_mode", "=", "unified_bridge"),
                ("purpose", "=", "campaign"),
                ("campaign_id", "=", campaign_id),
            ]
        )
        result = {
            "ok": True,
            "campaign_id": campaign_id,
            "jobs_found": len(jobs),
            "cancelled": 0,
            "already_sent": 0,
            "failed": 0,
            "uncertain": 0,
            "already_cancelled": 0,
            "job_ids": {
                "cancelled": [],
                "already_sent": [],
                "failed": [],
                "uncertain": [],
                "already_cancelled": [],
            },
            "reason": reason_clean,
        }

        for job in jobs:
            evo_id = (job.evolution_message_id or "").strip()
            if job.state == "sent" or (evo_id and job.state in ("pending", "processing")):
                if job.state != "sent" and evo_id:
                    job.write(
                        {
                            "state": "sent",
                            "next_retry_at": False,
                            "sent_at": job.sent_at or fields.Datetime.now(),
                        }
                    )
                result["already_sent"] += 1
                result["job_ids"]["already_sent"].append(job.id)
                continue
            if job.state == "failed":
                result["failed"] += 1
                result["job_ids"]["failed"].append(job.id)
                continue
            if job.state == "cancelled":
                result["already_cancelled"] += 1
                result["job_ids"]["already_cancelled"].append(job.id)
                continue
            if job.state == "processing" and not evo_id:
                job.write(
                    {
                        "state": "cancelled",
                        "next_retry_at": False,
                        "error_message": _clean(
                            f"uncertain quarantine (was processing): {reason_clean}",
                            2000,
                        ),
                    }
                )
                result["uncertain"] += 1
                result["job_ids"]["uncertain"].append(job.id)
                continue
            if job.state == "pending":
                job.write(
                    {
                        "state": "cancelled",
                        "next_retry_at": False,
                        "error_message": _clean(reason_clean, 2000),
                    }
                )
                result["cancelled"] += 1
                result["job_ids"]["cancelled"].append(job.id)
                continue
            job.write(
                {
                    "state": "cancelled",
                    "next_retry_at": False,
                    "error_message": _clean(
                        f"quarantine ({job.state}): {reason_clean}", 2000
                    ),
                }
            )
            result["cancelled"] += 1
            result["job_ids"]["cancelled"].append(job.id)

        return result

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
