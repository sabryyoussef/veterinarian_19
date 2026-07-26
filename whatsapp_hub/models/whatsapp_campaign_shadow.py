# -*- coding: utf-8 -*-
"""P5C: Campaign shadow-mode comparison evidence (observe only — never Hub-send)."""
from __future__ import annotations

import hashlib
import json
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class WhatsappCampaignShadow(models.Model):
    _name = "whatsapp.campaign.shadow"
    _description = "WhatsApp Campaign Shadow Comparison"
    _order = "id desc"

    name = fields.Char(required=True)
    classification = fields.Selection(
        [
            ("matched", "Matched"),
            ("unsupported_message_type", "Unsupported Message Type"),
            ("missing_instance", "Missing Instance"),
            ("invalid_destination", "Invalid Destination"),
            ("has_attachments", "Has Attachments (media blocked)"),
            ("body_mismatch", "Body Mismatch"),
            ("instance_mismatch", "Instance Mismatch"),
            ("destination_mismatch", "Destination Mismatch"),
            ("campaign_identity_mismatch", "Campaign Identity Mismatch"),
            ("provenance_mismatch", "Provenance Mismatch"),
            ("conversation_mismatch", "Conversation Mismatch"),
            ("legacy_queue_limited_evidence", "Legacy Queue Limited Evidence"),
            ("validation_error", "Validation Error"),
            ("legacy_only", "Legacy Only / Preview Skipped"),
            ("replay_skipped", "Replay Skipped (already shadow-sent)"),
        ],
        default="validation_error",
        required=True,
        index=True,
    )
    eligible = fields.Boolean(default=False)
    campaign_id = fields.Integer(index=True)
    campaign_line_id = fields.Integer(index=True)
    partner_id = fields.Many2one("res.partner", ondelete="set null", index=True)
    lead_id = fields.Integer(index=True)
    destination = fields.Char()
    normalized_jid = fields.Char()
    candidate_instance_reference = fields.Char()
    actual_instance_reference = fields.Char()
    candidate_business_key = fields.Char(index=True)
    actual_business_key = fields.Char(
        help="Legacy mirror often uses walog:{id}; not compared to campaign:* for match."
    )
    candidate_destination = fields.Char()
    actual_remote_jid = fields.Char()
    candidate_purpose = fields.Char()
    actual_purpose = fields.Char()
    candidate_body_preview = fields.Char()
    actual_body_preview = fields.Char()
    candidate_body_hash = fields.Char()
    actual_body_hash = fields.Char()
    legacy_transport = fields.Selection(
        [
            ("immediate", "Immediate (_send_via_evolution)"),
            ("bridge_queue", "Bridge outbound queue"),
            ("none", "No legacy send"),
        ],
        default="none",
        index=True,
    )
    legacy_provider_message_id = fields.Char()
    legacy_queue_id = fields.Integer(index=True)
    wa_message_log_id = fields.Integer(index=True)
    mirrored_message_id = fields.Many2one(
        "whatsapp.message", ondelete="set null", index=True
    )
    legacy_send_completed = fields.Boolean(
        default=False,
        index=True,
        help="True after a successful legacy shadow send for this line (replay guard).",
    )
    mismatch_reason = fields.Text()
    preview_payload = fields.Text()
    notes = fields.Text()

    @api.model
    def _body_hash(self, text):
        raw = (text or "").strip().encode("utf-8")
        return hashlib.sha256(raw).hexdigest()[:32]

    @api.model
    def find_completed_for_line(self, campaign_line_id):
        return self.sudo().search(
            [
                ("campaign_line_id", "=", int(campaign_line_id)),
                ("legacy_send_completed", "=", True),
            ],
            order="id desc",
            limit=1,
        )

    @api.model
    def classify_and_record(
        self,
        *,
        campaign,
        line,
        preview,
        legacy_transport="none",
        wa_log=None,
        mirrored_message=None,
        legacy_provider_message_id=None,
        legacy_queue_id=None,
        legacy_send_ok=False,
        notes=None,
        force_classification=None,
    ):
        """
        Persist or update shadow evidence after legacy Campaign send.

        Never creates Hub outbound jobs or reserves sendable campaign:* rows.
        Does not treat walog:* vs campaign:* business_key as a mismatch.
        """
        candidate = (preview or {}).get("candidate") or {}
        classification = force_classification or (preview or {}).get("classification") or "validation_error"
        eligible = bool((preview or {}).get("eligible"))
        mismatch_parts = list((preview or {}).get("errors") or [])

        mirrored = mirrored_message
        actual_business = False
        actual_purpose = False
        actual_remote = False
        actual_inst = False
        actual_body = False
        if mirrored:
            actual_business = mirrored.business_key or False
            actual_purpose = mirrored.purpose or False
            actual_remote = mirrored.remote_jid or False
            actual_inst = mirrored.instance_reference or False
            actual_body = (mirrored.body or "")[:500] or False
        if wa_log:
            if not actual_body:
                actual_body = (wa_log.message_text or "")[:500] or False
            if not actual_remote:
                actual_remote = (wa_log.phone or "").strip() or False
            if getattr(wa_log, "wa_message_id", False):
                legacy_provider_message_id = (
                    legacy_provider_message_id or wa_log.wa_message_id
                )

        cand_body = candidate.get("body") or line.message or ""
        cand_hash = self._body_hash(cand_body)
        act_hash = self._body_hash(actual_body) if actual_body else False

        if force_classification:
            classification = force_classification
        elif legacy_transport == "bridge_queue" and not wa_log and not mirrored:
            classification = "legacy_queue_limited_evidence"
            mismatch_parts.append(
                "queue-mode: provider/log evidence not available at enqueue time"
            )
        elif eligible and (mirrored or wa_log):
            # Destination
            cand_dest = "".join(
                c for c in (candidate.get("destination") or "") if c.isdigit()
            )
            act_digits = "".join(
                c for c in (actual_remote or "") if c.isdigit()
            )
            if cand_dest and act_digits and cand_dest not in act_digits and act_digits not in cand_dest:
                classification = "destination_mismatch"
                mismatch_parts.append(
                    f"destination candidate={cand_dest} actual={act_digits}"
                )
            # Purpose (only when Hub mirror present — legacy-first may use walog:*)
            if mirrored and candidate.get("purpose") and actual_purpose:
                if candidate["purpose"] != actual_purpose:
                    classification = "provenance_mismatch"
                    mismatch_parts.append(
                        f"purpose candidate={candidate['purpose']} actual={actual_purpose}"
                    )
            # Campaign line identity on log
            if wa_log:
                log_cid = wa_log.campaign_id.id if wa_log.campaign_id else False
                log_lid = (
                    wa_log.campaign_line_id.id if wa_log.campaign_line_id else False
                )
                if log_cid and log_cid != campaign.id:
                    classification = "campaign_identity_mismatch"
                    mismatch_parts.append("wa.message.log campaign_id mismatch")
                if log_lid and log_lid != line.id:
                    classification = "campaign_identity_mismatch"
                    mismatch_parts.append("wa.message.log campaign_line_id mismatch")
            # Body
            if actual_body and cand_body:
                # Compare stripped plain text loosely
                if cand_hash != act_hash and (cand_body.strip() not in (actual_body or "")):
                    # Allow HTML wrapping differences
                    from re import sub

                    def _plain(t):
                        return sub(r"<[^>]+>", "", t or "").strip()

                    if _plain(cand_body) != _plain(actual_body):
                        classification = "body_mismatch"
                        mismatch_parts.append("rendered body differs from legacy log/mirror")
            # Instance (informational when both present)
            if (
                mirrored
                and candidate.get("instance_reference")
                and actual_inst
                and candidate["instance_reference"] != actual_inst
            ):
                classification = "instance_mismatch"
                mismatch_parts.append(
                    f"instance candidate={candidate['instance_reference']} "
                    f"actual={actual_inst}"
                )
            if classification in ("matched", "validation_error") and not mismatch_parts:
                classification = "matched"
        elif eligible and legacy_transport == "immediate" and legacy_send_ok and not wa_log and not mirrored:
            classification = "validation_error"
            mismatch_parts.append("immediate legacy send produced no wa.message.log")
        elif eligible and not force_classification and classification in ("matched", "validation_error"):
            # Preview-only evidence (no legacy send yet)
            if legacy_transport == "none" and not legacy_send_ok:
                classification = "matched" if eligible else classification
                mismatch_parts = []

        vals = {
            "name": f"Campaign {campaign.id} line {line.id} {classification}"[:200],
            "classification": classification,
            "eligible": eligible,
            "campaign_id": campaign.id,
            "campaign_line_id": line.id,
            "partner_id": line.partner_id.id if line.partner_id else False,
            "lead_id": line.lead_id.id if line.lead_id else False,
            "destination": candidate.get("destination") or line.phone or False,
            "normalized_jid": candidate.get("remote_jid") or False,
            "candidate_instance_reference": candidate.get("instance_reference") or False,
            "actual_instance_reference": actual_inst,
            "candidate_business_key": candidate.get("business_key") or False,
            "actual_business_key": actual_business,
            "candidate_destination": candidate.get("destination") or False,
            "actual_remote_jid": actual_remote,
            "candidate_purpose": candidate.get("purpose") or False,
            "actual_purpose": actual_purpose,
            "candidate_body_preview": (cand_body or "")[:200] or False,
            "actual_body_preview": (actual_body or "")[:200] or False,
            "candidate_body_hash": cand_hash,
            "actual_body_hash": act_hash or False,
            "legacy_transport": legacy_transport,
            "legacy_provider_message_id": legacy_provider_message_id or False,
            "legacy_queue_id": int(legacy_queue_id) if legacy_queue_id else False,
            "wa_message_log_id": wa_log.id if wa_log else False,
            "mirrored_message_id": mirrored.id if mirrored else False,
            "legacy_send_completed": bool(legacy_send_ok),
            "mismatch_reason": "\n".join(mismatch_parts) if mismatch_parts else False,
            "preview_payload": json.dumps(preview or {}, default=str)[:8000],
            "notes": notes or False,
        }

        # Replay evidence is append-only so prior matched rows stay queryable.
        if force_classification == "replay_skipped":
            return self.sudo().create(vals)

        existing = self.sudo().search(
            [("campaign_line_id", "=", line.id)], order="id desc", limit=1
        )
        if existing and existing.classification != "replay_skipped":
            existing.write(vals)
            return existing
        return self.sudo().create(vals)

    @api.model
    def reconcile_queue_evidence(self, campaign_line_id):
        """
        Optional later update when bridge queue completes and wa.message.log appears.

        Does not re-send. Upgrades legacy_queue_limited_evidence when log/mirror exists.
        """
        rec = self.sudo().search(
            [("campaign_line_id", "=", int(campaign_line_id))],
            order="id desc",
            limit=1,
        )
        if not rec or rec.classification not in (
            "legacy_queue_limited_evidence",
            "validation_error",
        ):
            return rec
        if "wa.message.log" not in self.env:
            return rec
        wa_log = self.env["wa.message.log"].sudo().search(
            [("campaign_line_id", "=", int(campaign_line_id))],
            order="id desc",
            limit=1,
        )
        if not wa_log:
            return rec
        campaign = self.env["wa.campaign"].sudo().browse(rec.campaign_id)
        line = self.env["wa.campaign.line"].sudo().browse(rec.campaign_line_id)
        if not campaign.exists() or not line.exists():
            return rec
        Routing = self.env["whatsapp.campaign.hub.routing"]
        preview = Routing.service_preview_campaign_line(campaign, line)
        return self.classify_and_record(
            campaign=campaign,
            line=line,
            preview=preview,
            legacy_transport=rec.legacy_transport or "bridge_queue",
            wa_log=wa_log,
            mirrored_message=wa_log.hub_message_id or None,
            legacy_provider_message_id=wa_log.wa_message_id,
            legacy_queue_id=rec.legacy_queue_id,
            legacy_send_ok=True,
            notes=(rec.notes or "") + "\n[reconciled after bridge completion]",
        )

    # Back-compat alias used by P5B wiring
    @api.model
    def record_from_preview(
        self,
        *,
        campaign,
        line,
        preview,
        wa_log=None,
        mirrored_message=None,
        notes=None,
        **kwargs,
    ):
        return self.classify_and_record(
            campaign=campaign,
            line=line,
            preview=preview,
            wa_log=wa_log,
            mirrored_message=mirrored_message,
            notes=notes,
            legacy_transport=kwargs.get("legacy_transport") or "none",
            legacy_provider_message_id=kwargs.get("legacy_provider_message_id"),
            legacy_queue_id=kwargs.get("legacy_queue_id"),
            legacy_send_ok=kwargs.get("legacy_send_ok", False),
            force_classification=kwargs.get("force_classification"),
        )
