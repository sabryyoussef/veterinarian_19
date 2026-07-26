# -*- coding: utf-8 -*-
"""Canonical WhatsApp message store + normalized ingest RPC."""
from __future__ import annotations

import hashlib
import json
import logging

from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError

from .whatsapp_conversation import CONVERSATION_PURPOSE, _normalize_remote_jid

_logger = logging.getLogger(__name__)

SOURCE_APP = [
    ("hub", "Hub"),
    ("n8n", "n8n / Chatwoot ingest"),
    ("campaign", "Campaign"),
    ("discuss", "Discuss"),
    ("wizard", "Send Wizard"),
    ("clinic", "Clinic"),
    ("rewards", "Rewards"),
    ("mirror", "Legacy Mirror"),
    ("other", "Other"),
]

# Forward-only delivery ranks for lifecycle sync
_DELIVERY_RANK = {
    "pending": 0,
    "queued": 1,
    "sent": 2,
    "delivered": 3,
    "read": 4,
    "failed": 5,
    "received": 1,
}


def _require_ingest_service(env):
    if env.is_superuser():
        return
    if env.user.has_group("whatsapp_hub.group_whatsapp_ingest_service"):
        return
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
    """Stable idempotency key for Chatwoot-normalized ingest.

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


def build_business_key(
    *,
    source_model=None,
    source_res_id=None,
    client_request_id=None,
    wa_message_log_id=None,
):
    """Stable business idempotency key (no timestamps)."""
    if wa_message_log_id:
        return f"walog:{int(wa_message_log_id)}"
    if source_model and source_res_id and client_request_id:
        return (
            f"src:{source_model}:{int(source_res_id)}:"
            f"{_clean(str(client_request_id), 200)}"
        )
    if source_model and client_request_id:
        return f"src:{source_model}:0:{_clean(str(client_request_id), 200)}"
    return False


def discuss_business_key(channel_id, mail_message_id):
    """Stable Discuss outbound identity: discuss:{channel_id}:{mail_message_id}."""
    return f"discuss:{int(channel_id)}:{int(mail_message_id)}"


def campaign_business_key(campaign_id, campaign_line_id):
    """Stable Campaign outbound identity: campaign:{campaign_id}:{campaign_line_id}."""
    return f"campaign:{int(campaign_id)}:{int(campaign_line_id)}"


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
    media_kind = fields.Selection(
        [
            ("none", "None"),
            ("image", "Image"),
            ("video", "Video"),
            ("audio", "Audio"),
            ("document", "Document"),
            ("sticker", "Sticker"),
            ("reaction", "Reaction"),
            ("unknown", "Unknown"),
        ],
        default="none",
        required=True,
        index=True,
    )
    has_media = fields.Boolean(default=False, index=True)
    is_hidden = fields.Boolean(
        default=False,
        index=True,
        help="User-hidden from chat/list unless Show hidden is enabled.",
    )
    attachment_ids = fields.Many2many(
        comodel_name="ir.attachment",
        relation="whatsapp_message_ir_attachment_rel",
        column1="message_id",
        column2="attachment_id",
        string="Media Attachments",
        help="Cached media files (Evolution preview or ingest upload).",
    )
    message_timestamp = fields.Datetime(default=fields.Datetime.now, index=True)
    sent_at = fields.Datetime(index=True)
    delivered_at = fields.Datetime()
    read_at = fields.Datetime()
    conversation_id = fields.Many2one(
        "whatsapp.conversation", required=True, ondelete="cascade", index=True
    )
    group_id = fields.Many2one("whatsapp.group", ondelete="set null", index=True)
    contact_id = fields.Many2one("whatsapp.contact", ondelete="set null", index=True)
    instance_id = fields.Many2one("whatsapp.instance", ondelete="set null", index=True)
    reply_to_id = fields.Many2one("whatsapp.message", ondelete="set null")

    # External / provider IDs
    dedupe_key = fields.Char(required=True, index=True)
    business_key = fields.Char(
        index=True,
        help="Stable business idempotency key (walog:ID or src:model:id:request).",
    )
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
    instance_reference = fields.Char(index=True)
    group_jid = fields.Char(index=True)
    sender_jid = fields.Char(index=True)
    remote_jid = fields.Char(
        index=True,
        help="Normalized remote peer JID for this message.",
    )
    attachment_references = fields.Text()
    raw_payload = fields.Text()
    error_message = fields.Text()
    retry_count = fields.Integer(default=0)

    # Source / business provenance
    source_app = fields.Selection(SOURCE_APP, default="other", index=True)
    purpose = fields.Selection(CONVERSATION_PURPOSE, default="other", index=True)
    related_model = fields.Char(index=True)
    related_res_id = fields.Integer(index=True)
    client_request_id = fields.Char(index=True)
    partner_id = fields.Many2one("res.partner", ondelete="set null", index=True)
    campaign_id = fields.Integer(
        index=True,
        help="Soft reference to wa.campaign (no hard module dependency).",
    )
    campaign_line_id = fields.Integer(
        index=True,
        help="Soft reference to wa.campaign.line.",
    )
    discuss_channel_id = fields.Integer(index=True)
    queue_id = fields.Integer(
        index=True,
        help="Soft reference to integration.outbound.queue when applicable.",
    )
    # Legacy bridge to wa.message.log
    wa_message_log_id = fields.Integer(index=True)

    _dedupe_unique = models.Constraint(
        "unique(dedupe_key)",
        "Duplicate WhatsApp message (dedupe_key).",
    )
    _business_key_unique = models.UniqueIndex(
        "(business_key) WHERE business_key IS NOT NULL",
        "Duplicate WhatsApp message (business_key).",
    )
    _wa_log_unique = models.UniqueIndex(
        "(wa_message_log_id) WHERE wa_message_log_id IS NOT NULL AND wa_message_log_id <> 0",
        "Each wa.message.log maps to at most one Hub message.",
    )
    # Partial unique for Evolution provider ids when instance is known.
    # Not applied when instance_reference is NULL (historical / Chatwoot rows).
    _provider_instance_msg_unique = models.UniqueIndex(
        "(provider, instance_reference, provider_message_id) "
        "WHERE provider_message_id IS NOT NULL AND instance_reference IS NOT NULL "
        "AND provider = 'evolution'",
        "Duplicate Evolution provider message for this instance.",
    )

    @api.depends("direction", "group_jid", "sender_jid", "remote_jid", "body")
    def _compute_display_name(self):
        for rec in self:
            arrow = "←" if rec.direction == "in" else "→"
            who = rec.sender_jid or rec.remote_jid or rec.group_jid or "?"
            snippet = (rec.body or "")[:40]
            rec.display_name = f"{arrow} {who}: {snippet}"

    @api.model
    def _classify_media_kind(self, body="", attachment_references="", raw_payload=""):
        """Derive media_kind without downloading files (cheap string heuristics)."""
        body_l = (body or "").strip().lower()
        refs_l = (attachment_references or "").strip().lower()
        blob = f"{body_l}\n{refs_l}"
        # Prefer explicit attachment_references tokens
        for kind, tokens in (
            ("image", ("media_type=image", "imagemessage", "[image]", "image/")),
            ("video", ("media_type=video", "videomessage", "[video]", "video/")),
            ("audio", ("media_type=audio", "audiomessage", "[audio]", "audio/", "ptt")),
            ("document", ("media_type=document", "documentmessage", "[document]", "application/")),
            ("sticker", ("media_type=sticker", "stickermessage", "[sticker]")),
            ("reaction", ("media_type=reaction", "reactionmessage", "[reaction]")),
        ):
            if any(t in blob for t in tokens):
                return kind
        # Lightweight raw_payload peek (bounded)
        raw = (raw_payload or "")[:4000].lower()
        for kind, tokens in (
            ("image", ('"imagemessage"', "imageMessage")),
            ("video", ('"videomessage"',)),
            ("audio", ('"audiomessage"',)),
            ("document", ('"documentmessage"',)),
            ("sticker", ('"stickermessage"',)),
            ("reaction", ('"reactionmessage"',)),
        ):
            if any(t.lower() in raw for t in tokens):
                return kind
        if refs_l and "media_type=" in refs_l:
            return "unknown"
        if refs_l:
            return "unknown"
        return "none"

    # Placeholders / noise bodies used by filters and chat hide-noise.
    _NOISE_BODIES = frozenset(
        {
            "",
            "[image]",
            "[video]",
            "[audio]",
            "[document]",
            "[sticker]",
            "[reaction]",
            "[media]",
        }
    )

    @api.model
    def _noise_domain(self):
        """Domain matching unimportant / noise messages (for exclusion)."""
        return [
            "|",
            ("is_hidden", "=", True),
            "|",
            "&",
            ("media_kind", "=", "none"),
            "|",
            ("body", "=", False),
            ("body", "in", ["", " "]),
            ("media_kind", "in", ["reaction", "sticker"]),
        ]

    def action_toggle_hidden(self):
        for rec in self:
            rec.is_hidden = not rec.is_hidden
        return True

    def action_hide(self):
        self.write({"is_hidden": True})
        return True

    def action_unhide(self):
        self.write({"is_hidden": False})
        return True

    def action_open_chat(self):
        """Open the conversation chat thread focused on this message."""
        self.ensure_one()
        if not self.conversation_id:
            raise ValidationError("Message has no conversation.")
        return self.conversation_id.with_context(
            focus_message_id=self.id
        ).action_open_chat()

    def _thread_payload(self):
        """Serialize a message for the OWL chat thread."""
        self.ensure_one()
        body = self.body or ""
        preview_url = False
        if self.attachment_ids:
            att = self.attachment_ids[:1]
            preview_url = f"/web/content/{att.id}?download=false"
        elif self.evolution_message_id and self.has_media:
            preview_url = f"/whatsapp_hub/media/{self.id}"
        return {
            "id": self.id,
            "direction": self.direction,
            "body": body,
            "timestamp": fields.Datetime.to_string(self.message_timestamp)
            if self.message_timestamp
            else False,
            "sender": self.sender_jid
            or (self.contact_id.display_name if self.contact_id else False)
            or (self.partner_id.display_name if self.partner_id else False)
            or "",
            "media_kind": self.media_kind or "none",
            "has_media": bool(self.has_media),
            "is_hidden": bool(self.is_hidden),
            "state": self.state,
            "delivery_state": self.delivery_state,
            "evolution_message_id": self.evolution_message_id or False,
            "has_cached_media": bool(self.attachment_ids),
            "preview_url": preview_url,
            "can_fetch_media": bool(
                self.evolution_message_id
                and self.has_media
                and self.media_kind
                not in ("none", "reaction")
            ),
        }

    def _reconstruct_evolution_key(self):
        self.ensure_one()
        from_me = self.direction == "out"
        remote = (self.group_jid or self.remote_jid or "").strip()
        sender = (self.sender_jid or "").strip()
        evo_id = (self.evolution_message_id or "").strip()
        key = {
            "remoteJid": remote,
            "id": evo_id,
            "fromMe": bool(from_me),
        }
        if remote.endswith("@g.us") and sender and not from_me:
            key["participant"] = sender
        return key

    def _resolve_instance_config(self):
        self.ensure_one()
        Instance = self.env["whatsapp.instance"].sudo()
        if self.instance_id:
            return self.instance_id.get_config_dict()
        if self.instance_reference:
            inst = Instance.search(
                [("instance_name", "=", self.instance_reference)], limit=1
            )
            if inst:
                return inst.get_config_dict()
        return Instance.get_default_config()

    def _fetch_evolution_media_bytes(self):
        """Call Evolution getBase64FromMediaMessage; return (bytes, mimetype, filename)."""
        import base64
        import urllib.error
        import urllib.request

        self.ensure_one()
        if not self.evolution_message_id:
            raise ValidationError("Message has no evolution_message_id.")
        cfg = self._resolve_instance_config()
        base = (cfg.get("url") or "").rstrip("/")
        instance_path = cfg.get("instance_path") or ""
        api_key = cfg.get("key") or ""
        if not base or not instance_path or not api_key:
            raise ValidationError("Evolution instance is not configured for media fetch.")
        key = self._reconstruct_evolution_key()
        if not key.get("remoteJid") or not key.get("id"):
            raise ValidationError("Cannot reconstruct Evolution media key.")
        url = f"{base}/chat/getBase64FromMediaMessage/{instance_path}"
        body = json.dumps(
            {"message": {"key": key}, "convertToMp4": False},
            separators=(",", ":"),
        ).encode()
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "apikey": api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                payload = json.loads(resp.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as exc:
            try:
                err = exc.read().decode("utf-8", errors="replace")[:400]
            except Exception:
                err = str(exc)
            raise ValidationError(f"Evolution media fetch failed ({exc.code}): {err}") from exc
        except Exception as exc:
            raise ValidationError(f"Evolution media fetch failed: {exc}") from exc

        b64 = (
            payload.get("base64")
            or payload.get("data")
            or (payload.get("media") or {}).get("base64")
            or ""
        )
        if isinstance(b64, dict):
            b64 = b64.get("base64") or b64.get("data") or ""
        if "," in str(b64) and str(b64).startswith("data:"):
            b64 = str(b64).split(",", 1)[1]
        if not b64:
            raise ValidationError("Evolution returned no media bytes.")
        raw = base64.b64decode(b64)
        mimetype = (
            payload.get("mimetype")
            or payload.get("mimeType")
            or (payload.get("media") or {}).get("mimetype")
            or "application/octet-stream"
        )
        filename = (
            payload.get("fileName")
            or payload.get("filename")
            or f"wa_{self.id}_{self.media_kind or 'media'}"
        )
        return raw, mimetype, filename

    def ensure_media_attachment(self, *, force=False):
        """Fetch Evolution media into ir.attachment when missing; return attachment."""
        self.ensure_one()
        if self.attachment_ids and not force:
            return self.attachment_ids[:1]
        if not self.can_fetch_media_preview():
            return self.env["ir.attachment"]
        raw, mimetype, filename = self._fetch_evolution_media_bytes()
        import base64

        att = (
            self.env["ir.attachment"]
            .sudo()
            .create(
                {
                    "name": filename,
                    "datas": base64.b64encode(raw),
                    "mimetype": mimetype,
                    "res_model": "whatsapp.message",
                    "res_id": self.id,
                    "type": "binary",
                }
            )
        )
        self.sudo().write({"attachment_ids": [(4, att.id)]})
        return att

    def can_fetch_media_preview(self):
        self.ensure_one()
        return bool(
            self.evolution_message_id
            and self.has_media
            and (self.media_kind or "none") not in ("none", "reaction")
        )

    def action_fetch_media_preview(self):
        """RPC for chat UI: ensure media cached and return preview URL."""
        self.ensure_one()
        att = self.ensure_media_attachment()
        if not att:
            return {"ok": False, "error": "no_media", "preview_url": False}
        return {
            "ok": True,
            "attachment_id": att.id,
            "mimetype": att.mimetype,
            "preview_url": f"/web/content/{att.id}?download=false",
            "media_kind": self.media_kind,
        }

    def _attach_ingest_media(self, payload):
        """Phase 3: store media from ingest payload onto this message."""
        import base64
        import urllib.request

        self.ensure_one()
        media_b64 = payload.get("media_base64") or payload.get("file_base64")
        media_url = payload.get("media_url") or payload.get("file_url")
        media_type = (
            payload.get("media_type")
            or payload.get("media_kind")
            or self.media_kind
            or "unknown"
        )
        filename = (
            payload.get("media_filename")
            or payload.get("filename")
            or f"wa_ingest_{self.id}"
        )
        mimetype = payload.get("mimetype") or payload.get("media_mimetype") or False
        raw = None
        if media_b64:
            if isinstance(media_b64, str) and media_b64.startswith("data:") and "," in media_b64:
                header, media_b64 = media_b64.split(",", 1)
                if ":" in header and ";" in header and not mimetype:
                    mimetype = header.split(":", 1)[1].split(";", 1)[0]
            raw = base64.b64decode(media_b64)
        elif media_url:
            try:
                with urllib.request.urlopen(media_url, timeout=60) as resp:
                    raw = resp.read()
                    if not mimetype:
                        mimetype = resp.headers.get_content_type()
            except Exception as exc:
                _logger.warning(
                    "whatsapp_hub ingest media_url fetch failed message=%s: %s",
                    self.id,
                    exc,
                )
                return False
        if not raw:
            return False
        if not mimetype:
            mimetype = "application/octet-stream"
        att = (
            self.env["ir.attachment"]
            .sudo()
            .create(
                {
                    "name": filename,
                    "datas": base64.b64encode(raw),
                    "mimetype": mimetype,
                    "res_model": "whatsapp.message",
                    "res_id": self.id,
                    "type": "binary",
                }
            )
        )
        refs = self.attachment_references or ""
        if f"media_type={media_type}" not in (refs or ""):
            refs = (refs + f"\nmedia_type={media_type}").strip() if refs else f"media_type={media_type}"
        vals = {
            "attachment_ids": [(4, att.id)],
            "attachment_references": refs,
            "has_media": True,
        }
        if self.media_kind in ("none", False) or not self.media_kind:
            classified = self._classify_media_kind(
                self.body or "", refs, self.raw_payload or ""
            )
            if classified == "none" and media_type in (
                "image",
                "video",
                "audio",
                "document",
                "sticker",
            ):
                classified = media_type
            vals["media_kind"] = classified
            vals["has_media"] = classified != "none"
        self.sudo().write(vals)
        return True

    def _apply_media_classification(self):
        for rec in self:
            kind = self._classify_media_kind(
                rec.body or "",
                rec.attachment_references or "",
                rec.raw_payload or "",
            )
            vals = {"media_kind": kind, "has_media": kind != "none"}
            super(WhatsappMessage, rec).write(vals)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if "media_kind" not in vals:
                kind = self._classify_media_kind(
                    vals.get("body") or "",
                    vals.get("attachment_references") or "",
                    vals.get("raw_payload") or "",
                )
                vals["media_kind"] = kind
                vals["has_media"] = kind != "none"
        return super().create(vals_list)

    def write(self, vals):
        res = super().write(vals)
        if any(k in vals for k in ("body", "attachment_references", "raw_payload")):
            to_fix = self.browse(self.ids)
            for rec in to_fix:
                kind = self._classify_media_kind(
                    rec.body or "",
                    rec.attachment_references or "",
                    rec.raw_payload or "",
                )
                if rec.media_kind != kind or rec.has_media != (kind != "none"):
                    super(WhatsappMessage, rec).write(
                        {"media_kind": kind, "has_media": kind != "none"}
                    )
        return res

    def _on_message_ingested(self):
        self.ensure_one()
        self.env["whatsapp.message.event"].sudo().create(
            {
                "message_id": self.id,
                "event_type": "ingested",
                "payload_snapshot": self.raw_payload or "",
            }
        )
        if self.conversation_id and "whatsapp.ingestion.health" in self.env:
            try:
                health = (
                    self.env["whatsapp.ingestion.health"]
                    .sudo()
                    ._get_or_create_for_conversation(self.conversation_id)
                )
                health.record_successful_ingest(self)
            except Exception:
                _logger.warning(
                    "whatsapp_hub ingestion health update failed message=%s",
                    self.id,
                    exc_info=True,
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
    def find_canonical_message(
        self,
        *,
        wa_message_log_id=None,
        business_key=None,
        provider=None,
        instance_reference=None,
        provider_message_id=None,
        evolution_message_id=None,
        related_model=None,
        related_res_id=None,
        client_request_id=None,
        chatwoot_message_id=None,
        dedupe_key=None,
    ):
        """Locate an existing canonical message using stable keys (no create)."""
        Message = self.sudo()
        if wa_message_log_id:
            found = Message.search(
                [("wa_message_log_id", "=", int(wa_message_log_id))], limit=1
            )
            if found:
                return found
        key = business_key or build_business_key(
            source_model=related_model,
            source_res_id=related_res_id,
            client_request_id=client_request_id,
            wa_message_log_id=wa_message_log_id,
        )
        if key:
            found = Message.search([("business_key", "=", key)], limit=1)
            if found:
                return found
        evo_id = evolution_message_id or provider_message_id
        if provider == "evolution" and evo_id and instance_reference:
            found = Message.search(
                [
                    ("provider", "=", "evolution"),
                    ("instance_reference", "=", instance_reference),
                    ("provider_message_id", "=", str(evo_id)),
                ],
                limit=1,
            )
            if found:
                return found
        if evo_id:
            found = Message.search(
                [
                    "|",
                    ("evolution_message_id", "=", str(evo_id)),
                    ("provider_message_id", "=", str(evo_id)),
                ],
                limit=1,
            )
            if found:
                return found
        if chatwoot_message_id:
            found = Message.search(
                [("chatwoot_message_id", "=", int(chatwoot_message_id))], limit=1
            )
            if found:
                return found
        if dedupe_key:
            found = Message.search([("dedupe_key", "=", dedupe_key)], limit=1)
            if found:
                return found
        return Message.browse()

    def apply_delivery_status(self, status, *, error_message=None, timestamps=None):
        """Update delivery/state forward-only from a legacy/provider status string."""
        self.ensure_one()
        mapping = {
            "PENDING": "pending",
            "pending": "pending",
            "QUEUED": "pending",
            "queued": "pending",
            "SERVER_ACK": "sent",
            "SENT": "sent",
            "sent": "sent",
            "DELIVERY_ACK": "delivered",
            "DELIVERED": "delivered",
            "delivered": "delivered",
            "READ": "read",
            "PLAYED": "read",
            "read": "read",
            "ERROR": "failed",
            "FAILED": "failed",
            "failed": "failed",
            "received": "delivered",
        }
        delivery = mapping.get((status or "").strip(), False)
        if not delivery:
            return False
        current = self.delivery_state or "pending"
        # Allow failed to overwrite; otherwise only move forward (except failed sticks)
        if (
            current != "failed"
            and delivery != "failed"
            and _DELIVERY_RANK.get(delivery, 0) < _DELIVERY_RANK.get(current, 0)
        ):
            return False
        vals = {"delivery_state": delivery}
        if delivery == "pending":
            vals["state"] = "queued" if self.direction == "out" else "received"
        elif delivery == "sent":
            vals["state"] = "sent"
        elif delivery == "delivered":
            vals["state"] = "delivered" if self.direction == "out" else "received"
        elif delivery == "read":
            vals["state"] = "read"
        elif delivery == "failed":
            vals["state"] = "failed"
        ts = timestamps or {}
        now = fields.Datetime.now()
        if delivery == "sent" and not self.sent_at:
            vals["sent_at"] = ts.get("sent_at") or now
        if delivery == "delivered" and not self.delivered_at:
            vals["delivered_at"] = ts.get("delivered_at") or now
        if delivery == "read" and not self.read_at:
            vals["read_at"] = ts.get("read_at") or now
        if error_message:
            vals["error_message"] = _clean(error_message, 2000)
        elif delivery != "failed":
            # clear stale error on recovery only if explicitly re-sent path sets it
            pass
        self.with_context(whatsapp_hub_mirroring=True).write(vals)
        self.env["whatsapp.message.event"].sudo().create(
            {
                "message_id": self.id,
                "event_type": "status_update",
                "payload_snapshot": json.dumps(
                    {"status": status, "delivery": delivery}, default=str
                ),
            }
        )
        return True

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
        has_media_payload = bool(
            payload.get("media_base64")
            or payload.get("file_base64")
            or payload.get("media_url")
            or payload.get("file_url")
            or payload.get("media_type")
            or payload.get("attachment_references")
        )
        if not text and not payload.get("allow_empty") and not has_media_payload:
            return {"skipped": True, "reason": "empty_text"}
        if not text and has_media_payload:
            media_type = payload.get("media_type") or payload.get("media_kind") or "media"
            text = f"[{media_type}]"

        dedupe = _dedupe_key(payload)
        existing = self.find_canonical_message(
            chatwoot_message_id=chatwoot_message_id,
            evolution_message_id=evolution_message_id or None,
            provider="evolution" if evolution_message_id and not chatwoot_message_id else None,
            instance_reference=_clean(
                payload.get("instance_reference") or payload.get("evolution_instance"),
                200,
            )
            or None,
            provider_message_id=evolution_message_id or None,
            dedupe_key=dedupe,
            business_key=(
                f"chatwoot:{int(payload.get('chatwoot_account_id') or payload.get('account_id') or 0)}:"
                f"{int(chatwoot_message_id)}"
                if chatwoot_message_id
                else False
            ),
        )
        if existing:
            enrich = {}
            if evolution_message_id and not existing.evolution_message_id:
                enrich["evolution_message_id"] = evolution_message_id
                if not existing.provider_message_id:
                    enrich["provider_message_id"] = evolution_message_id
            if enrich:
                existing.with_context(whatsapp_hub_mirroring=True).sudo().write(enrich)
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

        remote = _normalize_remote_jid(group_jid or sender_jid)
        account = int(payload.get("chatwoot_account_id") or payload.get("account_id") or 0)
        business_key = (
            f"chatwoot:{account}:{int(chatwoot_message_id)}"
            if chatwoot_message_id
            else (
                f"evo:{instance_ref or 'default'}:{evolution_message_id}"
                if evolution_message_id
                else False
            )
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
                "business_key": business_key or False,
                "evolution_message_id": evolution_message_id or False,
                "chatwoot_account_id": account or False,
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
                "remote_jid": remote or False,
                "source_app": "n8n",
                "purpose": "chatwoot",
                "attachment_references": _clean(
                    payload.get("attachment_references")
                    or (
                        f"media_type={payload.get('media_type')}"
                        if payload.get("media_type")
                        else ""
                    ),
                    4000,
                )
                or False,
                "raw_payload": json.dumps(payload, ensure_ascii=False, default=str),
            }
        )
        conversation.write({"last_message_at": ts})
        try:
            message._attach_ingest_media(payload)
        except Exception:
            _logger.exception(
                "whatsapp_hub ingest media attach failed message=%s", message.id
            )
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
            "has_media": bool(message.has_media),
            "media_kind": message.media_kind,
        }

    @api.model
    def update_delivery_status(self, evolution_message_id, status):
        """Map Evolution delivery webhook status onto hub messages."""
        if not evolution_message_id:
            return False
        messages = self.sudo().search(
            [
                "|",
                ("evolution_message_id", "=", evolution_message_id),
                ("provider_message_id", "=", evolution_message_id),
            ]
        )
        if not messages:
            return False
        ok = False
        for msg in messages:
            if msg.apply_delivery_status(status):
                ok = True
        return ok
