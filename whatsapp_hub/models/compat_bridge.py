# -*- coding: utf-8 -*-
"""Compatibility helpers when legacy modules are installed alongside the hub.

Phase 2: observational mirror only — never triggers outbound WhatsApp sends.
"""
from __future__ import annotations

import hashlib
import logging

from odoo import api, fields, models

from .whatsapp_conversation import _normalize_remote_jid
from .whatsapp_message import (
    build_business_key,
    campaign_business_key,
    discuss_business_key,
    _clean,
)

_logger = logging.getLogger(__name__)

_STATUS_TO_HUB = {
    "pending": "pending",
    "sent": "sent",
    "delivered": "delivered",
    "read": "read",
    "failed": "failed",
}


class WhatsappHubCompat(models.AbstractModel):
    _name = "whatsapp.hub.compat"
    _description = "WhatsApp Hub Compatibility Helpers"

    @api.model
    def _skip_mirror(self):
        """Skip only when explicitly asked — not while performing a mirror write."""
        return bool(self.env.context.get("whatsapp_hub_skip_mirror"))

    @api.model
    def _resolve_campaign_refs(self, wa_log):
        campaign_id = False
        campaign_line_id = False
        camp = getattr(wa_log, "campaign_id", False)
        if camp:
            campaign_id = camp.id if hasattr(camp, "id") else int(camp)
        line_f = getattr(wa_log, "campaign_line_id", False)
        if line_f:
            campaign_line_id = line_f.id if hasattr(line_f, "id") else int(line_f)
        if campaign_id or campaign_line_id:
            return campaign_id, campaign_line_id
        if "wa.campaign.line" not in self.env:
            return False, False
        Line = self.env["wa.campaign.line"].sudo()
        line = Line.browse()
        if wa_log.wa_message_id:
            line = Line.search([("wa_message_id", "=", wa_log.wa_message_id)], limit=1)
        if not line and wa_log.queue_id:
            line = Line.search([("queue_id", "=", wa_log.queue_id.id)], limit=1)
        if line:
            return line.campaign_id.id, line.id
        return False, False

    @api.model
    def _resolve_instance(self, wa_log):
        """Best-effort instance without exposing credentials on Hub rows."""
        Instance = self.env["whatsapp.instance"].sudo()
        purpose = "crm"
        camp = getattr(wa_log, "campaign_id", False)
        line_f = getattr(wa_log, "campaign_line_id", False)
        if camp or line_f:
            purpose = "campaign"
        rec = Instance.search([("purpose", "=", purpose), ("active", "=", True)], limit=1)
        if not rec:
            rec = Instance.search([("is_default", "=", True), ("active", "=", True)], limit=1)
        if not rec:
            rec = Instance.search([("active", "=", True)], limit=1)
        if rec:
            return rec, rec.instance_name
        Evo = self.env.get("evolution.instance")
        if Evo is not None:
            evo = Evo.sudo().get_default_config()
            name = (evo or {}).get("instance") or False
            return Instance.browse(), name
        return Instance.browse(), False

    @api.model
    def _purpose_for_log(self, wa_log, campaign_id=False):
        if campaign_id:
            return "campaign"
        # Phase 4: Partner Discuss channels use purpose=discuss (stable with Hub cutover).
        if wa_log.channel_id:
            return "discuss"
        if wa_log.partner_id or wa_log.lead_id:
            return "crm"
        return "other"

    @api.model
    def _source_app_for_log(self, wa_log, campaign_id=False):
        if campaign_id:
            return "campaign"
        if wa_log.channel_id:
            return "discuss"
        return "mirror"

    @api.model
    def _vals_from_wa_log(self, wa_log, conversation, contact, instance, instance_ref):
        campaign_id, campaign_line_id = self._resolve_campaign_refs(wa_log)
        purpose = self._purpose_for_log(wa_log, campaign_id)
        source_app = self._source_app_for_log(wa_log, campaign_id)
        remote = _normalize_remote_jid(wa_log.phone)
        direction = wa_log.direction or "out"
        delivery = _STATUS_TO_HUB.get(wa_log.delivery_status or "pending", "pending")
        if direction == "in":
            state = "received"
            if delivery == "pending":
                delivery = "delivered"
        else:
            state = {
                "pending": "queued",
                "sent": "sent",
                "delivered": "delivered",
                "read": "read",
                "failed": "failed",
            }.get(delivery, "queued")

        related_model = False
        related_res_id = False
        if campaign_line_id:
            related_model = "wa.campaign.line"
            related_res_id = campaign_line_id
        elif wa_log.lead_id:
            related_model = "crm.lead"
            related_res_id = wa_log.lead_id.id
        elif wa_log.partner_id:
            related_model = "res.partner"
            related_res_id = wa_log.partner_id.id
        elif wa_log.channel_id:
            related_model = "discuss.channel"
            related_res_id = wa_log.channel_id.id

        business_key = build_business_key(wa_message_log_id=wa_log.id)
        evo_id = (wa_log.wa_message_id or "").strip() or False
        provider_message_id = evo_id or f"walog-{wa_log.id}"
        dedupe = hashlib.sha256(
            f"walog:{wa_log.id}:{evo_id or wa_log.phone or ''}".encode()
        ).hexdigest()

        partner = wa_log.partner_id
        if not partner and contact and contact.partner_id:
            partner = contact.partner_id

        vals = {
            "direction": direction,
            "state": state,
            "delivery_state": delivery,
            "body": wa_log.message_text or "",
            "message_timestamp": wa_log.sent_at or fields.Datetime.now(),
            "conversation_id": conversation.id,
            "contact_id": contact.id if contact else False,
            "instance_id": instance.id if instance else False,
            "instance_reference": instance_ref or False,
            "dedupe_key": dedupe,
            "business_key": business_key,
            "evolution_message_id": evo_id,
            "provider": "evolution",
            "provider_message_id": provider_message_id,
            "remote_jid": remote or False,
            "sender_jid": remote if direction == "in" else False,
            "source_app": source_app,
            "purpose": purpose,
            "related_model": related_model or False,
            "related_res_id": related_res_id or False,
            "client_request_id": f"walog-{wa_log.id}",
            "partner_id": partner.id if partner else False,
            "campaign_id": campaign_id or False,
            "campaign_line_id": campaign_line_id or False,
            "discuss_channel_id": wa_log.channel_id.id if wa_log.channel_id else False,
            "queue_id": wa_log.queue_id.id if wa_log.queue_id else False,
            "wa_message_log_id": wa_log.id,
        }
        if wa_log.has_media:
            vals["attachment_references"] = _clean(
                f"media_type={wa_log.media_type or 'unknown'}", 500
            )
        if delivery == "sent" and wa_log.sent_at:
            vals["sent_at"] = wa_log.sent_at
        if delivery == "delivered" and wa_log.delivered_at:
            vals["delivered_at"] = wa_log.delivered_at
        if delivery == "read" and wa_log.read_at:
            vals["read_at"] = wa_log.read_at
        if delivery == "failed":
            vals["error_message"] = _clean(
                getattr(wa_log, "error_msg", None) or "legacy delivery failed", 2000
            )
        return vals

    @api.model
    def mirror_wa_message_log(self, wa_log):
        """Idempotent mirror of wa.message.log → whatsapp.message (no outbound)."""
        if self._skip_mirror():
            return self.env["whatsapp.message"].browse()
        if not wa_log or "whatsapp.message" not in self.env:
            return self.env["whatsapp.message"].browse()

        Message = self.env["whatsapp.message"].sudo()
        existing = Message.find_canonical_message(
            wa_message_log_id=wa_log.id,
            business_key=build_business_key(wa_message_log_id=wa_log.id),
            provider="evolution",
            evolution_message_id=wa_log.wa_message_id or None,
            provider_message_id=wa_log.wa_message_id or None,
        )
        # Phase 4 Hub-cutover: reuse canonical message created via discuss:* key
        if not existing:
            hub_ref = getattr(wa_log, "hub_message_id", False)
            if hub_ref:
                existing = hub_ref if hasattr(hub_ref, "id") else Message.browse(int(hub_ref))
                if not existing.exists():
                    existing = Message.browse()
        # Phase 5B: prefer campaign:{campaign_id}:{line_id} before walog:* twin
        if not existing:
            camp = getattr(wa_log, "campaign_id", False)
            cline = getattr(wa_log, "campaign_line_id", False)
            cid = camp.id if hasattr(camp, "id") else (int(camp) if camp else 0)
            lid = cline.id if hasattr(cline, "id") else (int(cline) if cline else 0)
            if cid and lid:
                existing = Message.find_canonical_message(
                    business_key=campaign_business_key(cid, lid)
                )
        if not existing and wa_log.channel_id:
            mm = getattr(wa_log, "mail_message_id", False)
            mm_id = mm.id if hasattr(mm, "id") else (int(mm) if mm else 0)
            if mm_id:
                dkey = discuss_business_key(wa_log.channel_id.id, mm_id)
                existing = Message.find_canonical_message(business_key=dkey)
        instance, instance_ref = self._resolve_instance(wa_log)
        # Prefer instance ref from existing if already set
        if existing and existing.instance_reference:
            instance_ref = existing.instance_reference

        campaign_id, _line = self._resolve_campaign_refs(wa_log)
        purpose = self._purpose_for_log(wa_log, campaign_id)
        remote = _normalize_remote_jid(wa_log.phone)

        contact = (
            self.env["whatsapp.contact"]
            .sudo()
            .get_or_create_from_sender(
                phone=wa_log.phone,
                name=wa_log.partner_id.name if wa_log.partner_id else None,
            )
        )
        if wa_log.partner_id and not contact.partner_id:
            contact.sudo().write({"partner_id": wa_log.partner_id.id})

        conversation = (
            self.env["whatsapp.conversation"]
            .sudo()
            .resolve_conversation(
                remote_jid=remote,
                purpose=purpose,
                instance_id=instance.id if instance else False,
                instance_reference=instance_ref or False,
                conversation_type="dm",
                contact=contact,
                partner=wa_log.partner_id,
                name=wa_log.partner_id.name if wa_log.partner_id else wa_log.phone,
            )
        )

        vals = self._vals_from_wa_log(
            wa_log, conversation, contact, instance, instance_ref
        )

        ctx = dict(self.env.context, whatsapp_hub_mirroring=True)
        if existing:
            # Enrich / lifecycle sync — never create a second row
            updates = {}
            enrich_fields = (
                "evolution_message_id",
                "provider_message_id",
                "body",
                "partner_id",
                "campaign_id",
                "campaign_line_id",
                "discuss_channel_id",
                "queue_id",
                "related_model",
                "related_res_id",
                "instance_id",
                "instance_reference",
                "remote_jid",
                "sent_at",
                "delivered_at",
                "read_at",
                "error_message",
                "attachment_references",
                "source_app",
                "purpose",
                "wa_message_log_id",
                "business_key",
            )
            overwrite_if_changed = {
                "campaign_id",
                "campaign_line_id",
                "discuss_channel_id",
                "queue_id",
                "partner_id",
            }
            for field in enrich_fields:
                new_val = vals.get(field)
                if not new_val:
                    continue
                old_val = existing[field]
                old_cmp = old_val.id if hasattr(old_val, "ids") else old_val
                new_cmp = new_val.id if hasattr(new_val, "ids") else new_val
                # Never replace discuss:{channel}:{mail_message} or campaign:* with walog:{id}
                if field == "business_key" and old_cmp and (
                    str(old_cmp).startswith("discuss:")
                    or str(old_cmp).startswith("campaign:")
                ):
                    continue
                if not old_cmp and new_cmp:
                    updates[field] = new_cmp
                elif field in overwrite_if_changed and new_cmp and old_cmp != new_cmp:
                    updates[field] = new_cmp
            if updates:
                existing.with_context(**ctx).write(updates)
            # Status sync via forward-only helper
            existing.apply_delivery_status(
                wa_log.delivery_status or "pending",
                timestamps={
                    "sent_at": wa_log.sent_at,
                    "delivered_at": wa_log.delivered_at,
                    "read_at": wa_log.read_at,
                },
            )
            conversation.write({"last_message_at": fields.Datetime.now()})
            return existing

        message = Message.with_context(**ctx).create(vals)
        conversation.write({"last_message_at": fields.Datetime.now()})
        _logger.info(
            "whatsapp_hub mirrored wa.message.log id=%s → message id=%s",
            wa_log.id,
            message.id,
        )
        return message

    @api.model
    def sync_wa_message_log_status(self, wa_log):
        """Lifecycle sync only (write path). Idempotent; no outbound."""
        if self._skip_mirror():
            return self.env["whatsapp.message"].browse()
        return self.mirror_wa_message_log(wa_log)

    @api.model
    def service_backfill_wa_message_logs(self, limit=200, dry_run=True, since_id=0):
        """
        Explicit admin/manual backfill. Never auto-run on upgrade.

        Returns stats dict. dry_run=True only reports candidates.
        """
        if "wa.message.log" not in self.env:
            return {"ok": False, "reason": "wa.message.log missing"}
        Log = self.env["wa.message.log"].sudo()
        Message = self.env["whatsapp.message"].sudo()
        domain = [("id", ">", int(since_id or 0))]
        logs = Log.search(domain, order="id asc", limit=int(limit or 200))
        missing = []
        for log in logs:
            exists = Message.search([("wa_message_log_id", "=", log.id)], limit=1)
            if not exists:
                missing.append(log.id)
        result = {
            "ok": True,
            "scanned": len(logs),
            "missing": len(missing),
            "missing_ids": missing[:50],
            "dry_run": bool(dry_run),
            "mirrored": 0,
        }
        if dry_run or not missing:
            return result
        mirrored = 0
        for log_id in missing:
            log = Log.browse(log_id)
            try:
                msg = self.mirror_wa_message_log(log)
                if msg:
                    mirrored += 1
            except Exception:
                _logger.exception("backfill mirror failed for wa.message.log %s", log_id)
        result["mirrored"] = mirrored
        return result
