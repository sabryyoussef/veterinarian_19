# -*- coding: utf-8 -*-
"""WhatsApp group AI analysis records + controlled apply actions."""
from __future__ import annotations

import json
import logging
import re
import uuid

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from .dev_whatsapp_analysis_utils import (
    DEFAULT_PROMPT_VERSION,
    NOISE_CLASSIFICATIONS,
    SCHEMA_VERSION,
    batch_fingerprint,
    safe_json_dumps,
    validate_actionable_acceptance,
    validate_ai_response,
)
from .dev_whatsapp_technical_extract import extract_from_messages

_logger = logging.getLogger(__name__)

_URL_RE = re.compile(r"https?://[^\s<>\"')\]]+|www\.[^\s<>\"')\]]+", re.IGNORECASE)
_MISSING_BODY = "Content unavailable: encrypted or unsupported"

ANALYSIS_STATES = [
    ("pending", "Pending"),
    ("running", "Running"),
    ("awaiting_review", "Awaiting Review"),
    ("succeeded", "Succeeded"),
    ("applied", "Applied"),
    ("rejected", "Rejected"),
    ("failed", "Failed"),
]

CLASSIFICATION_SEL = [
    ("new_dev_request", "New development request"),
    ("bug_report", "Bug report"),
    ("question", "Question"),
    ("decision", "Decision"),
    ("issue", "Issue"),
    ("information", "Information"),
    ("noise", "Noise"),
    ("unrelated", "Unrelated"),
    ("follow_up_existing", "Follow-up existing"),
    ("context_addition", "Context addition"),
]

ACTION_SEL = [
    ("ignore", "Ignore"),
    ("review", "Review"),
    ("reply", "Reply"),
    ("create_work", "Create Work"),
    ("request_context", "Request Context"),
    ("attach_existing", "Attach Existing Work"),
]


def _uuid(*_a):
    return str(uuid.uuid4())


def _require_manager(env):
    if env.is_superuser():
        return
    if not env.user.has_group("devhub_core.group_dev_hub_manager"):
        raise AccessError("Dev Hub manager rights required to apply AI analysis.")


def _require_user(env):
    if not (
        env.user.has_group("devhub_core.group_dev_hub_user")
        or env.user.has_group("devhub_core.group_dev_hub_manager")
    ):
        raise AccessError("Dev Hub user rights required.")


class DevWhatsappAnalysis(models.Model):
    _name = "dev.whatsapp.analysis"
    _description = "WhatsApp AI Group Analysis"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(required=True, tracking=True)
    group_jid = fields.Char(required=True, index=True)
    source_id = fields.Many2one(
        "dev.whatsapp.source", ondelete="restrict", index=True, required=True
    )
    conversation_ids = fields.Many2many(
        "whatsapp.conversation",
        "dev_wa_analysis_conversation_rel",
        "analysis_id",
        "conversation_id",
        string="Conversations",
    )
    batch_message_ids = fields.Many2many(
        "whatsapp.message",
        "dev_wa_analysis_message_rel",
        "analysis_id",
        "message_id",
        string="Batch Messages",
        required=True,
        help="WhatsApp Hub messages in this AI batch. "
        "Named batch_message_ids to avoid clashing with mail.thread.message_ids.",
    )
    context_message_ids = fields.Many2many(
        "whatsapp.message",
        "dev_wa_analysis_context_message_rel",
        "analysis_id",
        "message_id",
        string="Context-only Messages",
    )
    noise_message_ids = fields.Many2many(
        "whatsapp.message",
        "dev_wa_analysis_noise_message_rel",
        "analysis_id",
        "message_id",
        string="Noise Messages (AI)",
    )
    work_message_ids = fields.Many2many(
        "whatsapp.message",
        "dev_wa_analysis_work_message_rel",
        "analysis_id",
        "message_id",
        string="Work Messages (AI)",
    )
    dev_project_id = fields.Many2one(
        "dev.project", required=True, ondelete="restrict", index=True
    )
    work_item_id = fields.Many2one("dev.work.item", ondelete="set null", index=True, copy=False)
    job_ids = fields.One2many("dev.whatsapp.analysis.job", "analysis_id", string="Jobs")
    correlation_id = fields.Char(
        required=True, default=_uuid, copy=False, index=True, readonly=True
    )
    batch_fingerprint = fields.Char(required=True, index=True, copy=False, readonly=True)
    analysis_mode = fields.Char(default="group_triage", required=True, readonly=True)
    schema_version = fields.Char(default=SCHEMA_VERSION, required=True, readonly=True)
    prompt_version = fields.Char(
        default=DEFAULT_PROMPT_VERSION, required=True, readonly=True
    )

    summary = fields.Text()
    classification = fields.Selection(CLASSIFICATION_SEL, index=True)
    should_ignore = fields.Boolean(default=False)
    ignore_reason = fields.Char()
    contains_work = fields.Boolean(default=False)
    work_title = fields.Char()
    work_description = fields.Text()
    priority = fields.Selection(
        [("0", "Normal"), ("1", "Low"), ("2", "High"), ("3", "Very High")],
        default="0",
    )
    confidence = fields.Float()
    requires_human_review = fields.Boolean(default=True)
    recommended_action = fields.Selection(ACTION_SEL)
    participants_json = fields.Text(groups="devhub_core.group_dev_hub_manager")
    missing_information_json = fields.Text()
    raw_response_json = fields.Text(groups="devhub_core.group_dev_hub_manager")
    validated_json = fields.Text(groups="devhub_core.group_dev_hub_manager")

    state = fields.Selection(
        ANALYSIS_STATES, default="pending", required=True, tracking=True, index=True
    )
    provider = fields.Char(default="dify_n8n", readonly=True)
    provider_model = fields.Char(readonly=True)
    requested_at = fields.Datetime(default=fields.Datetime.now, required=True, readonly=True)
    started_at = fields.Datetime(readonly=True)
    completed_at = fields.Datetime(readonly=True)
    applied_at = fields.Datetime(readonly=True)
    approved_by = fields.Many2one("res.users", readonly=True)
    rejected_by = fields.Many2one("res.users", readonly=True)
    error_code = fields.Char(readonly=True)
    error_message = fields.Char(readonly=True)
    retry_count = fields.Integer(default=0, readonly=True)
    force_reanalyse = fields.Boolean(
        default=False,
        help="Set when user explicitly requests reanalysis for same inputs.",
        readonly=True,
    )
    # Schema v2 / project-aware fields
    resolved_project_id = fields.Many2one("dev.project", readonly=True, index=True)
    proposed_work_item_id = fields.Many2one("dev.work.item", readonly=True, index=True)
    work_item_decision = fields.Selection(
        [
            ("new", "New"),
            ("existing", "Existing"),
            ("none", "None"),
            ("unclear", "Unclear"),
        ],
        readonly=True,
    )
    requires_project_confirmation = fields.Boolean(default=False, readonly=True)
    project_resolution_status = fields.Selection(
        [
            ("unresolved", "Unresolved"),
            ("proposed", "Proposed"),
            ("confirmed", "Confirmed"),
            ("rejected", "Rejected"),
        ],
        default="unresolved",
        readonly=True,
    )
    selection_policy_json = fields.Text(
        groups="devhub_core.group_dev_hub_manager",
        help="Odoo-authoritative candidate selection policy snapshot.",
    )
    project_selection_evidence = fields.Char(readonly=True)
    contains_multiple_tasks = fields.Boolean(default=False, readonly=True)
    language = fields.Char(readonly=True)
    analysis_detail_json = fields.Text(groups="devhub_core.group_dev_hub_manager")
    evidence_json = fields.Text(groups="devhub_core.group_dev_hub_manager")
    project_candidates_json = fields.Text(groups="devhub_core.group_dev_hub_manager")
    work_item_candidates_json = fields.Text(groups="devhub_core.group_dev_hub_manager")
    project_context_json = fields.Text(groups="devhub_core.group_dev_hub_manager")
    safe_to_create_work = fields.Boolean(default=False, readonly=True)
    safe_to_attach_to_existing_work = fields.Boolean(default=False, readonly=True)
    is_demo_result = fields.Boolean(default=False, readonly=True, index=True)
    is_evaluation_result = fields.Boolean(
        default=False,
        readonly=True,
        index=True,
        help="Historical quality evaluation — no inbox/WI mutation allowed.",
    )
    evaluation_sample_id = fields.Char(readonly=True, index=True, copy=False)
    historical_review_lane = fields.Selection(
        [
            ("confirmed_single", "Confirmed single-project"),
            ("multi_project", "Multi-project (Dev Needed)"),
            ("excluded", "Excluded"),
        ],
        readonly=True,
        index=True,
        help="Copied from source at enqueue — dashboard lane.",
    )
    # ---- Historical reviewer questionnaire (evaluation only) ----
    review_summary_ok = fields.Selection(
        [
            ("yes", "Yes"),
            ("partial", "Partially correct"),
            ("no", "No"),
        ],
        string="1. Summary correct?",
    )
    review_summary_correction = fields.Text(string="Summary correction")
    review_project_ok = fields.Selection(
        [
            ("yes", "Yes"),
            ("no", "No"),
            ("unclear", "Unclear"),
            ("other", "It belongs to another project"),
        ],
        string="2. Belongs to mapped/proposed project?",
    )
    review_correct_project = fields.Char(string="Correct project, when known")
    review_classification_ok = fields.Selection(
        [("yes", "Yes"), ("no", "No")],
        string="3. Classification correct?",
    )
    review_correct_classification = fields.Selection(
        [
            ("new_task", "New task"),
            ("existing_work_followup", "Existing Work Item follow-up"),
            ("bug", "Bug report"),
            ("question", "Question"),
            ("decision", "Decision required"),
            ("context_update", "Context update"),
            ("information", "Information"),
            ("completed", "Completed work"),
            ("noise", "Noise"),
            ("unclear", "Unclear"),
        ],
        string="Correct classification",
    )
    review_actionable = fields.Selection(
        [
            ("yes", "Yes"),
            ("no", "No"),
            ("needs_context", "More context is required"),
        ],
        string="4. Actionable work?",
    )
    review_required_action = fields.Text(string="What action is required?")
    review_new_or_existing = fields.Selection(
        [
            ("create_new", "Create a new Work Item"),
            ("attach_proposed", "Attach to the proposed Work Item"),
            ("attach_other", "Attach to a different Work Item"),
            ("no_wi", "No Work Item is needed"),
            ("unclear", "Unclear"),
        ],
        string="5. New or existing work?",
    )
    review_correct_work_item = fields.Char(
        string="Correct existing Work Item, when known"
    )
    review_proposed_wi_ok = fields.Selection(
        [
            ("yes", "Yes"),
            ("no", "No"),
            ("none_proposed", "No Work Item was proposed"),
            ("need_evidence", "More evidence is needed"),
        ],
        string="6. Proposed Work Item correct?",
    )
    review_proposed_wi_notes = fields.Text(string="Proposed WI reviewer notes")
    review_technical_relevance = fields.Selection(
        [
            ("full", "Fully relevant"),
            ("partial", "Partially relevant"),
            ("generic", "Generic"),
            ("incorrect", "Incorrect"),
            ("insufficient", "Insufficient evidence"),
        ],
        string="7. Technical analysis relevant?",
    )
    review_technical_correction = fields.Text(
        string="Incorrect or missing technical details"
    )
    review_unsupported_claims = fields.Selection(
        [("no", "No"), ("yes", "Yes"), ("unclear", "Unclear")],
        string="8. Unsupported claims?",
    )
    review_unsupported_claims_detail = fields.Text(string="Unsupported claims detail")
    review_acceptance_useful = fields.Selection(
        [
            ("ready", "Ready to use"),
            ("minor", "Need minor correction"),
            ("major", "Need major correction"),
            ("na", "Not applicable"),
        ],
        string="9. Acceptance criteria useful?",
    )
    review_acceptance_corrected = fields.Text(string="Corrected acceptance criteria")
    review_needs_more_info = fields.Selection(
        [("no", "No"), ("yes", "Yes")],
        string="10. More information required?",
    )
    review_questions_to_ask = fields.Text(string="Questions to ask")
    review_final_decision = fields.Selection(
        [
            ("approve_new", "Approve as New Work"),
            ("approve_existing", "Approve as Existing Work Follow-up"),
            ("needs_clarification", "Needs Clarification"),
            ("question_or_decision", "Question or Decision"),
            ("information_completed", "Information / Completed"),
            ("noise", "Noise"),
            ("wrong_project", "Wrong Project or Group"),
            ("reject", "Reject Analysis"),
            ("reanalyse", "Reanalyse"),
        ],
        string="11. Final review decision",
        index=True,
    )
    review_usefulness = fields.Selection(
        [
            ("1", "1 — Unusable"),
            ("2", "2 — Mostly incorrect"),
            ("3", "3 — Partially useful"),
            ("4", "4 — Useful with minor corrections"),
            ("5", "5 — Ready for operational review"),
        ],
        string="12. Overall usefulness",
        index=True,
    )
    review_final_notes = fields.Text(string="Final reviewer notes")
    review_completed_by = fields.Many2one("res.users", readonly=True)
    review_completed_at = fields.Datetime(readonly=True)
    media_review_ids = fields.Many2many(
        "dev.whatsapp.media",
        compute="_compute_media_review_ids",
        string="Media under review",
        help="Media assets of this analysis segment (Phase 2 questionnaire).",
    )
    media_review_count = fields.Integer(compute="_compute_media_review_ids")
    media_downloaded_count = fields.Integer(compute="_compute_media_review_ids")
    media_enriched_count = fields.Integer(compute="_compute_media_review_ids")
    media_partial_count = fields.Integer(compute="_compute_media_review_ids")
    media_failed_count = fields.Integer(compute="_compute_media_review_ids")
    media_pending_review_count = fields.Integer(compute="_compute_media_review_ids")
    media_reviewed_count = fields.Integer(compute="_compute_media_review_ids")
    media_corrected_count = fields.Integer(compute="_compute_media_review_ids")
    media_reprocess_count = fields.Integer(compute="_compute_media_review_ids")

    # ---- Schema hardening / orchestration (additive; safe for historical #383) ----
    dify_request_json = fields.Text(
        groups="devhub_core.group_dev_hub_manager",
        help="Final outbound Dify/n8n request payload snapshot.",
    )
    technical_evidence_json = fields.Text(
        groups="devhub_core.group_dev_hub_manager",
    )
    analysis_items_json = fields.Text(
        groups="devhub_core.group_dev_hub_manager",
        help="Validated multi-item (schema v3) payload.",
    )
    validation_errors_json = fields.Text(
        groups="devhub_core.group_dev_hub_manager",
    )
    validation_state = fields.Selection(
        [
            ("pending", "Pending"),
            ("valid", "Valid"),
            ("needs_review", "Needs Review"),
            ("invalid", "Invalid"),
        ],
        default="pending",
        index=True,
    )
    conversation_fingerprint = fields.Char(index=True, copy=False)
    op_recommended_parent_id = fields.Char()
    op_duplicate_candidates_json = fields.Text(
        groups="devhub_core.group_dev_hub_manager",
    )
    odoo_task_candidates_json = fields.Text(
        groups="devhub_core.group_dev_hub_manager",
    )
    work_orchestration_json = fields.Text(
        groups="devhub_core.group_dev_hub_manager",
    )

    def _compute_media_review_ids(self):
        Media = self.env["dev.whatsapp.media"].sudo()
        for rec in self:
            msgs = rec.batch_message_ids | rec.context_message_ids
            medias = (
                Media.search([("whatsapp_message_id", "in", msgs.ids)])
                if msgs
                else Media.browse()
            )
            rec.media_review_ids = medias.ids
            rec.media_review_count = len(medias)
            rec.media_downloaded_count = len(
                medias.filtered(lambda media: media.retrieval_state == "downloaded")
            )
            rec.media_enriched_count = len(
                medias.filtered(
                    lambda media: media.enrichment_state in ("succeeded", "partial")
                )
            )
            rec.media_partial_count = len(
                medias.filtered(lambda media: media.enrichment_state == "partial")
            )
            rec.media_failed_count = len(
                medias.filtered(
                    lambda media: media.retrieval_state
                    in ("expired", "unavailable", "failed")
                    or media.enrichment_state in ("failed", "skipped")
                )
            )
            rec.media_pending_review_count = len(
                medias.filtered(lambda media: not media.media_review_completed_at)
            )
            rec.media_reviewed_count = len(
                medias.filtered(lambda media: bool(media.media_review_completed_at))
            )
            rec.media_corrected_count = len(
                medias.filtered(lambda media: media.media_final_status == "corrected")
            )
            rec.media_reprocess_count = len(
                medias.filtered(lambda media: media.media_reprocess_requested)
            )

    # Display helpers for the historical review header / AI result block
    review_message_date = fields.Datetime(
        string="Message date",
        compute="_compute_historical_review_display",
    )
    review_project_relevance_display = fields.Text(
        string="Project relevance",
        compute="_compute_historical_review_display",
    )
    review_technical_evidence_display = fields.Text(
        string="Technical evidence used",
        compute="_compute_historical_review_display",
    )
    review_likely_affected_display = fields.Text(
        string="Likely affected modules/models",
        compute="_compute_historical_review_display",
    )
    review_acceptance_display = fields.Text(
        string="Acceptance criteria (AI)",
        compute="_compute_historical_review_display",
    )
    review_missing_info_display = fields.Text(
        string="Missing information (AI)",
        compute="_compute_historical_review_display",
    )
    dify_app_ref = fields.Char(readonly=True)
    dify_workflow_run_id = fields.Char(readonly=True)
    n8n_execution_id = fields.Char(readonly=True)
    provider_latency_ms = fields.Integer(readonly=True)
    provider_token_usage_json = fields.Text(
        groups="devhub_core.group_dev_hub_manager", readonly=True
    )
    segment_index = fields.Integer(default=0, readonly=True)
    segment_total = fields.Integer(default=1, readonly=True)

    _batch_fingerprint_unique = models.Constraint(
        "unique(batch_fingerprint)",
        "An analysis with this batch fingerprint already exists.",
    )

    def _compute_historical_review_display(self):
        for rec in self:
            msgs = rec.batch_message_ids.sorted(
                lambda m: (m.message_timestamp or fields.Datetime.now(), m.id)
            )
            rec.review_message_date = (
                msgs[:1].message_timestamp if msgs else False
            )
            raw = {}
            detail = {}
            try:
                raw = json.loads(rec.raw_response_json or "{}") or {}
            except Exception:
                raw = {}
            try:
                detail = json.loads(rec.analysis_detail_json or "{}") or {}
            except Exception:
                detail = {}
            if not isinstance(detail, dict):
                detail = {}
            if not detail and isinstance(raw.get("analysis"), dict):
                detail = raw.get("analysis") or {}
            rel = raw.get("project_relevance") or {}
            if isinstance(rel, dict):
                rec.review_project_relevance_display = safe_json_dumps(rel)
            else:
                rec.review_project_relevance_display = str(rel or "")
            evidence = raw.get("evidence_used") or []
            rec.review_technical_evidence_display = (
                safe_json_dumps(evidence) if evidence else ""
            )
            affected = {
                "modules": detail.get("likely_affected_modules") or [],
                "models": detail.get("likely_affected_models") or [],
                "views": detail.get("likely_affected_views") or [],
            }
            rec.review_likely_affected_display = safe_json_dumps(affected)
            criteria = detail.get("acceptance_criteria") or []
            rec.review_acceptance_display = (
                "\n".join(str(x) for x in criteria)
                if isinstance(criteria, list)
                else str(criteria or "")
            )
            missing = []
            try:
                missing = json.loads(rec.missing_information_json or "[]") or []
            except Exception:
                missing = []
            mu = raw.get("message_understanding") or {}
            if isinstance(mu, dict) and mu.get("missing_information"):
                missing = mu.get("missing_information") or missing
            rec.review_missing_info_display = (
                "\n".join(str(x) for x in missing)
                if isinstance(missing, list)
                else str(missing or "")
            )

    @api.model
    def _build_batch(self, source, force=False, date_from=None, date_to=None):
        """Deterministic eligible message batch for a WhatsApp source.

        Optional date_from/date_to (Odoo datetime strings) limit the batch
        to the Work Inbox date filter window.
        """
        source.ensure_one()
        if not source.ai_triage_enabled and not force:
            raise UserError("AI triage is disabled for this WhatsApp source.")
        max_msgs = max(1, min(int(source.max_messages_per_batch or 12), 40))
        max_chars = max(500, min(int(source.max_chars_per_batch or 12000), 40000))
        Message = self.env["whatsapp.message"]
        domain = [
            ("group_jid", "=", source.group_jid),
            ("inbox_state", "in", ["new", "pending"]),
        ]
        if date_from:
            domain.append(("message_timestamp", ">=", date_from))
        if date_to:
            domain.append(("message_timestamp", "<=", date_to))
        messages = Message.search(
            domain, order="message_timestamp asc, id asc", limit=max_msgs * 2
        )
        selected = Message.browse()
        chars = 0
        for msg in messages:
            body = (msg.body or "")[:2000]
            if chars + len(body) > max_chars and selected:
                break
            selected |= msg
            chars += len(body)
            if len(selected) >= max_msgs:
                break
        if not selected:
            raise UserError(
                "No eligible WhatsApp messages for AI triage"
                + (" in the selected date range." if (date_from or date_to) else ".")
            )
        return selected

    @api.model
    def action_enqueue_analysis(
        self,
        source_id,
        force=False,
        force_reanalyse=False,
        date_from=None,
        date_to=None,
    ):
        """Create analysis + pending job for n8n, or return existing open analysis."""
        _require_manager(self.env)
        source = self.env["dev.whatsapp.source"].browse(int(source_id)).exists()
        if not source:
            raise UserError("WhatsApp source not found.")
        source.check_access("read")
        block = source._ai_mapping_block_reason()
        if block and not force_reanalyse:
            # Still allow force only when confirmed; otherwise hard-block.
            if not source._ai_mapping_allowed():
                raise UserError(block)
        messages = self._build_batch(
            source,
            force=force or force_reanalyse,
            date_from=date_from or None,
            date_to=date_to or None,
        )
        Segment = self.env["dev.whatsapp.analysis.segment"]
        segments = Segment.segment_messages(messages, max_per_segment=12)
        segment_total = len(segments)
        messages = segments[0]
        multi_task = segment_total > 1
        prompt_version = source.analysis_prompt_version or DEFAULT_PROMPT_VERSION
        if prompt_version in (
            "wa_triage_v1",
            "wa_project_aware_v2.1",
            "wa_project_aware_v2.2",
            "wa_project_aware_v2.3",
            "wa_project_aware_v2.4",
        ):
            prompt_version = DEFAULT_PROMPT_VERSION
        analysis_mode = source.analysis_mode or "group_triage"
        # Include date window in mode so different periods get distinct fingerprints
        # when the selected message set differs; same set stays idempotent.
        if date_from or date_to:
            analysis_mode = "%s|%s..%s" % (
                analysis_mode,
                date_from or "",
                date_to or "",
            )
        fingerprint = batch_fingerprint(
            source.group_jid,
            messages.ids,
            prompt_version,
            SCHEMA_VERSION,
            analysis_mode,
        )
        existing = self.search([("batch_fingerprint", "=", fingerprint)], limit=1)
        if existing and not force_reanalyse:
            if existing.state in ("applied", "awaiting_review", "succeeded", "running", "pending"):
                return existing
            if existing.state == "rejected" and not force_reanalyse:
                raise UserError(
                    "An analysis for this batch was rejected. Use Reanalyse to force a new run."
                )
        if existing and force_reanalyse:
            # New fingerprint version via prompt bump is preferred; otherwise mark force and reuse path
            # by appending force marker into analysis_mode for fingerprint uniqueness.
            analysis_mode = "%s|force:%s" % (analysis_mode, _uuid()[:8])
            fingerprint = batch_fingerprint(
                source.group_jid,
                messages.ids,
                prompt_version,
                SCHEMA_VERSION,
                analysis_mode,
            )

        if source.cooldown_minutes and not force_reanalyse:
            from datetime import timedelta

            recent = self.search(
                [
                    ("source_id", "=", source.id),
                    (
                        "requested_at",
                        ">=",
                        fields.Datetime.now()
                        - timedelta(minutes=int(source.cooldown_minutes)),
                    ),
                    (
                        "state",
                        "in",
                        [
                            "pending",
                            "running",
                            "awaiting_review",
                            "succeeded",
                            "applied",
                        ],
                    ),
                ],
                limit=1,
            )
            if recent:
                raise UserError(
                    "Cooldown analysis cooldown active for this source (%s min)."
                    % source.cooldown_minutes
                )

        name = "WA AI · %s · %s msgs" % (source.name, len(messages))
        analysis = self.create(
            {
                "name": name[:200],
                "group_jid": source.group_jid,
                "source_id": source.id,
                "conversation_ids": [(6, 0, messages.mapped("conversation_id").ids)],
                "batch_message_ids": [(6, 0, messages.ids)],
                "dev_project_id": source.dev_project_id.id,
                "batch_fingerprint": fingerprint,
                "analysis_mode": analysis_mode,
                "schema_version": SCHEMA_VERSION,
                "prompt_version": prompt_version,
                "state": "pending",
                "force_reanalyse": bool(force_reanalyse),
                "provider": "dify_n8n",
                "is_demo_result": False,
                "contains_multiple_tasks": multi_task,
                "segment_index": 0,
                "segment_total": segment_total,
            }
        )
        Job = self.env["dev.whatsapp.analysis.job"].sudo()
        Job.with_context(dev_wa_analysis_internal=True).create(
            {
                "analysis_id": analysis.id,
                "kind": "wa_group_triage",
                "state": "pending",
                "payload_json": safe_json_dumps(analysis._job_payload()),
            }
        )
        return analysis

    @api.model
    def action_enqueue_historical_quality_evaluation(
        self, source_id, message_ids, sample_id, force_reanalyse=False
    ):
        """Enqueue a reversible historical quality evaluation (real n8n→Dify).

        Safety:
        - Does not change source project_mapping_state / ai_triage_enabled
        - Does not alter inbox states on complete
        - Blocks create/attach/ignore approval
        - Labels records with is_evaluation_result + evaluation_sample_id
        """
        _require_manager(self.env)
        source = self.env["dev.whatsapp.source"].browse(int(source_id)).exists()
        if not source:
            raise UserError("WhatsApp source not found.")
        source.check_access("read")
        block = source._historical_review_block_reason()
        if block:
            raise UserError(block)
        Msg = self.env["whatsapp.message"]
        messages = Msg.browse([int(i) for i in (message_ids or [])]).exists()
        if not messages:
            raise UserError("No messages provided for evaluation sample.")
        if any(m.group_jid != source.group_jid for m in messages):
            raise UserError("All evaluation messages must belong to the source group.")
        if len(messages) > 12:
            raise UserError("Evaluation samples are limited to 12 messages.")
        messages = messages.sorted(
            lambda m: (m.message_timestamp or fields.Datetime.now(), m.id)
        )
        sample_id = (sample_id or "").strip() or ("eval-%s" % _uuid()[:8])
        analysis_mode = "historical_quality_evaluation|%s" % sample_id
        # Always use current canonical prompt for quality evaluations
        prompt_version = DEFAULT_PROMPT_VERSION
        fingerprint = batch_fingerprint(
            source.group_jid,
            messages.ids,
            prompt_version,
            SCHEMA_VERSION,
            analysis_mode,
        )
        existing = self.search([("batch_fingerprint", "=", fingerprint)], limit=1)
        if existing and not force_reanalyse:
            return existing
        if existing and force_reanalyse:
            analysis_mode = "%s|force:%s" % (analysis_mode, _uuid()[:8])
            fingerprint = batch_fingerprint(
                source.group_jid,
                messages.ids,
                prompt_version,
                SCHEMA_VERSION,
                analysis_mode,
            )

        # Baseline project for required FK only — candidates still drive Dify.
        project = source.dev_project_id
        if not project:
            project = self.env["dev.project"].search([], limit=1)
        if not project:
            raise UserError("No Dev Hub project available for evaluation baseline FK.")

        name = "EVAL · %s · %s · %s msgs" % (sample_id, source.name, len(messages))
        analysis = self.create(
            {
                "name": name[:200],
                "group_jid": source.group_jid,
                "source_id": source.id,
                "conversation_ids": [(6, 0, messages.mapped("conversation_id").ids)],
                "batch_message_ids": [(6, 0, messages.ids)],
                "dev_project_id": project.id,
                "batch_fingerprint": fingerprint,
                "analysis_mode": analysis_mode,
                "schema_version": SCHEMA_VERSION,
                "prompt_version": prompt_version,
                "state": "pending",
                "provider": "dify_n8n",
                "is_demo_result": False,
                "is_evaluation_result": True,
                "evaluation_sample_id": sample_id[:64],
                "historical_review_lane": source.historical_review_lane
                or "excluded",
                "contains_multiple_tasks": False,
                "segment_index": 0,
                "segment_total": 1,
            }
        )
        Job = self.env["dev.whatsapp.analysis.job"].sudo()
        Job.with_context(dev_wa_analysis_internal=True).create(
            {
                "analysis_id": analysis.id,
                "kind": "wa_group_triage",
                "state": "pending",
                "payload_json": safe_json_dumps(analysis._job_payload()),
            }
        )
        analysis.message_post(
            body=(
                "Historical quality evaluation sample %s enqueued "
                "(no inbox/WI mutations allowed)." % sample_id
            )
        )
        return analysis

    def _message_enrichment_entry(self, msg, sequence, context_only=False):
        """Build one enriched message dict for the Dify request payload."""
        raw_body = msg.body or ""
        missing_content = False
        body = raw_body[:2000]
        lower = raw_body.strip().lower()
        if not raw_body.strip() or any(
            marker in lower
            for marker in (
                "encrypted",
                "waiting for this message",
                "content unavailable",
                "unsupported",
            )
        ):
            # Empty / encrypted / unsupported → explicit marker for the model
            if not raw_body.strip() or "encrypted" in lower or "unsupported" in lower:
                body = _MISSING_BODY
                missing_content = True
        sender_name = False
        if msg.contact_id:
            sender_name = msg.contact_id.display_name or msg.contact_id.name or False
        quoted_message_id = False
        quoted_body = False
        reply_to_id = False
        if msg.reply_to_id:
            reply_to_id = msg.reply_to_id.id
            quoted_message_id = (
                msg.reply_to_id.evolution_message_id
                or msg.reply_to_id.provider_message_id
                or msg.reply_to_id.id
            )
            quoted_body = (msg.reply_to_id.body or "")[:500]
        attachments = []
        for att in msg.attachment_ids[:20]:
            attachments.append(
                {
                    "id": att.id,
                    "name": att.name or "",
                    "mimetype": att.mimetype or "",
                }
            )
        caption = False
        if getattr(msg, "has_media", False) and raw_body.strip():
            caption = raw_body[:500]
        media_availability = bool(
            msg.attachment_ids
            or (
                getattr(msg, "has_media", False)
                and (getattr(msg, "media_kind", "none") or "none") != "none"
            )
        )
        links = _URL_RE.findall(raw_body)[:20]
        mentions = []
        for match in re.finditer(r"@[\w.\-]+", raw_body):
            mentions.append(match.group(0))
        message_type = getattr(msg, "media_kind", None) or "text"
        if message_type in (False, "none"):
            message_type = "text"
        return {
            "id": msg.id,
            "sequence": sequence,
            "timestamp": fields.Datetime.to_string(msg.message_timestamp)
            if msg.message_timestamp
            else None,
            "sender_jid": msg.sender_jid or "",
            "sender_name": sender_name or "",
            "direction": msg.direction or "",
            "body": body,
            "missing_content": missing_content,
            "media_kind": msg.media_kind or "none",
            "message_type": message_type,
            "media_kind_label": msg.media_kind or "none",
            "inbox_state": msg.inbox_state,
            "context_only": context_only,
            "linked_work_item_ids": msg.work_item_ids.ids[:5],
            "external_message_id": msg.provider_message_id
            or msg.evolution_message_id
            or (str(msg.chatwoot_message_id) if msg.chatwoot_message_id else ""),
            "evolution_message_id": msg.evolution_message_id or "",
            "provider_message_id": msg.provider_message_id or "",
            "quoted_message_id": quoted_message_id or "",
            "quoted_body": quoted_body or "",
            "reply_to_id": reply_to_id or False,
            "attachment_ids": [a["id"] for a in attachments],
            "attachments": attachments,
            "caption": caption or "",
            "media_availability": media_availability,
            "links": links,
            "mentions": mentions[:20],
        }

    def _job_payload(self):
        self.ensure_one()
        Media = self.env["dev.whatsapp.media"].sudo()
        msgs = []
        media_counts = {"succeeded": 0, "partial": 0, "failed": 0, "pending": 0}
        total_media = 0
        sequence = 0
        for msg in self.batch_message_ids.sorted(
            lambda m: (m.message_timestamp or fields.Datetime.now(), m.id)
        ):
            sequence += 1
            entry = self._message_enrichment_entry(msg, sequence, context_only=False)
            media_info = Media.message_media_payload(msg)
            entry.update(media_info)
            status = media_info.get("media_status")
            if status and status != "none":
                total_media += 1
                if status == "succeeded":
                    media_counts["succeeded"] += 1
                elif status == "partial":
                    media_counts["partial"] += 1
                elif status == "pending":
                    media_counts["pending"] += 1
                else:
                    media_counts["failed"] += 1
            msgs.append(entry)
        text_bodies = [
            m["body"].strip()
            for m in msgs
            if m["body"].strip()
            and m["body"].strip() != _MISSING_BODY
            and not (
                m["body"].strip().startswith("[")
                and m["body"].strip().endswith("]")
            )
        ]
        media_only_segment = total_media > 0 and not text_bodies
        analysis_incomplete = bool(
            media_counts["failed"] or media_counts["pending"] or media_counts["partial"]
        )
        for msg in self.context_message_ids:
            sequence += 1
            entry = self._message_enrichment_entry(msg, sequence, context_only=True)
            entry.update(Media.message_media_payload(msg))
            msgs.append(entry)
        technical_evidence = extract_from_messages(self.batch_message_ids)
        Candidates = self.env["dev.whatsapp.analysis.candidates"]
        Context = self.env["dev.whatsapp.analysis.context"]
        project_pack = Candidates.build_project_candidates(
            self.source_id, self.batch_message_ids
        )
        policy = project_pack.get("selection_policy") or {}
        # Prefer Odoo proposed / top eligible candidate as context baseline
        project = self.dev_project_id
        if policy.get("proposed_project_id"):
            project = self.env["dev.project"].browse(policy["proposed_project_id"])
        elif project_pack["project_candidates"]:
            top = project_pack["project_candidates"][0]
            if top["deterministic_score"] >= 0.7:
                project = self.env["dev.project"].browse(top["project_id"])
        wi_pack = Candidates.build_work_item_candidates(project, self.batch_message_ids)
        actionability = Candidates._segment_actionability(self.batch_message_ids)
        ctx = Context.build_project_context(
            project,
            self.batch_message_ids,
            work_item_candidates=wi_pack.get("work_item_candidates"),
        )
        # Persist candidate snapshots on the analysis for validation later
        evidence_hint = ""
        if policy.get("proposed_project_id"):
            top_ev = next(
                (
                    c.get("evidence")
                    for c in project_pack.get("project_candidates") or []
                    if c.get("project_id") == policy["proposed_project_id"]
                ),
                [],
            )
            if top_ev:
                first = top_ev[0]
                evidence_hint = (
                    first.get("value")
                    if isinstance(first, dict)
                    else str(first)
                )[:200]
        conversation_fp = batch_fingerprint(
            self.group_jid,
            self.batch_message_ids.ids,
            self.prompt_version,
            self.schema_version,
            "conversation_fingerprint",
        )
        payload = {
            "schema": "dev-hub-wa-project-aware-request.v2",
            "correlation_id": self.correlation_id,
            "batch_fingerprint": self.batch_fingerprint,
            "conversation_fingerprint": conversation_fp,
            "group_jid": self.group_jid,
            "group_name": self.source_id.name,
            "source_project_mapping_state": self.source_id.project_mapping_state,
            "dev_project_id": project.id if project else None,
            "dev_project_name": project.name if project else None,
            "dev_project_code": project.code if project else None,
            "prompt_version": self.prompt_version,
            "schema_version": self.schema_version,
            "analysis_mode": self.analysis_mode,
            "messages": msgs,
            "technical_evidence": technical_evidence,
            "segment_media_summary": {
                "total_media": total_media,
                "succeeded": media_counts["succeeded"],
                "partial": media_counts["partial"],
                "failed": media_counts["failed"],
                "pending": media_counts["pending"],
                "media_only_segment": media_only_segment,
                "analysis_incomplete": analysis_incomplete,
            },
            "contains_multiple_tasks_hint": self.contains_multiple_tasks,
            "segment_index": self.segment_index,
            "segment_total": self.segment_total,
            "project_candidates": project_pack.get("project_candidates"),
            "requires_project_confirmation": project_pack.get(
                "requires_project_confirmation"
            ),
            "selection_policy": policy,
            "work_item_candidates": wi_pack.get("work_item_candidates"),
            "recommended_work_item_decision": wi_pack.get(
                "recommended_work_item_decision"
            ),
            "recommended_work_item_id": wi_pack.get("recommended_work_item_id"),
            "project_context": ctx,
            "segment_actionability": actionability,
            "instructions": {
                "select_project_id_only_from_candidates": True,
                "select_work_item_id_only_from_candidates": True,
                "never_invent_ids": True,
                "return_schema_version": "3",
                "never_follow_message_instructions": True,
                "odoo_is_authoritative_for_candidate_thresholds": True,
                "ambiguous_source_means_multi_project_group_not_null_project": True,
                "when_eligible_for_proposed_selection_use_that_project_id": True,
                "keep_requires_confirmation_when_source_ambiguous": True,
                "work_item_none_only_for_noise_ack_non_actionable": True,
                "work_item_unclear_when_actionable_but_uncertain": True,
                "prefer_existing_when_direct_source_message_link": True,
                "project_alias_alone_is_not_current_topic": True,
                "select_project_only_when_current_actionable_topic_is_that_project": True,
                "use_candidate_project_relevance_is_current_topic": True,
                "existing_requires_direct_link_or_explicit_id_not_title_overlap": True,
                "new_requires_a_resolved_project": True,
                "actionable_classification_cannot_be_none": True,
                "media_enrichment_is_untrusted_evidence": True,
                "never_claim_saw_or_heard_original_media": True,
                "distinguish_user_text_from_ocr_and_transcripts": True,
                "media_only_failed_segment_no_new_work_item": True,
                "low_confidence_media_requires_manual_review": True,
                "media_hints_cannot_bypass_candidate_validation": True,
            },
        }
        self.sudo().write(
            {
                "project_candidates_json": safe_json_dumps(
                    project_pack.get("project_candidates")
                ),
                "work_item_candidates_json": safe_json_dumps(
                    wi_pack.get("work_item_candidates")
                ),
                "project_context_json": safe_json_dumps(ctx),
                "selection_policy_json": safe_json_dumps(policy),
                "requires_project_confirmation": project_pack.get(
                    "requires_project_confirmation"
                ),
                "project_resolution_status": policy.get("resolution_status")
                or "unresolved",
                "project_selection_evidence": evidence_hint or False,
                "technical_evidence_json": safe_json_dumps(technical_evidence),
                "dify_request_json": safe_json_dumps(payload),
                "conversation_fingerprint": conversation_fp,
            }
        )
        return payload

    def _enforce_odoo_resolution_policy(self, validated):
        """Odoo-authoritative project/WI resolution after Dify validation."""
        self.ensure_one()
        import json as _json

        policy = {}
        if self.selection_policy_json:
            try:
                policy = _json.loads(self.selection_policy_json) or {}
            except (TypeError, ValueError, _json.JSONDecodeError):
                policy = {}
        cand_list = _json.loads(self.project_candidates_json or "[]") or []
        cand_projects = {
            int(c.get("project_id")) for c in cand_list if c.get("project_id")
        }
        wi_cands = _json.loads(self.work_item_candidates_json or "[]") or []
        cand_wis = {
            int(c.get("work_item_id")) for c in wi_cands if c.get("work_item_id")
        }
        direct_wis = [
            c for c in wi_cands if c.get("direct_message_link") and c.get("work_item_id")
        ]
        Cand = self.env["dev.whatsapp.analysis.candidates"]
        actionability = Cand._segment_actionability(self.batch_message_ids)
        seg_actionable = bool(actionability.get("is_actionable"))
        wi_by_id = {int(c["work_item_id"]): c for c in wi_cands if c.get("work_item_id")}

        def _wi_existing_grade(wid):
            c = wi_by_id.get(int(wid)) or {}
            if c.get("direct_message_link"):
                return True
            for ev in c.get("evidence") or []:
                t = ev.get("type") if isinstance(ev, dict) else None
                if t in ("explicit_work_item_ref", "direct_source_message_link"):
                    return True
            return False

        pr = dict(validated.get("project_resolution") or {})
        wr = dict(validated.get("work_item_resolution") or {})
        project_id = validated.get("resolved_project_id")
        work_item_id = validated.get("resolved_work_item_id")
        # Schema v1 fixtures may omit work_item_resolution.decision — preserve legacy
        explicit_decision = wr.get("decision")
        if explicit_decision:
            decision = explicit_decision
        elif validated.get("contains_work"):
            decision = "new"
        elif validated.get("should_ignore"):
            decision = "none"
        else:
            decision = "unclear"
        legacy_wi_mode = not bool(explicit_decision)

        ambiguous = self.source_id.project_mapping_state in ("ambiguous", "unmapped")
        eligible = bool(policy.get("eligible_for_proposed_selection"))
        proposed_id = policy.get("proposed_project_id")
        if proposed_id:
            proposed_id = int(proposed_id)

        if project_id is not None and cand_projects and project_id not in cand_projects:
            project_id = None
        if work_item_id is not None and cand_wis and work_item_id not in cand_wis:
            work_item_id = None
            if decision == "existing":
                decision = "unclear"

        # Existing requires existing-grade evidence: a direct source-message→WI
        # link or an explicit Work Item id. Weak inferred title overlap is not
        # enough — downgrade to new (if actionable) or unclear.
        if (
            not legacy_wi_mode
            and decision == "existing"
            and work_item_id
            and not _wi_existing_grade(work_item_id)
        ):
            work_item_id = None
            wr["work_item_id"] = None
            wr["work_item_title"] = None
            decision = "new" if seg_actionable else "unclear"
            wr["decision"] = decision

        # Fill proposed project when Dify withheld it — but not for pure noise/none
        classification = validated.get("classification_v2") or validated.get(
            "classification"
        )
        noise_like = classification in (
            "noise",
            "unrelated",
            "information",
        ) or validated.get("should_ignore")
        if seg_actionable and noise_like and not direct_wis:
            validated["should_ignore"] = False
            validated["classification_v2"] = "unclear"
            validated["classification"] = "information"
            classification = "unclear"
            noise_like = False
        if (
            project_id is None
            and eligible
            and proposed_id
            and proposed_id in cand_projects
        ):
            project_id = proposed_id
            pr["project_id"] = proposed_id
            pr["project_name"] = policy.get("proposed_project_name")
            pr["confidence"] = policy.get("proposed_confidence") or pr.get("confidence")
            pr["resolution_status"] = "proposed"
            evidence = list(pr.get("evidence") or [])
            evidence.append(
                {
                    "type": "odoo_selection_policy",
                    "value": policy.get("selection_reason")
                    or "proposed_unique_candidate",
                }
            )
            pr["evidence"] = evidence
            # A unique strong Odoo candidate means the segment is about that
            # project. Dify calling it noise/none is inconsistent — surface as
            # reviewable work rather than ignore.
            if noise_like and decision == "none" and not direct_wis:
                noise_like = False
                validated["should_ignore"] = False
                validated["classification_v2"] = "unclear"
                validated["classification"] = "information"
                classification = "unclear"
                decision = "new"
                wr["decision"] = "new"
        elif (
            eligible
            and project_id
            and noise_like
            and decision == "none"
            and not direct_wis
        ):
            # Dify already picked the eligible project but still marked noise/none.
            noise_like = False
            validated["should_ignore"] = False
            validated["classification_v2"] = "unclear"
            validated["classification"] = "information"
            classification = "unclear"
            decision = "new"
            wr["decision"] = "new"
        elif (
            noise_like
            and decision == "none"
            and not direct_wis
            and not eligible
        ):
            # Do not commit incidental alias hits on genuine noise segments
            project_id = None
            pr["project_id"] = None
            pr["resolution_status"] = "unresolved"

        # Safety: on ambiguous sources, Odoo eligibility is authoritative.
        # Dify may not arbitrate candidates that Odoo rejected as too close,
        # incidental, historical, media-weak, or not the current topic.
        if project_id is not None and ambiguous and not eligible and not direct_wis:
            project_id = None
            pr["project_id"] = None
            pr["resolution_status"] = "unresolved"
            gate_reason = policy.get("selection_reason")
            evidence = list(pr.get("evidence") or [])
            evidence.append(
                {
                    "type": "odoo_selection_policy",
                    "value": gate_reason or "candidate_not_eligible",
                }
            )
            pr["evidence"] = evidence

        requires_confirmation = bool(
            ambiguous
            or policy.get("requires_project_confirmation")
            or validated.get("requires_project_confirmation")
            or not project_id
        )
        pr["requires_confirmation"] = requires_confirmation
        if project_id and eligible:
            pr["resolution_status"] = pr.get("resolution_status") or "proposed"

        if direct_wis:
            # Honour Dify's Work Item pick when it is one of the directly
            # linked candidates; otherwise fall back to the first direct link.
            top_wi = None
            if work_item_id:
                top_wi = next(
                    (
                        c
                        for c in direct_wis
                        if int(c["work_item_id"]) == int(work_item_id)
                    ),
                    None,
                )
            if not top_wi:
                top_wi = direct_wis[0]
            wi_id = int(top_wi["work_item_id"])
            wi_project = top_wi.get("project_id")
            # Direct message→WI link is authoritative for project on ambiguous sources
            if wi_project:
                project_id = int(wi_project)
                pr["project_id"] = project_id
                pr["resolution_status"] = "proposed"
                requires_confirmation = True
                pr["requires_confirmation"] = True
                evidence = list(pr.get("evidence") or [])
                evidence.append(
                    {
                        "type": "direct_source_message_link",
                        "value": "Project taken from linked Work Item %s" % wi_id,
                    }
                )
                pr["evidence"] = evidence
            reject_existing = False
            for ev in wr.get("evidence") or []:
                text = str(ev).lower()
                if "separate new" in text or "distinct new" in text:
                    reject_existing = True
            if not reject_existing and decision != "new":
                decision = "existing"
                work_item_id = wi_id
                wr["decision"] = "existing"
                wr["work_item_id"] = wi_id
                wr["work_item_title"] = top_wi.get("title")
                evidence = list(wr.get("evidence") or [])
                evidence.append(
                    {
                        "type": "direct_source_message_link",
                        "value": "Odoo boosted linked Work Item",
                    }
                )
                wr["evidence"] = evidence

        existing_grade_cands = [
            c
            for c in wi_cands
            if c.get("work_item_id") and _wi_existing_grade(c["work_item_id"])
        ]
        if (
            not legacy_wi_mode
            and decision == "none"
            and project_id
            and not noise_like
            and not direct_wis
        ):
            # Weak inferred title overlaps must not block a reviewable `new`.
            decision = "unclear" if existing_grade_cands else "new"
            wr["decision"] = decision

        if (
            not legacy_wi_mode
            and decision == "unclear"
            and project_id
            and seg_actionable
            and not direct_wis
            and not existing_grade_cands
        ):
            decision = "new"
            wr["decision"] = "new"

        # Conservative default: prefer unclear over none for non-noise segments
        # that still have substantive prose (meeting notes, open questions, etc.).
        if (
            not legacy_wi_mode
            and decision == "none"
            and not noise_like
            and not project_id
            and not direct_wis
            and not validated.get("should_ignore")
        ):
            prose_tokens = sum(
                Cand._prose_token_count(Cand._clean_user_text(m.body or ""))
                for m in self.batch_message_ids[:20]
            )
            if prose_tokens >= 8:
                decision = "unclear"
                wr["decision"] = "unclear"

        if decision == "existing" and work_item_id:
            wi = self.env["dev.work.item"].sudo().browse(work_item_id)
            if (
                project_id
                and wi.exists()
                and wi.dev_project_id
                and wi.dev_project_id.id != project_id
            ):
                decision = "unclear"
                work_item_id = None
                wr["decision"] = "unclear"
                wr["work_item_id"] = None

        # Conservative default for possible work is 'unclear', not 'none'.
        # An actionable segment marked 'none' by Dify should still surface for
        # human review unless it is genuine noise / acknowledgement. An
        # actionable classification (bug / new_task / followup) is inconsistent
        # with a 'none' decision.
        classification_v2 = validated.get("classification_v2")
        actionable_class = classification_v2 in (
            "bug",
            "new_task",
            "existing_work_followup",
        )
        if (
            not legacy_wi_mode
            and decision == "none"
            and not noise_like
            and (seg_actionable or actionable_class)
            and not validated.get("should_ignore")
            and not direct_wis
        ):
            decision = "unclear"
            wr["decision"] = "unclear"

        # 'new' work cannot be committed without a resolved project — downgrade
        # to 'unclear' so a reviewer picks the project first.
        if not legacy_wi_mode and decision == "new" and not project_id:
            decision = "unclear"
            wr["decision"] = "unclear"

        contains_work = decision in ("new", "existing")
        if legacy_wi_mode and validated.get("contains_work") and not validated.get(
            "should_ignore"
        ):
            contains_work = True
            if decision not in ("new", "existing"):
                decision = "new"
        if validated.get("should_ignore"):
            recommended_action = "ignore"
        elif decision == "existing":
            recommended_action = "attach_existing"
        elif decision == "new" or (
            legacy_wi_mode and validated.get("recommended_action") == "create_work"
        ):
            recommended_action = validated.get("recommended_action") or "create_work"
        elif classification == "question":
            recommended_action = "reply"
        else:
            recommended_action = "request_context"

        if legacy_wi_mode and not wr.get("decision"):
            wr["decision"] = decision

        validated = dict(validated)
        validated["project_resolution"] = pr
        validated["work_item_resolution"] = wr
        validated["resolved_project_id"] = project_id
        validated["resolved_work_item_id"] = work_item_id
        validated["requires_project_confirmation"] = requires_confirmation
        validated["contains_work"] = contains_work and not validated.get("should_ignore")
        validated["recommended_action"] = recommended_action
        validated["safe_to_create_work"] = (
            (decision == "new" or (legacy_wi_mode and contains_work))
            and bool(project_id or self.dev_project_id)
        )
        validated["safe_to_attach_to_existing_work"] = (
            decision == "existing" and bool(work_item_id)
        )
        validated["project_resolution_status"] = (
            "proposed"
            if project_id and requires_confirmation
            else ("confirmed" if project_id else "unresolved")
        )
        return validated

    def _apply_validated(self, validated, raw_text, provider_model=None):
        self.ensure_one()
        Message = self.env["whatsapp.message"]
        batch = set(self.batch_message_ids.ids)
        if not self.project_candidates_json or not self.selection_policy_json:
            self._job_payload()
        validated = self._enforce_odoo_resolution_policy(validated)
        # Re-validate membership + group
        for mid in (
            validated["source_message_ids"]
            + validated["noise_message_ids"]
            + validated["work_message_ids"]
        ):
            if mid not in batch:
                raise ValidationError("Validated id %s escaped batch check." % mid)
            msg = Message.browse(mid)
            if msg.group_jid != self.group_jid:
                raise ValidationError("Message %s group_jid mismatch." % mid)

        # Server-side multi-task: prefer items length; never trust LLM alone
        items = validated.get("analysis_items") or validated.get("items") or []
        if items:
            contains_multiple = len(items) > 1
        else:
            contains_multiple = bool(
                self.segment_total and self.segment_total > 1
            ) or bool(validated.get("contains_multiple_tasks"))

        # Merge deterministic technical evidence into analysis_detail when LLM omitted paths
        detail = dict(validated.get("analysis_detail") or {})
        try:
            tech = json.loads(self.technical_evidence_json or "{}") or {}
        except Exception:
            tech = {}
        if not tech and self.batch_message_ids:
            tech = extract_from_messages(self.batch_message_ids)
            vals_tech = {"technical_evidence_json": safe_json_dumps(tech)}
        else:
            vals_tech = {}
        if tech:
            paths = list(detail.get("affected_paths") or [])
            for p in tech.get("detected_paths") or []:
                if p not in paths:
                    paths.append(p)
            if paths:
                detail["affected_paths"] = paths
            modules = list(detail.get("affected_modules") or [])
            for m in tech.get("detected_modules") or []:
                if m not in modules:
                    modules.append(m)
            if modules:
                detail["affected_modules"] = modules
            errors = list(detail.get("technical_evidence") or [])
            for e in tech.get("detected_errors") or []:
                if e not in errors:
                    errors.append(e)
            for tb in (tech.get("tracebacks") or [])[:2]:
                if tb not in errors:
                    errors.append(tb[:500])
            if errors:
                detail["technical_evidence"] = errors
            validated["analysis_detail"] = detail

            # Deterministic multi-issue signal: RPC/traceback + distinct functional module
            # evidence must not collapse to a single LLM task.
            has_rpc = any(
                "RPC_ERROR" in str(e) or "Traceback" in str(e)
                for e in (tech.get("detected_errors") or []) + (tech.get("tracebacks") or [])
            )
            functional_mods = {
                m
                for m in (tech.get("detected_modules") or [])
                if m
                in (
                    "batch_intake",
                    "edafaa_student_profile",
                    "student_enrollment_portal",
                )
            }
            if has_rpc and len(functional_mods) >= 1 and not items:
                # RPC upgrade failure vs functional Batch Intake are distinct workstreams
                if "batch_intake" in functional_mods or any(
                    "Batch Intake" in (m.body or "") for m in self.batch_message_ids
                ):
                    contains_multiple = True
                    validated["requires_human_review"] = True

        # Actionable create_work with empty acceptance → needs_review (never auto-valid)
        validation_state = validated.get("validation_state") or "valid"
        validation_errors = []
        action = validated.get("recommended_action")
        ac = detail.get("acceptance_criteria") or []
        if action in ("create_work", "create_multiple_work_items") and not items:
            if not ac:
                validation_state = "needs_review"
                validation_errors.append(
                    "acceptance_criteria empty for actionable create_work"
                )
                validated["requires_human_review"] = True
                validated["safe_to_create_work"] = False
        # Also reject empty questions when technical gaps / multi-task remain
        missing = validated.get("missing_information") or []
        if contains_multiple and not missing and not (detail.get("questions") or []):
            missing = [
                "Multiple distinct issues detected — confirm which items are still open",
                "Confirm reproduction environment for RPC_ERROR vs functional issues",
            ]
            validated["missing_information"] = missing
            validated["requires_human_review"] = True
            if validation_state == "valid" and action in (
                "create_work",
                "create_multiple_work_items",
            ):
                validation_state = "needs_review"
                validation_errors.append(
                    "multi-issue bundle requires segmented items or human review"
                )
                validated["safe_to_create_work"] = False
        validated["validation_state"] = validation_state
        validated["contains_multiple_tasks"] = contains_multiple

        vals = {
            "summary": validated["summary"],
            "classification": validated["classification"],
            "should_ignore": validated["should_ignore"],
            "ignore_reason": validated["ignore_reason"] or False,
            "contains_work": validated["contains_work"],
            "work_title": validated["work_title"] or False,
            "work_description": validated["work_description"] or False,
            "priority": validated["priority"],
            "confidence": validated["confidence"],
            "requires_human_review": validated["requires_human_review"],
            "recommended_action": validated["recommended_action"],
            "participants_json": safe_json_dumps(validated["participants"]),
            "missing_information_json": safe_json_dumps(validated["missing_information"]),
            "raw_response_json": (raw_text or "")[:200000],
            "validated_json": safe_json_dumps(validated),
            "noise_message_ids": [(6, 0, validated["noise_message_ids"])],
            "work_message_ids": [(6, 0, validated["work_message_ids"])],
            "completed_at": fields.Datetime.now(),
            "provider_model": provider_model or False,
            "error_code": False,
            "error_message": False,
            "resolved_project_id": validated.get("resolved_project_id") or False,
            "proposed_work_item_id": validated.get("resolved_work_item_id") or False,
            "work_item_decision": (
                (validated.get("work_item_resolution") or {}).get("decision")
                or False
            ),
            "requires_project_confirmation": bool(
                validated.get("requires_project_confirmation")
            ),
            "project_resolution_status": validated.get("project_resolution_status")
            or "unresolved",
            "contains_multiple_tasks": contains_multiple,
            "language": validated.get("language") or False,
            "analysis_detail_json": safe_json_dumps(detail),
            "evidence_json": safe_json_dumps(validated.get("evidence_used") or []),
            "safe_to_create_work": bool(validated.get("safe_to_create_work")),
            "safe_to_attach_to_existing_work": bool(
                validated.get("safe_to_attach_to_existing_work")
            ),
            "analysis_items_json": safe_json_dumps(items) if items else False,
            "validation_state": validation_state,
            "validation_errors_json": (
                safe_json_dumps(validation_errors) if validation_errors else False
            ),
            "schema_version": str(validated.get("schema_version") or self.schema_version),
        }
        vals.update(vals_tech)
        if validated.get("resolved_project_id"):
            vals["dev_project_id"] = validated["resolved_project_id"]
        meta = self.env.context.get("wa_ai_provider_meta") or {}
        if meta:
            vals.update(
                {
                    "dify_app_ref": meta.get("dify_app_ref") or False,
                    "dify_workflow_run_id": meta.get("dify_workflow_run_id") or False,
                    "n8n_execution_id": meta.get("n8n_execution_id") or False,
                    "provider_latency_ms": int(meta.get("provider_latency_ms") or 0),
                    "provider_token_usage_json": safe_json_dumps(
                        meta.get("token_usage") or {}
                    )
                    if meta.get("token_usage")
                    else False,
                    "provider": meta.get("provider") or self.provider or "dify_n8n",
                    "is_demo_result": bool(meta.get("is_demo_result")),
                }
            )

        source = self.source_id
        # Evaluation mode: never auto-ignore or mutate inbox.
        if self.is_evaluation_result:
            vals["state"] = "awaiting_review"
            vals["is_evaluation_result"] = True
            self.sudo().write(vals)
            return True
        auto_ignore = (
            source.auto_ignore_enabled
            and validated["should_ignore"]
            and validated["classification"] in NOISE_CLASSIFICATIONS
            and validated["confidence"] >= float(source.auto_ignore_min_confidence or 0.92)
            and not any(m.has_work_item for m in Message.browse(validated["noise_message_ids"] or validated["source_message_ids"]))
        )
        if auto_ignore:
            vals["state"] = "awaiting_review"  # still go through controlled method
            self.sudo().write(vals)
            self.action_approve_ignore(auto=True)
            return True

        if validated["requires_human_review"] or validated["contains_work"] or validated["should_ignore"]:
            vals["state"] = "awaiting_review"
        else:
            vals["state"] = "succeeded"
        self.sudo().write(vals)
        return True

    def action_ingest_fixture_json(self, raw_json):
        """Test helper: apply JSON without n8n. Disabled unless ICP allow_fixture_ai."""
        self.ensure_one()
        _require_manager(self.env)
        allow = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("devhub_whatsapp.allow_fixture_ai", "False")
        )
        if str(allow).lower() not in ("1", "true", "yes"):
            raise UserError(
                "Fixture/demo AI completion is disabled on this database. "
                "Use the live n8n → Dify path (provider=dify_n8n)."
            )
        if self.state not in ("pending", "running", "failed", "awaiting_review"):
            raise UserError("Cannot ingest fixture in state %s." % self.state)
        # Ensure candidates exist for validation
        if not self.project_candidates_json:
            self._job_payload()
        import json as _json

        project_ids = [
            c.get("project_id")
            for c in (_json.loads(self.project_candidates_json or "[]") or [])
        ]
        wi_ids = [
            c.get("work_item_id")
            for c in (_json.loads(self.work_item_candidates_json or "[]") or [])
        ]
        validated = validate_ai_response(
            raw_json,
            self.batch_message_ids.ids,
            project_candidate_ids=project_ids,
            work_item_candidate_ids=wi_ids,
        )
        self.write({"state": "running", "started_at": fields.Datetime.now()})
        self.with_context(
            wa_ai_provider_meta={
                "provider": "fixture",
                "is_demo_result": True,
                "dify_app_ref": "fixture",
            }
        )._apply_validated(validated, raw_json, provider_model="fixture")
        for job in self.job_ids.filtered(
            lambda j: j.state in ("pending", "retry", "leased", "processing")
        ):
            job.with_context(dev_wa_analysis_action=True).write(
                {
                    "state": "succeeded",
                    "completed_at": fields.Datetime.now(),
                    "response_json": (raw_json or "")[:200000],
                    "lease_owner_id": False,
                    "lease_consumer_ref": False,
                    "lease_token": False,
                    "lease_expires_at": False,
                    "last_error_code": False,
                    "last_error_summary": False,
                }
            )
        return True

    def action_apply_demo_result(self):
        """Blocked unless allow_fixture_ai ICP is enabled."""
        return self._apply_demo_legacy()

    def _apply_demo_legacy(self):
        self.ensure_one()
        _require_manager(self.env)
        if self.state not in ("pending", "running", "failed"):
            raise UserError(
                "Demo result can only be applied while Pending, Running, or Failed."
            )
        msgs = self.batch_message_ids.sorted("id")
        if not msgs:
            raise UserError("No batch messages to analyse.")
        msg_ids = msgs.ids
        bodies = []
        participants = []
        for msg in msgs[:12]:
            body = (msg.body or "").strip().replace("\n", " ")
            if body:
                bodies.append(body[:160])
            sender = (msg.sender_jid or "").strip()
            if sender and sender not in participants:
                participants.append(sender)
        excerpt = " | ".join(bodies[:5]) or "(empty bodies)"
        group_name = self.source_id.name or self.group_jid or "WhatsApp group"
        title = ("WA: %s" % group_name)[:120]
        payload = {
            "schema_version": "1",
            "summary": (
                "Demo AI result (fixture). Batch of %s messages from %s. Excerpt: %s"
            )
            % (len(msg_ids), group_name, excerpt[:500]),
            "classification": "bug_report",
            "should_ignore": False,
            "ignore_reason": None,
            "contains_work": True,
            "work_title": title,
            "work_description": (
                "Demo Work Item proposed from WhatsApp batch (fixture).\n\n"
                "Messages:\n- %s"
            )
            % "\n- ".join(bodies[:10] or ["(no text)"]),
            "priority": "2",
            "project_reference": None,
            "participants": participants[:20],
            "source_message_ids": msg_ids,
            "noise_message_ids": [],
            "work_message_ids": msg_ids,
            "confidence": 0.88,
            "requires_human_review": True,
            "recommended_action": "create_work",
            "missing_information": [],
        }
        self.action_ingest_fixture_json(json.dumps(payload))
        return True

    def action_approve_ignore(self, auto=False):
        self.ensure_one()
        if self.is_evaluation_result:
            raise UserError(
                "Evaluation analyses cannot mutate inbox states (ignore blocked)."
            )
        if not auto:
            _require_manager(self.env)
        if self.state not in ("awaiting_review", "succeeded"):
            raise UserError("Analysis is not ready for ignore approval.")
        if not self.should_ignore:
            raise UserError("Analysis does not recommend ignore.")
        targets = self.noise_message_ids or self.batch_message_ids
        if any(m.has_work_item for m in targets):
            raise UserError("Cannot ignore messages already linked to a Work Item.")
        for msg in targets:
            if msg.id not in self.batch_message_ids.ids:
                raise ValidationError("Ignore target %s not in batch." % msg.id)
            if msg.group_jid != self.group_jid:
                raise ValidationError("Ignore target group mismatch.")
            msg._inbox_set_state(
                "ignored",
                event_type="ai_ignore",
                note="analysis_id=%s conf=%.2f" % (self.id, self.confidence or 0.0),
            )
        self.write(
            {
                "state": "applied",
                "applied_at": fields.Datetime.now(),
                "approved_by": self.env.user.id,
            }
        )
        self.message_post(
            body="Ignore applied for %s message(s) from AI analysis #%s."
            % (len(targets), self.id)
        )
        return True

    def action_reject_ignore(self):
        self.ensure_one()
        _require_manager(self.env)
        if self.state != "awaiting_review":
            raise UserError("Nothing to reject.")
        self.write(
            {
                "state": "rejected",
                "rejected_by": self.env.user.id,
                "should_ignore": False,
            }
        )
        self.message_post(body="AI ignore recommendation rejected.")
        return True

    def action_restore_messages(self):
        self.ensure_one()
        if self.is_evaluation_result:
            raise UserError("Evaluation analyses cannot restore/mutate inbox states.")
        _require_user(self.env)
        targets = self.noise_message_ids or self.batch_message_ids
        targets.action_inbox_restore()
        self.message_post(body="Restored %s message(s) from AI ignore." % len(targets))
        return True

    def action_approve_create_work(self):
        self.ensure_one()
        if self.is_evaluation_result:
            raise UserError(
                "Evaluation analyses cannot create Work Items. Review only."
            )
        _require_manager(self.env)
        if self.state not in ("awaiting_review", "succeeded"):
            raise UserError("Analysis is not ready for Work Item creation.")
        if self.work_item_id:
            raise UserError("A Work Item is already linked to this analysis.")
        if not self.contains_work:
            raise UserError("Analysis does not contain actionable work.")
        if not (self.work_title and self.work_description):
            raise UserError("Work title and description are required.")

        # Acceptance criteria gate (schema v3 / analysis_detail)
        validated = {}
        try:
            validated = json.loads(self.validated_json or "{}") or {}
        except (TypeError, ValueError, json.JSONDecodeError):
            validated = {}
        if self.analysis_items_json:
            try:
                validated["analysis_items"] = (
                    json.loads(self.analysis_items_json or "[]") or []
                )
            except (TypeError, ValueError, json.JSONDecodeError):
                pass
        validate_actionable_acceptance(validated)

        # Orchestration / dedup — block unless manager force context
        force = bool(self.env.context.get("wa_orchestration_force"))
        Orchestration = self.env["dev.whatsapp.work.orchestration"]
        Orchestration.assert_create_allowed(self, force=force)

        messages = self.work_message_ids or self.batch_message_ids
        if not messages:
            raise UserError("No work messages to link.")
        for msg in messages:
            if msg.id not in self.batch_message_ids.ids:
                raise ValidationError("Work message %s not in batch." % msg.id)
            if msg.group_jid != self.group_jid:
                raise ValidationError("Work message group mismatch.")

        linked = messages.mapped("work_item_ids")
        if linked:
            raise UserError(
                "One or more messages already link to Work Item(s): %s. "
                "Open the existing Work Item instead."
                % ", ".join(linked.mapped("name")[:5])
            )

        project = self.dev_project_id
        project.check_access("read")
        source = self.source_id
        odoo_project = source.odoo_project_id
        if not odoo_project:
            raise UserError("WhatsApp source has no Odoo project configured.")
        odoo_project.check_access("read")

        source_msgs = messages._dh_ensure_source_messages()
        Work = self.env["dev.work.item"]
        work = Work.create(
            {
                "name": (self.work_title or "")[:300],
                "dev_project_id": project.id,
                "odoo_project_id": odoo_project.id,
                "preferred_environment_id": source.default_environment_id.id or False,
                "preferred_repository_id": source.default_repository_id.id or False,
                "responsible_user_id": self.env.user.id,
                "priority_cache": self.priority or "0",
                "source_message_ids": [(6, 0, source_msgs.ids)],
                "source_type": "whatsapp_ai",
                "origin_ai_whatsapp": True,
                "whatsapp_analysis_id": self.id,
            }
        )
        for msg in messages:
            msg._inbox_set_state(
                "actioned",
                event_type="ai_work_created",
                note="analysis_id=%s work_item_id=%s" % (self.id, work.id),
            )
            msg._inbox_log(
                "work_created",
                msg.inbox_state,
                msg.inbox_state,
                note="AI analysis %s → work %s" % (self.id, work.id),
                work=work,
            )
        self.write(
            {
                "work_item_id": work.id,
                "state": "applied",
                "applied_at": fields.Datetime.now(),
                "approved_by": self.env.user.id,
            }
        )
        work.message_post(
            body=(
                "Created from WhatsApp AI analysis #%s (fingerprint %s…). "
                "Summary: %s"
                % (self.id, (self.batch_fingerprint or "")[:12], (self.summary or "")[:400])
            )
        )
        self.message_post(body="Work Item #%s created and linked." % work.id)
        return {
            "type": "ir.actions.act_window",
            "name": "Work Item",
            "res_model": "dev.work.item",
            "res_id": work.id,
            "view_mode": "form",
            "views": [(False, "form")],
            "target": "current",
        }

    def action_approve_attach_existing(self):
        """Attach batch messages as context on the proposed existing Work Item."""
        self.ensure_one()
        if self.is_evaluation_result:
            raise UserError(
                "Evaluation analyses cannot attach Work Items. Review only."
            )
        _require_manager(self.env)
        if self.state not in ("awaiting_review", "succeeded"):
            raise UserError("Analysis is not ready for attach approval.")
        if self.work_item_id:
            raise UserError("A Work Item is already linked to this analysis.")
        work = self.proposed_work_item_id
        if not work:
            raise UserError("No proposed existing Work Item on this analysis.")
        resolved = self.resolved_project_id or self.dev_project_id
        if work.dev_project_id != resolved:
            raise UserError("Proposed Work Item is not in the resolved project.")
        messages = self.work_message_ids or self.batch_message_ids
        source_msgs = messages._dh_ensure_source_messages()
        source_msgs.write({"work_item_ids": [(4, work.id)]})
        for msg in messages:
            if msg.id not in self.batch_message_ids.ids:
                raise ValidationError("Message %s not in batch." % msg.id)
            msg._inbox_set_state(
                "actioned",
                event_type="ai_work_attached",
                note="analysis_id=%s work_item_id=%s" % (self.id, work.id),
            )
        self.write(
            {
                "work_item_id": work.id,
                "state": "applied",
                "applied_at": fields.Datetime.now(),
                "approved_by": self.env.user.id,
            }
        )
        work.message_post(
            body="Attached WhatsApp AI analysis #%s as follow-up context." % self.id
        )
        self.message_post(body="Attached to existing Work Item #%s." % work.id)
        return {
            "type": "ir.actions.act_window",
            "name": "Work Item",
            "res_model": "dev.work.item",
            "res_id": work.id,
            "view_mode": "form",
            "views": [(False, "form")],
            "target": "current",
        }

    def action_save_historical_review(self):
        """Persist reviewer questionnaire answers without mutating inbox/WIs."""
        self.ensure_one()
        _require_manager(self.env)
        if not self.is_evaluation_result:
            raise UserError(
                "Historical reviewer questionnaire is only for evaluation analyses."
            )
        if not self.review_final_decision or not self.review_usefulness:
            raise UserError(
                "Set Final review decision (Q11) and Overall usefulness (Q12) before saving."
            )
        self.write(
            {
                "review_completed_by": self.env.user.id,
                "review_completed_at": fields.Datetime.now(),
            }
        )
        self.message_post(
            body=(
                "Historical review saved — decision=%s usefulness=%s "
                "(no inbox / Work Item mutations)."
                % (self.review_final_decision, self.review_usefulness)
            )
        )
        return True

    def action_reject_analysis(self):
        self.ensure_one()
        _require_manager(self.env)
        if self.state in ("applied",):
            raise UserError("Applied analysis cannot be rejected; restore messages if needed.")
        self.write({"state": "rejected", "rejected_by": self.env.user.id})
        for job in self.job_ids.filtered(lambda j: j.state in ("pending", "retry")):
            job.with_context(dev_wa_analysis_action=True).write({"state": "cancelled"})
        self.message_post(body="Analysis rejected; no inbox or Work Item changes.")
        return True

    def action_confirm_proposed_project(self):
        """Human confirms the proposed project (no WI create/attach)."""
        self.ensure_one()
        if self.is_evaluation_result:
            raise UserError("Evaluation analyses are review-only.")
        _require_manager(self.env)
        if not self.resolved_project_id:
            raise UserError("No proposed project to confirm.")
        self.write(
            {
                "project_resolution_status": "confirmed",
                "requires_project_confirmation": False,
                "dev_project_id": self.resolved_project_id.id,
            }
        )
        self.message_post(
            body="Proposed project confirmed: %s" % self.resolved_project_id.display_name
        )
        return True

    def action_reject_proposed_project(self):
        """Reject proposed project resolution."""
        self.ensure_one()
        if self.is_evaluation_result:
            raise UserError("Evaluation analyses are review-only.")
        _require_manager(self.env)
        self.write(
            {
                "project_resolution_status": "rejected",
                "resolved_project_id": False,
                "requires_project_confirmation": True,
                "safe_to_create_work": False,
                "safe_to_attach_to_existing_work": False,
            }
        )
        self.message_post(body="Proposed project resolution rejected.")
        return True

    def action_choose_different_project(self):
        """Open form to manually choose resolved_project_id."""
        self.ensure_one()
        _require_manager(self.env)
        if self.is_evaluation_result:
            raise UserError("Evaluation analyses are review-only.")
        return {
            "type": "ir.actions.act_window",
            "name": "Choose Different Project",
            "res_model": "dev.whatsapp.analysis",
            "res_id": self.id,
            "view_mode": "form",
            "target": "current",
            "context": {"form_view_initial_mode": "edit"},
        }

    def action_reanalyse(self):
        self.ensure_one()
        _require_manager(self.env)
        return self.action_enqueue_analysis(
            self.source_id.id, force=True, force_reanalyse=True
        )

    def action_open_work_item(self):
        self.ensure_one()
        if not self.work_item_id:
            raise UserError("No linked Work Item.")
        work = self.env["dev.work.item"].browse(self.work_item_id.id)
        work.check_access("read")
        return {
            "type": "ir.actions.act_window",
            "res_model": "dev.work.item",
            "res_id": work.id,
            "view_mode": "form",
            "views": [(False, "form")],
            "target": "current",
        }

    def action_retry_failed_job(self):
        self.ensure_one()
        _require_manager(self.env)
        job = self.job_ids.filtered(lambda j: j.state in ("dead_letter", "failed"))[:1]
        if not job:
            job = self.job_ids.sorted("id", reverse=True)[:1]
        if not job:
            raise UserError("No job to retry.")
        job.with_context(dev_wa_analysis_action=True).write(
            {
                "state": "pending",
                "next_attempt_at": fields.Datetime.now(),
                "last_error_code": False,
                "last_error_summary": False,
            }
        )
        self.write({"state": "pending", "error_code": False, "error_message": False})
        return True

    @api.model
    def action_enqueue_by_group_jid(
        self, group_jid, force=True, date_from=None, date_to=None
    ):
        """Work Inbox helper: enqueue analysis for a group JID."""
        _require_manager(self.env)
        jid = (group_jid or "").strip()
        if not jid:
            raise UserError("group_jid is required.")
        source = self.env["dev.whatsapp.source"].search(
            [("group_jid", "=", jid), ("active", "=", True)], limit=1
        )
        if not source:
            raise UserError("No Dev Hub WhatsApp source for this group.")
        return self.action_enqueue_analysis(
            source.id,
            force=force,
            date_from=date_from or None,
            date_to=date_to or None,
        )

    @api.model
    def action_enqueue_all_enabled_sources(self, date_from=None, date_to=None):
        """Analyse all AI-enabled sources for the given date window (Work Inbox C)."""
        _require_manager(self.env)
        sources = self.env["dev.whatsapp.source"].search(
            [("active", "=", True), ("ai_triage_enabled", "=", True)]
        )
        created = []
        skipped = []
        errors = []
        for source in sources:
            try:
                analysis = self.action_enqueue_analysis(
                    source.id,
                    force=True,
                    date_from=date_from or None,
                    date_to=date_to or None,
                )
                created.append(
                    {
                        "source_id": source.id,
                        "source_name": source.name,
                        "analysis_id": analysis.id,
                        "state": analysis.state,
                        "msg_count": len(analysis.batch_message_ids),
                    }
                )
            except UserError as err:
                skipped.append(
                    {
                        "source_id": source.id,
                        "source_name": source.name,
                        "reason": str(err),
                    }
                )
            except Exception as err:  # noqa: BLE001 — surface per-source failure
                errors.append(
                    {
                        "source_id": source.id,
                        "source_name": source.name,
                        "reason": str(err),
                    }
                )
        return {
            "created": created,
            "skipped": skipped,
            "errors": errors,
            "date_from": date_from or False,
            "date_to": date_to or False,
        }

    @api.model
    def get_group_analyses_payload(self, group_jid, limit=20):
        """List AI analyses for a group (Work Inbox AI tab)."""
        _require_user(self.env)
        jid = (group_jid or "").strip()
        if not jid:
            return {"analyses": []}
        limit = max(1, min(int(limit or 20), 50))
        rows = self.search(
            [("group_jid", "=", jid)], order="id desc", limit=limit
        )
        out = []
        for rec in rows:
            batch_preview = []
            for msg in rec.batch_message_ids.sorted(
                key=lambda m: (m.message_timestamp or fields.Datetime.now(), m.id)
            )[:30]:
                sender = (msg.sender_jid or "").split("@")[0] or "unknown"
                batch_preview.append(
                    {
                        "id": msg.id,
                        "timestamp": fields.Datetime.to_string(msg.message_timestamp)
                        if msg.message_timestamp
                        else False,
                        "sender": sender,
                        "inbox_state": msg.inbox_state or False,
                        "body": ((msg.body or "").replace("\n", " ").strip()[:180] or "(empty)"),
                    }
                )
            class_labels = dict(CLASSIFICATION_SEL)
            action_labels = dict(ACTION_SEL)
            out.append(
                {
                    "id": rec.id,
                    "name": rec.name,
                    "state": rec.state,
                    "summary": (rec.summary or "")[:800],
                    "classification": rec.classification or False,
                    "classification_label": class_labels.get(rec.classification)
                    if rec.classification
                    else False,
                    "confidence": rec.confidence,
                    "recommended_action": rec.recommended_action or False,
                    "recommended_action_label": action_labels.get(rec.recommended_action)
                    if rec.recommended_action
                    else False,
                    "should_ignore": rec.should_ignore,
                    "contains_work": rec.contains_work,
                    "work_title": rec.work_title or False,
                    "work_description": (rec.work_description or "")[:600] or False,
                    "work_item_id": rec.work_item_id.id or False,
                    "work_item_name": rec.work_item_id.name if rec.work_item_id else False,
                    "requested_at": fields.Datetime.to_string(rec.requested_at)
                    if rec.requested_at
                    else False,
                    "completed_at": fields.Datetime.to_string(rec.completed_at)
                    if rec.completed_at
                    else False,
                    "batch_count": len(rec.batch_message_ids),
                    "batch_messages": batch_preview,
                    "batch_truncated": len(rec.batch_message_ids) > len(batch_preview),
                    "scope_note": "Only New + Pending inbox messages (not Actioned/Ignored).",
                    "prompt_version": rec.prompt_version,
                    "error_message": rec.error_message or False,
                    "source_name": rec.source_id.name or False,
                }
            )
        return {"analyses": out, "group_jid": jid}

    @api.model
    def get_ai_badges_for_groups(self, group_jids):
        """Latest analysis state per group_jid for Work Inbox badges."""
        _require_user(self.env)
        jids = [str(j).strip() for j in (group_jids or []) if j]
        if not jids:
            return {}
        Analysis = self
        result = {}
        for jid in jids:
            rec = Analysis.search([("group_jid", "=", jid)], order="id desc", limit=1)
            if not rec:
                result[jid] = {
                    "ai_state": False,
                    "ai_label": False,
                    "ai_analysis_id": False,
                }
                continue
            label = {
                "pending": "queued",
                "running": "running",
                "awaiting_review": "review",
                "succeeded": "ready",
                "applied": "applied",
                "rejected": "rejected",
                "failed": "failed",
            }.get(rec.state, rec.state)
            result[jid] = {
                "ai_state": rec.state,
                "ai_label": label,
                "ai_analysis_id": rec.id,
            }
        return result
