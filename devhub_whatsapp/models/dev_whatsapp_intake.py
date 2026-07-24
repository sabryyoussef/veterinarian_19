# -*- coding: utf-8 -*-
"""Controlled WhatsApp → Dev Hub intake candidates and ingest RPC."""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

_logger = logging.getLogger(__name__)

CLASSIFICATIONS = [
    ("new_dev_request", "New development request"),
    ("context_addition", "Additional information"),
    ("follow_up_existing", "Existing task follow-up"),
    ("bug_report", "Bug report"),
    ("question", "Question"),
    ("status_request", "Status request"),
    ("approval", "Approval"),
    ("rejection", "Rejection"),
    ("unrelated", "Unrelated discussion"),
    ("noise", "Noise"),
]


def _require_intake_service(env):
    if not env.is_superuser() and not env.user.has_group(
        "devhub_whatsapp.group_dev_hub_whatsapp_intake"
    ):
        raise AccessError(
            "This operation requires the scoped Dev Hub WhatsApp Intake Service role."
        )


def _clean(value, limit=6000):
    text = (value or "").strip()
    if len(text) > limit:
        text = text[: limit - 20] + "\n...[truncated]..."
    return text


def _hash(payload):
    raw = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class DevWhatsappIntake(models.Model):
    _name = "dev.whatsapp.intake"
    _description = "Dev Hub WhatsApp Intake Candidate"
    _order = "id desc"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    name = fields.Char(required=True, tracking=True)
    source_id = fields.Many2one(
        "dev.whatsapp.source", required=True, ondelete="restrict", index=True
    )
    dev_project_id = fields.Many2one(
        related="source_id.dev_project_id", store=True, index=True
    )
    state = fields.Selection(
        [
            ("received", "Received"),
            ("collecting", "Collecting Context"),
            ("draft_ready", "Draft Ready"),
            ("awaiting_confirm", "Awaiting Confirmation"),
            ("confirmed", "Confirmed"),
            ("rejected", "Rejected"),
            ("merged", "Merged"),
            ("abandoned", "Abandoned"),
        ],
        default="received",
        required=True,
        tracking=True,
        index=True,
    )
    classification = fields.Selection(CLASSIFICATIONS, index=True)
    confidence = fields.Float()
    grouping_key = fields.Char(index=True, copy=False)
    chatwoot_account_id = fields.Integer(index=True)
    chatwoot_inbox_id = fields.Integer()
    chatwoot_conversation_id = fields.Integer(index=True)
    group_jid = fields.Char(index=True)
    primary_sender_jid = fields.Char()
    draft_summary = fields.Text()
    draft_problem = fields.Text()
    draft_current_behavior = fields.Text()
    draft_expected_behavior = fields.Text()
    draft_acceptance_criteria = fields.Text()
    draft_missing_information = fields.Text()
    draft_urgency = fields.Selection(
        [("low", "Low"), ("normal", "Normal"), ("high", "High")],
        default="normal",
    )
    draft_json = fields.Text(help="Structured AI draft payload (JSON).")
    source_message_ids = fields.Many2many(
        "dev.work.source.message",
        "dev_whatsapp_intake_source_message_rel",
        "intake_id",
        "source_message_id",
        string="Source Messages",
    )
    work_item_id = fields.Many2one("dev.work.item", ondelete="set null", index=True)
    whatsapp_message_id = fields.Many2one(
        "whatsapp.message",
        string="WhatsApp Hub Message",
        ondelete="set null",
        index=True,
        copy=False,
        help="Canonical WhatsApp Hub message this intake was built from.",
    )
    hub_body = fields.Text(
        related="whatsapp_message_id.body",
        string="Hub message body",
        readonly=True,
    )
    hub_attachment_references = fields.Text(
        related="whatsapp_message_id.attachment_references",
        string="Hub attachment refs",
        readonly=True,
    )
    hub_attachment_ids = fields.Many2many(
        "ir.attachment",
        string="Hub attachments",
        compute="_compute_hub_attachments",
    )
    hub_has_attachment = fields.Boolean(
        string="Has attachment",
        compute="_compute_hub_attachments",
    )
    last_message_at = fields.Datetime(index=True)
    ingest_fingerprint = fields.Char(index=True, copy=False)
    event_ids = fields.One2many("dev.whatsapp.intake.event", "intake_id")

    @api.depends(
        "whatsapp_message_id",
        "whatsapp_message_id.attachment_references",
        "whatsapp_message_id.dh_attachment_ids",
        "whatsapp_message_id.dh_has_attachment",
    )
    def _compute_hub_attachments(self):
        for rec in self:
            msg = rec.whatsapp_message_id
            if msg:
                rec.hub_attachment_ids = msg.dh_attachment_ids
                rec.hub_has_attachment = msg.dh_has_attachment
            else:
                rec.hub_attachment_ids = False
                rec.hub_has_attachment = False

    def _audit(self, event_type, detail=None):
        Event = self.env["dev.whatsapp.intake.event"].sudo()
        for rec in self:
            Event.create(
                {
                    "intake_id": rec.id,
                    "event_type": event_type,
                    "detail": _clean(detail, 4000) or False,
                    "actor_id": self.env.user.id,
                }
            )

    def action_mark_awaiting_confirm(self):
        for rec in self:
            if rec.state in ("rejected", "confirmed", "merged", "abandoned"):
                raise UserError("This intake can no longer await confirmation.")
            rec.state = "awaiting_confirm"
            rec._audit("awaiting_confirm")
        return True

    def action_reject(self):
        for rec in self:
            if rec.state == "confirmed":
                raise UserError("Confirmed intake cannot be rejected; cancel the work item instead.")
            rec.state = "rejected"
            rec._audit("rejected")
        return True

    def action_confirm_create_work_item(self):
        """Human confirmation → create linked dev.work.item (no execution)."""
        Work = self.env["dev.work.item"]
        for rec in self:
            if rec.work_item_id:
                continue
            if rec.source_id.require_human_confirm and not self.env.user.has_group(
                "devhub_core.group_dev_hub_approver"
            ) and not self.env.user.has_group("devhub_core.group_dev_hub_manager"):
                raise AccessError("Confirming WhatsApp intake requires a Dev Hub approver.")
            if rec.state in ("rejected", "abandoned", "merged"):
                raise UserError("This intake cannot be confirmed.")
            if not rec.source_message_ids:
                raise UserError("Intake requires at least one source message.")
            source = rec.source_id
            vals = {
                "name": rec.name[:200],
                "dev_project_id": source.dev_project_id.id,
                "preferred_environment_id": source.default_environment_id.id or False,
                "preferred_repository_id": source.default_repository_id.id or False,
                "source_message_ids": [(6, 0, rec.source_message_ids.ids)],
            }
            # odoo_project_id required on work item — use configured or project's linked
            if source.odoo_project_id:
                vals["odoo_project_id"] = source.odoo_project_id.id
            elif "odoo_project_id" in Work._fields:
                # try related maps via openproject extension if present
                project = source.dev_project_id
                primary = getattr(project, "primary_odoo_project_id", False)
                if primary:
                    vals["odoo_project_id"] = primary.id
            if "odoo_project_id" in Work._fields and not vals.get("odoo_project_id"):
                raise UserError(
                    "Configure an Odoo Project on the WhatsApp source before confirming."
                )
            work = Work.create(vals)
            rec.write({"work_item_id": work.id, "state": "confirmed"})
            rec._audit("confirmed", "work_item_id=%s" % work.id)
        return True

    @api.model
    def service_ingest_message(self, payload):
        """Idempotent Chatwoot-normalized WhatsApp ingest (n8n → Dev Hub)."""
        _require_intake_service(self.env)
        if not isinstance(payload, dict):
            raise ValidationError("payload must be an object.")

        group_jid = _clean(payload.get("group_jid"), 80)
        chatwoot_message_id = payload.get("chatwoot_message_id") or payload.get("message_id")
        chatwoot_conversation_id = payload.get("chatwoot_conversation_id") or payload.get(
            "conversation_id"
        )
        chatwoot_account_id = int(payload.get("chatwoot_account_id") or payload.get("account_id") or 0)
        chatwoot_inbox_id = int(payload.get("chatwoot_inbox_id") or payload.get("inbox_id") or 0)
        text = _clean(payload.get("text") or payload.get("content") or payload.get("body"))
        attachment_references = _clean(payload.get("attachment_references"), 4000)
        sender_jid = _clean(payload.get("sender_jid") or payload.get("sender"), 120)
        classification = payload.get("classification") or "new_dev_request"
        confidence = float(payload.get("confidence") or 0.0)
        evolution_message_id = _clean(
            payload.get("evolution_message_id") or payload.get("provider_message_id"), 300
        )
        instance_ref = _clean(payload.get("instance_reference") or payload.get("evolution_instance"), 200)
        reply_to = payload.get("reply_to_chatwoot_message_id") or payload.get("quoted_message_id")
        ts = payload.get("message_timestamp") or fields.Datetime.now()

        if not group_jid:
            return {"skipped": True, "reason": "missing_group_jid"}
        # Allow media-only WhatsApp messages (caption may be empty)
        if not text and not attachment_references:
            return {"skipped": True, "reason": "empty_text"}
        if not text and attachment_references:
            text = "[attachment]"
        if not chatwoot_message_id and not evolution_message_id:
            raise ValidationError("chatwoot_message_id or evolution_message_id is required.")

        # Canonical store first (WhatsApp Hub) — one message row for all consumers
        hub_result = {}
        if "whatsapp.message" in self.env:
            try:
                hub_result = (
                    self.env["whatsapp.message"]
                    .sudo()
                    .service_ingest_normalized(
                        {
                            **payload,
                            "group_jid": group_jid,
                            "text": text,
                            "sender_jid": sender_jid,
                            "chatwoot_message_id": chatwoot_message_id,
                            "evolution_message_id": evolution_message_id,
                            "chatwoot_account_id": chatwoot_account_id,
                            "chatwoot_inbox_id": chatwoot_inbox_id,
                            "chatwoot_conversation_id": chatwoot_conversation_id,
                            "message_timestamp": ts,
                            "instance_reference": instance_ref,
                            "attachment_references": attachment_references,
                        }
                    )
                )
            except Exception as hub_exc:
                _logger.warning("whatsapp_hub ingest from devhub failed: %s", hub_exc)

        fingerprint = _hash(
            {
                "account": chatwoot_account_id,
                "message": chatwoot_message_id or evolution_message_id,
                "group": group_jid,
            }
        )

        # Idempotency: prior ingest of same message
        existing_event = self.env["dev.whatsapp.intake.event"].sudo().search(
            [("ingest_fingerprint", "=", fingerprint)], limit=1
        )
        if existing_event:
            intake = existing_event.intake_id
            return {
                "skipped": True,
                "reason": "duplicate_message",
                "intake_id": intake.id,
                "work_item_id": intake.work_item_id.id or False,
                "state": intake.state,
            }

        source = (
            self.env["dev.whatsapp.source"]
            .sudo()
            .search([("group_jid", "=", group_jid), ("active", "=", True)], limit=1)
        )
        if not source:
            return {"skipped": True, "reason": "group_not_whitelisted", "group_jid": group_jid}

        if source.intake_mode == "legacy_op_only":
            return {
                "skipped": True,
                "reason": "legacy_op_only",
                "intake_mode": source.intake_mode,
                "skip_openproject_autocreate": False,
            }
        if source.intake_mode == "observe":
            return {
                "skipped": True,
                "reason": "observe_only",
                "intake_mode": source.intake_mode,
                "skip_openproject_autocreate": True,
            }

        # Sender policy
        sender_ok = True
        needs_sender_review = False
        if source.sender_policy in ("allowlist", "allowlist_or_approval"):
            allowed = source.sender_ids.filtered(
                lambda s: s.active and s.sender_jid == sender_jid
            )
            if not allowed:
                if source.sender_policy == "allowlist":
                    return {"skipped": True, "reason": "sender_not_allowlisted"}
                needs_sender_review = True
                sender_ok = False

        # Upsert source message (reuse Dev Hub provenance model)
        SourceMsg = self.env["dev.work.source.message"].sudo()
        provider = "chatwoot" if chatwoot_message_id else "evolution"
        provider_message_id = str(chatwoot_message_id or evolution_message_id)
        existing_msg = SourceMsg.search(
            [
                ("provider", "=", provider),
                ("provider_message_id", "=", provider_message_id),
                ("extracted_item_index", "=", 0),
            ],
            limit=1,
        )
        if existing_msg:
            source_msg = existing_msg
        else:
            source_msg = SourceMsg.create(
                {
                    "provider": provider,
                    "instance_reference": instance_ref or False,
                    "provider_message_id": provider_message_id,
                    "evolution_message_id": evolution_message_id or False,
                    "group_jid": group_jid,
                    "sender_jid": sender_jid or False,
                    "chatwoot_account_id": chatwoot_account_id or False,
                    "chatwoot_inbox_id": chatwoot_inbox_id or source.chatwoot_inbox_id or False,
                    "chatwoot_conversation_id": int(chatwoot_conversation_id or 0) or False,
                    "chatwoot_message_id": int(chatwoot_message_id or 0) or False,
                    "message_timestamp": ts,
                    "text_snapshot": text,
                    "attachment_references": attachment_references or False,
                    "source_url": _clean(payload.get("source_url"), 500) or False,
                }
            )

        # Grouping
        window = timedelta(minutes=max(1, source.grouping_window_minutes or 30))
        now = fields.Datetime.from_string(ts) if isinstance(ts, str) else ts
        if not now:
            now = fields.Datetime.now()
        Intake = self.sudo()
        intake = Intake.browse()
        # 1) reply to known source message
        if reply_to:
            parent_msg = SourceMsg.search(
                [("chatwoot_message_id", "=", int(reply_to))], limit=1
            )
            if parent_msg and parent_msg.work_item_ids:
                # follow existing work — append only
                work = parent_msg.work_item_ids[:1]
                work.write({"source_message_ids": [(4, source_msg.id)]})
                return {
                    "skipped": False,
                    "action": "appended_to_work_item",
                    "work_item_id": work.id,
                    "source_message_id": source_msg.id,
                    "skip_openproject_autocreate": True,
                }
            linked_intake = Intake.search(
                [("source_message_ids", "in", parent_msg.ids), ("state", "not in", ["rejected", "abandoned", "merged"])],
                limit=1,
            ) if parent_msg else Intake.browse()
            if linked_intake:
                intake = linked_intake

        # 2) open intake same conversation within window
        if not intake and chatwoot_conversation_id:
            candidates = Intake.search(
                [
                    ("source_id", "=", source.id),
                    ("chatwoot_conversation_id", "=", int(chatwoot_conversation_id)),
                    ("state", "in", ["received", "collecting", "draft_ready", "awaiting_confirm"]),
                ],
                order="id desc",
                limit=5,
            )
            for cand in candidates:
                if cand.last_message_at and (now - cand.last_message_at) <= window:
                    intake = cand
                    break

        classification = classification if classification in dict(CLASSIFICATIONS) else "new_dev_request"
        is_new = classification in ("new_dev_request", "bug_report")
        is_context = classification in ("context_addition", "follow_up_existing")
        is_noise = classification in ("unrelated", "noise", "question", "status_request")

        if is_noise and not intake:
            return {
                "skipped": True,
                "reason": "non_task_classification",
                "classification": classification,
                "source_message_id": source_msg.id,
                "skip_openproject_autocreate": True,
            }

        if not intake and (is_new or is_context) and source.auto_create_candidate:
            if confidence and confidence < (source.min_confidence or 0):
                return {
                    "skipped": True,
                    "reason": "low_confidence",
                    "confidence": confidence,
                    "source_message_id": source_msg.id,
                    "skip_openproject_autocreate": True,
                }
            title = _clean(payload.get("draft_title") or text.split("\n", 1)[0], 200) or "WhatsApp request"
            intake = Intake.create(
                {
                    "name": title,
                    "source_id": source.id,
                    "state": "collecting" if needs_sender_review else "received",
                    "classification": classification,
                    "confidence": confidence,
                    "grouping_key": "%s:%s" % (group_jid, chatwoot_conversation_id or "none"),
                    "chatwoot_account_id": chatwoot_account_id or False,
                    "chatwoot_inbox_id": chatwoot_inbox_id or source.chatwoot_inbox_id or False,
                    "chatwoot_conversation_id": int(chatwoot_conversation_id or 0) or False,
                    "group_jid": group_jid,
                    "primary_sender_jid": sender_jid or False,
                    "draft_summary": _clean(payload.get("draft_summary") or text, 4000),
                    "draft_problem": _clean(payload.get("draft_problem"), 4000) or False,
                    "draft_current_behavior": _clean(payload.get("draft_current_behavior"), 4000)
                    or False,
                    "draft_expected_behavior": _clean(payload.get("draft_expected_behavior"), 4000)
                    or False,
                    "draft_acceptance_criteria": _clean(
                        payload.get("draft_acceptance_criteria"), 4000
                    )
                    or False,
                    "draft_missing_information": _clean(
                        payload.get("draft_missing_information"), 4000
                    )
                    or False,
                    "draft_urgency": payload.get("draft_urgency") or "normal",
                    "draft_json": json.dumps(payload.get("draft_json") or {}, default=str)[:20000],
                    "last_message_at": now,
                    "source_message_ids": [(4, source_msg.id)],
                    "whatsapp_message_id": hub_result.get("message_id") or False,
                }
            )
            intake._audit("created", "fingerprint=%s" % fingerprint)
        elif intake:
            intake.write(
                {
                    "source_message_ids": [(4, source_msg.id)],
                    "last_message_at": now,
                    "state": "collecting"
                    if intake.state == "received"
                    else intake.state,
                    "draft_summary": intake.draft_summary
                    or _clean(payload.get("draft_summary") or text, 4000),
                    "whatsapp_message_id": hub_result.get("message_id")
                    or intake.whatsapp_message_id.id
                    or False,
                }
            )
            intake._audit("context_appended", "source_message_id=%s" % source_msg.id)
        else:
            return {
                "skipped": True,
                "reason": "no_candidate_created",
                "classification": classification,
                "source_message_id": source_msg.id,
                "skip_openproject_autocreate": True,
            }

        # Record fingerprint on event for idempotency
        self.env["dev.whatsapp.intake.event"].sudo().create(
            {
                "intake_id": intake.id,
                "event_type": "ingest",
                "detail": "message=%s" % provider_message_id,
                "ingest_fingerprint": fingerprint,
                "actor_id": self.env.user.id,
            }
        )

        if (
            not source.require_human_confirm
            and sender_ok
            and intake.state in ("received", "collecting", "draft_ready")
            and confidence >= (source.min_confidence or 0)
        ):
            intake.state = "draft_ready"
        elif intake.state in ("received", "collecting") and sender_ok:
            intake.state = "awaiting_confirm" if source.require_human_confirm else "draft_ready"
            intake._audit(intake.state)

        return {
            "skipped": False,
            "intake_id": intake.id,
            "state": intake.state,
            "source_message_id": source_msg.id,
            "work_item_id": intake.work_item_id.id or False,
            "intake_mode": source.intake_mode,
            "skip_openproject_autocreate": True,
            "classification": classification,
            "whatsapp_message_id": hub_result.get("message_id") or False,
        }


class DevWhatsappIntakeEvent(models.Model):
    _name = "dev.whatsapp.intake.event"
    _description = "Dev Hub WhatsApp Intake Event"
    _order = "id desc"

    intake_id = fields.Many2one(
        "dev.whatsapp.intake", required=True, ondelete="cascade", index=True
    )
    event_type = fields.Char(required=True, index=True)
    detail = fields.Text()
    ingest_fingerprint = fields.Char(index=True, copy=False)
    actor_id = fields.Many2one("res.users", ondelete="set null")
    create_date = fields.Datetime(readonly=True)

    _fingerprint_unique = models.UniqueIndex(
        "(ingest_fingerprint) WHERE ingest_fingerprint IS NOT NULL",
        "This WhatsApp message was already ingested.",
    )

    def write(self, vals):
        raise AccessError("Intake events are immutable.")

    def unlink(self):
        raise AccessError("Intake events cannot be deleted.")


class DevWorkItemWhatsapp(models.Model):
    _inherit = "dev.work.item"

    whatsapp_intake_ids = fields.One2many(
        "dev.whatsapp.intake", "work_item_id", string="WhatsApp Intakes"
    )
    whatsapp_intake_count = fields.Integer(compute="_compute_whatsapp_intake_count")

    @api.depends("whatsapp_intake_ids")
    def _compute_whatsapp_intake_count(self):
        for rec in self:
            rec.whatsapp_intake_count = len(rec.whatsapp_intake_ids)

    def action_open_whatsapp_intakes(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "WhatsApp Intakes",
            "res_model": "dev.whatsapp.intake",
            "view_mode": "list,form",
            "domain": [("work_item_id", "=", self.id)],
        }
