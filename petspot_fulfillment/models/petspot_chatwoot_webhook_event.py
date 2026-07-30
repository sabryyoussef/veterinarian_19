# -*- coding: utf-8 -*-
import hashlib
import json
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from .petspot_cta_parser import is_availability_cta, parse_availability_cta

_logger = logging.getLogger(__name__)


class PetspotChatwootWebhookEvent(models.Model):
    _name = "petspot.chatwoot.webhook.event"
    _description = "PetSpot Chatwoot Webhook Event"
    _order = "id desc"

    name = fields.Char(required=True, index=True)
    idempotency_key = fields.Char(required=True, index=True, copy=False)
    event_type = fields.Char(index=True)
    account_id = fields.Char(index=True)
    inbox_id = fields.Char(index=True)
    conversation_id = fields.Char(index=True)
    contact_id = fields.Char(index=True)
    message_id = fields.Char(index=True)
    message_type = fields.Char()
    direction = fields.Selection(
        [
            ("incoming", "Incoming"),
            ("outgoing", "Outgoing"),
            ("activity", "Activity"),
            ("unknown", "Unknown"),
        ],
        default="unknown",
    )
    state = fields.Selection(
        [
            ("received", "Received"),
            ("ignored", "Ignored"),
            ("processed", "Processed"),
            ("failed", "Failed"),
            ("review", "Review required"),
        ],
        default="received",
        required=True,
        index=True,
    )
    ignore_reason = fields.Char()
    error_message = fields.Char()
    payload_fingerprint = fields.Char(
        help="SHA256 of canonical payload subset — never stores secrets/full body.",
    )
    content_preview = fields.Char(help="Short sanitized preview only.")
    inquiry_id = fields.Many2one("petspot.availability.inquiry", ondelete="set null")
    ack_sent = fields.Boolean(default=False)
    processed_at = fields.Datetime()
    attempt_count = fields.Integer(default=0)

    _sql_constraints = [
        (
            "petspot_cw_event_idem_unique",
            "unique(idempotency_key)",
            "Chatwoot webhook event already processed.",
        ),
    ]

    @api.model
    def _cfg(self, key, default=""):
        return self.env["ir.config_parameter"].sudo().get_param(key, default)

    @api.model
    def _intake_enabled(self):
        return self._cfg("petspot_fulfillment.chatwoot_intake_enabled", "False") == "True"

    @api.model
    def validate_webhook_secret(self, headers):
        secret = self._cfg("petspot_fulfillment.chatwoot_webhook_secret", "")
        if not secret:
            return False
        # Headers may be plain dict with varying case after copy
        lowered = {str(k).lower(): v for k, v in (headers or {}).items()}
        provided = (
            lowered.get("x-petspot-webhook-secret")
            or lowered.get("x-chatwoot-webhook-secret")
            or ""
        )
        auth = lowered.get("authorization") or ""
        if auth.lower().startswith("bearer "):
            provided = provided or auth[7:].strip()
        return bool(provided) and provided == secret

    @api.model
    def process_webhook_payload(self, payload, headers=None):
        """Idempotent Chatwoot message intake. Never creates SO/RFQ/payment/AWB."""
        headers = headers or {}
        if not self._intake_enabled() and not self.env.context.get("petspot_ff_force_intake"):
            return {"ok": True, "ignored": True, "reason": "intake_disabled"}

        event_type = str(payload.get("event") or payload.get("event_type") or "")
        account = payload.get("account") or {}
        inbox = payload.get("inbox") or {}
        conversation = payload.get("conversation") or {}
        sender = payload.get("sender") or {}
        message_id = str(payload.get("id") or payload.get("message_id") or "")
        account_id = str(account.get("id") or payload.get("account_id") or "")
        inbox_id = str(
            inbox.get("id")
            or (conversation.get("inbox_id") if isinstance(conversation, dict) else "")
            or ""
        )
        conversation_id = str(
            conversation.get("id")
            if isinstance(conversation, dict)
            else payload.get("conversation_id")
            or ""
        )
        contact_id = str(sender.get("id") or "")
        if not message_id or not account_id or not conversation_id:
            return {"ok": False, "error": "missing_ids", "status": 400}

        permitted_account = self._cfg("petspot_fulfillment.chatwoot_account_id", "2")
        permitted_inbox = self._cfg("petspot_fulfillment.chatwoot_inbox_id", "2")
        if permitted_account and account_id != str(permitted_account):
            return {"ok": True, "ignored": True, "reason": "account_not_permitted"}
        if permitted_inbox and inbox_id and inbox_id != str(permitted_inbox):
            return {"ok": True, "ignored": True, "reason": "inbox_not_permitted"}

        idem = f"cw:{account_id}:{conversation_id}:{message_id}"
        existing = self.search([("idempotency_key", "=", idem)], limit=1)
        if existing:
            return {
                "ok": True,
                "replay": True,
                "event_id": existing.id,
                "state": existing.state,
                "inquiry_id": existing.inquiry_id.id or False,
                "inquiry_name": existing.inquiry_id.name if existing.inquiry_id else False,
            }

        content = payload.get("content") or ""
        preview = (content or "")[:120].replace("\n", " ")
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "e": event_type,
                    "a": account_id,
                    "c": conversation_id,
                    "m": message_id,
                    "t": payload.get("message_type"),
                    "p": bool(payload.get("private")),
                },
                sort_keys=True,
                default=str,
            ).encode("utf-8")
        ).hexdigest()

        direction, ignore_reason = self._classify_direction(payload, event_type)
        event = self.create({
            "name": f"CW/{account_id}/{conversation_id}/{message_id}",
            "idempotency_key": idem,
            "event_type": event_type or False,
            "account_id": account_id,
            "inbox_id": inbox_id or False,
            "conversation_id": conversation_id,
            "contact_id": contact_id or False,
            "message_id": message_id,
            "message_type": str(payload.get("message_type") or ""),
            "direction": direction,
            "state": "received",
            "payload_fingerprint": fingerprint,
            "content_preview": preview,
            "attempt_count": 1,
        })
        _logger.info(
            "petspot_ff chatwoot webhook event=%s account=%s conv=%s msg=%s dir=%s",
            event.id, account_id, conversation_id, message_id, direction,
        )

        if ignore_reason:
            event.write({
                "state": "ignored",
                "ignore_reason": ignore_reason,
                "processed_at": fields.Datetime.now(),
            })
            return {"ok": True, "ignored": True, "reason": ignore_reason, "event_id": event.id}

        if not is_availability_cta(content):
            event.write({
                "state": "ignored",
                "ignore_reason": "not_availability_cta",
                "processed_at": fields.Datetime.now(),
            })
            return {
                "ok": True,
                "ignored": True,
                "reason": "not_availability_cta",
                "event_id": event.id,
            }

        try:
            inquiry = self.env["petspot.availability.inquiry"]._intake_from_chatwoot_cta(
                payload=payload,
                parsed=parse_availability_cta(content),
                account_id=account_id,
                inbox_id=inbox_id,
                conversation_id=conversation_id,
                contact_id=contact_id,
                message_id=message_id,
            )
        except Exception as exc:
            _logger.exception("petspot_ff chatwoot intake failed event=%s", event.id)
            event.write({
                "state": "failed",
                "error_message": str(exc)[:500],
                "processed_at": fields.Datetime.now(),
            })
            return {"ok": False, "error": "processing_failed", "event_id": event.id, "status": 500}

        event.write({
            "inquiry_id": inquiry.id,
            "state": "review" if inquiry.review_required else "processed",
            "processed_at": fields.Datetime.now(),
        })
        ack_sent = False
        if self._cfg("petspot_fulfillment.chatwoot_ack_enabled", "True") == "True":
            ack_sent = inquiry._send_chatwoot_acknowledgement()
            event.ack_sent = ack_sent
        return {
            "ok": True,
            "event_id": event.id,
            "inquiry_id": inquiry.id,
            "inquiry_name": inquiry.name,
            "review_required": inquiry.review_required,
            "ack_sent": ack_sent,
            "case_id": inquiry.case_id.id or False,
        }

    @api.model
    def _classify_direction(self, payload, event_type):
        if event_type and event_type not in ("message_created", "message_updated"):
            return "unknown", "unsupported_event"
        if payload.get("private"):
            return "outgoing", "private_note"
        mt = payload.get("message_type")
        if mt in (1, "1", "outgoing", "outgoing_message"):
            return "outgoing", "outgoing_message"
        if mt in (2, "2", "activity"):
            return "activity", "activity_message"
        sender = payload.get("sender") or {}
        sender_type = (sender.get("type") or "").lower()
        if sender_type in ("user", "agent_bot", "agentbot"):
            return "outgoing", "agent_or_bot_sender"
        if mt in (0, "0", "incoming", None, False, ""):
            return "incoming", False
        return "unknown", "unsupported_message_type"

    def action_reprocess(self):
        self.ensure_one()
        if not self.env.user.has_group("petspot_fulfillment.group_fulfillment_manager"):
            raise UserError(_("Manager role required to reprocess webhook events."))
        if self.state not in ("failed", "received"):
            raise UserError(_("Only failed/received events can be reprocessed."))
        raise UserError(
            _("Reprocess requires the original payload from Chatwoot retry. "
              "Trigger a Chatwoot webhook replay for message %s.")
            % self.message_id
        )
