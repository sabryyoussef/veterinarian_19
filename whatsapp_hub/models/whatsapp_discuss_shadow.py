# -*- coding: utf-8 -*-
"""Phase 4A: Discuss shadow-mode comparison evidence (no transport)."""
from odoo import api, fields, models


class WhatsappDiscussShadow(models.Model):
    _name = "whatsapp.discuss.shadow"
    _description = "WhatsApp Discuss Shadow Comparison"
    _order = "id desc"

    name = fields.Char(required=True)
    classification = fields.Selection(
        [
            ("matched", "Matched"),
            ("unsupported_message_type", "Unsupported Message Type"),
            ("missing_instance", "Missing Instance"),
            ("invalid_destination", "Invalid Destination"),
            ("provenance_mismatch", "Provenance Mismatch"),
            ("conversation_mismatch", "Conversation Mismatch"),
            ("canonical_identity_mismatch", "Canonical Identity Mismatch"),
            ("validation_error", "Validation Error"),
            ("legacy_only", "Legacy Only / Preview Skipped"),
        ],
        default="validation_error",
        required=True,
        index=True,
    )
    eligible = fields.Boolean(default=False)
    channel_id = fields.Integer(index=True)
    mail_message_id = fields.Integer(index=True)
    partner_id = fields.Many2one("res.partner", ondelete="set null", index=True)
    wa_message_log_id = fields.Integer(index=True)
    mirrored_message_id = fields.Many2one(
        "whatsapp.message", ondelete="set null", index=True
    )
    expected_conversation_identity_key = fields.Char()
    actual_conversation_identity_key = fields.Char()
    actual_conversation_id = fields.Many2one(
        "whatsapp.conversation", ondelete="set null"
    )
    candidate_business_key = fields.Char(index=True)
    actual_business_key = fields.Char()
    candidate_destination = fields.Char()
    actual_remote_jid = fields.Char()
    candidate_purpose = fields.Char()
    actual_purpose = fields.Char()
    candidate_instance_reference = fields.Char()
    actual_instance_reference = fields.Char()
    mismatch_reason = fields.Text()
    preview_payload = fields.Text()
    notes = fields.Text()

    @api.model
    def record_from_preview(
        self,
        *,
        channel,
        mail_message,
        partner,
        preview,
        wa_log=None,
        mirrored_message=None,
        notes=None,
    ):
        """Persist shadow comparison after a legacy Discuss send."""
        candidate = (preview or {}).get("candidate") or {}
        classification = (preview or {}).get("classification") or "validation_error"
        eligible = bool((preview or {}).get("eligible"))
        mirrored = mirrored_message
        actual_identity = False
        actual_business = False
        actual_purpose = False
        actual_remote = False
        actual_inst = False
        conv = self.env["whatsapp.conversation"].browse()
        if mirrored:
            conv = mirrored.conversation_id
            actual_identity = conv.identity_key if conv else False
            actual_business = mirrored.business_key or False
            actual_purpose = mirrored.purpose or False
            actual_remote = mirrored.remote_jid or False
            actual_inst = mirrored.instance_reference or False

        mismatch_parts = list((preview or {}).get("errors") or [])
        if eligible and mirrored:
            if candidate.get("business_key") and actual_business:
                # After legacy mirror, business_key is walog:* — compare destination/purpose/conversation
                if candidate.get("expected_conversation_identity_key") and actual_identity:
                    if (
                        candidate["expected_conversation_identity_key"]
                        != actual_identity
                    ):
                        classification = "conversation_mismatch"
                        mismatch_parts.append(
                            "expected conversation identity != mirrored conversation"
                        )
                if candidate.get("purpose") and actual_purpose:
                    if candidate["purpose"] != actual_purpose:
                        classification = "provenance_mismatch"
                        mismatch_parts.append(
                            f"purpose candidate={candidate['purpose']} actual={actual_purpose}"
                        )
                if candidate.get("remote_jid") and actual_remote:
                    if candidate["remote_jid"] != actual_remote:
                        classification = "provenance_mismatch"
                        mismatch_parts.append("remote_jid mismatch")
                if (
                    classification
                    in (
                        "matched",
                        "validation_error",
                    )
                    and not mismatch_parts
                ):
                    classification = "matched"
            elif eligible and not mirrored:
                classification = "canonical_identity_mismatch"
                mismatch_parts.append("no mirrored Hub message after legacy send")
        elif eligible and not mirrored:
            classification = "canonical_identity_mismatch"
            mismatch_parts.append("no mirrored Hub message after legacy send")

        import json

        name = (
            f"Shadow ch={channel.id if channel else 0} "
            f"msg={mail_message.id if mail_message else 0}"
        )
        return self.sudo().create(
            {
                "name": name,
                "classification": classification,
                "eligible": eligible,
                "channel_id": channel.id if channel else False,
                "mail_message_id": mail_message.id if mail_message else False,
                "partner_id": partner.id if partner else False,
                "wa_message_log_id": wa_log.id if wa_log else False,
                "mirrored_message_id": mirrored.id if mirrored else False,
                "expected_conversation_identity_key": candidate.get(
                    "expected_conversation_identity_key"
                )
                or False,
                "actual_conversation_identity_key": actual_identity or False,
                "actual_conversation_id": conv.id if conv else False,
                "candidate_business_key": candidate.get("business_key") or False,
                "actual_business_key": actual_business or False,
                "candidate_destination": candidate.get("destination") or False,
                "actual_remote_jid": actual_remote or False,
                "candidate_purpose": candidate.get("purpose") or False,
                "actual_purpose": actual_purpose or False,
                "candidate_instance_reference": candidate.get("instance_reference")
                or False,
                "actual_instance_reference": actual_inst or False,
                "mismatch_reason": "\n".join(mismatch_parts) if mismatch_parts else False,
                "preview_payload": json.dumps(preview or {}, default=str)[:8000],
                "notes": notes or False,
            }
        )
