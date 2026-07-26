# -*- coding: utf-8 -*-
from __future__ import annotations

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from odoo.addons.devhub_work.models.dev_work_utils import (
    MAX_TEXT,
    SECRET_PATTERN,
    FORBIDDEN_CONTENT,
    FORBIDDEN_JSON_KEYS,
    LIFECYCLE_SELECTION,
    LIFECYCLE_TRANSITIONS,
    _uuid,
    _canonical_hash,
    _clean_text,
    _clean_note_text,
    _bounded,
    _neutralize_forbidden,
    _context_text,
    _validate_text_values,
    _normalize_aliases,
    _validate_json_value,
    _validated_json,
    _require_approver,
    _require_importer,
)

class DevWorkLifecycleEvent(models.Model):
    _name = "dev.work.lifecycle.event"
    _description = "Immutable Development Work Lifecycle Event"
    _order = "occurred_at desc, id desc"

    work_item_id = fields.Many2one(
        "dev.work.item", required=True, ondelete="restrict", index=True, readonly=True
    )
    old_phase = fields.Selection(LIFECYCLE_SELECTION, readonly=True)
    new_phase = fields.Selection(LIFECYCLE_SELECTION, required=True, readonly=True)
    actor_type = fields.Selection(
        [("human", "Human"), ("automation", "Automation"), ("agent", "Agent")],
        required=True,
        readonly=True,
    )
    actor_id = fields.Many2one(
        "res.users", required=True, ondelete="restrict", readonly=True
    )
    occurred_at = fields.Datetime(required=True, readonly=True, index=True)
    timestamp = fields.Datetime(related="occurred_at", readonly=True)
    from_phase = fields.Selection(related="old_phase", readonly=True)
    to_phase = fields.Selection(related="new_phase", readonly=True)
    reason = fields.Text(required=True, readonly=True)
    correlation_id = fields.Char(required=True, readonly=True, index=True)
    artifact_model = fields.Char(readonly=True)
    artifact_record_id = fields.Integer(readonly=True)
    artifact_revision = fields.Integer(readonly=True)
    artifact_hash = fields.Char(readonly=True)
    policy_decision = fields.Text(readonly=True)

    _correlation_unique = models.Constraint(
        "unique(correlation_id)", "Lifecycle correlation ID must be unique."
    )

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("dev_internal_event"):
            raise AccessError("Lifecycle events may be created only by lifecycle actions.")
        return super().create(vals_list)

    def write(self, vals):
        raise AccessError("Lifecycle events are immutable.")

    def unlink(self):
        raise AccessError("Lifecycle events are immutable.")



class DevWorkSourceMessage(models.Model):
    _name = "dev.work.source.message"
    _description = "Development Work Source Message"
    _order = "message_timestamp desc, id desc"

    provider = fields.Selection(
        [("evolution", "Evolution"), ("chatwoot", "Chatwoot"), ("manual", "Manual")],
        required=True,
        index=True,
    )
    instance_reference = fields.Char(index=True)
    evolution_instance_ref = fields.Char(related="instance_reference", readonly=False)
    provider_message_id = fields.Char(index=True)
    extracted_item_index = fields.Integer(default=0, required=True)
    dedupe_key = fields.Char(required=True, readonly=True, copy=False, index=True)
    evolution_message_id = fields.Char(index=True)
    group_jid = fields.Char()
    sender_jid = fields.Char()
    chatwoot_account_id = fields.Integer(index=True)
    chatwoot_inbox_id = fields.Integer(index=True)
    chatwoot_conversation_id = fields.Integer(index=True)
    chatwoot_message_id = fields.Integer(index=True)
    message_timestamp = fields.Datetime(
        required=True, default=fields.Datetime.now, index=True
    )
    text_snapshot = fields.Text(required=True)
    sanitized_text = fields.Text(related="text_snapshot", readonly=False)
    text_hash = fields.Char(required=True, readonly=True)
    content_hash = fields.Char(related="text_hash", readonly=True)
    attachment_references = fields.Text(
        help="Sanitized URLs or opaque attachment references only; no attachment payload."
    )
    source_url = fields.Char()
    work_item_ids = fields.Many2many(
        "dev.work.item",
        "dev_work_item_source_message_rel",
        "source_message_id",
        "work_item_id",
    )

    _dedupe_unique = models.Constraint(
        "unique(dedupe_key)", "Source message extraction must be unique."
    )
    _provider_message_unique = models.UniqueIndex(
        "(provider, instance_reference, provider_message_id, extracted_item_index) "
        "WHERE provider_message_id IS NOT NULL",
        "This provider message extraction already exists.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            _normalize_aliases(
                vals,
                {
                    "evolution_instance_ref": "instance_reference",
                    "sanitized_text": "text_snapshot",
                },
            )
            _validate_text_values(self, vals, 6000)
            snapshot = _clean_text(vals.get("text_snapshot"), "Source text", 6000)
            if not snapshot:
                raise ValidationError("A sanitized source text snapshot is required.")
            identity = {
                "provider": vals.get("provider"),
                "instance": vals.get("instance_reference") or "",
                "message": vals.get("provider_message_id")
                or vals.get("chatwoot_message_id")
                or "",
                "index": vals.get("extracted_item_index", 0),
            }
            if not identity["message"]:
                raise ValidationError("A provider or Chatwoot message identity is required.")
            vals["dedupe_key"] = _canonical_hash(identity)
            vals["text_snapshot"] = snapshot
            vals["text_hash"] = _canonical_hash({"text": snapshot})
            _clean_text(vals.get("attachment_references"), "Attachment references", 4000)
        return super().create(vals_list)

    def write(self, vals):
        vals = dict(vals)
        _normalize_aliases(
            vals,
            {
                "evolution_instance_ref": "instance_reference",
                "sanitized_text": "text_snapshot",
            },
        )
        if {
            "provider",
            "instance_reference",
            "provider_message_id",
            "extracted_item_index",
            "dedupe_key",
            "text_snapshot",
            "text_hash",
        } & set(vals):
            raise AccessError("Source identity and sanitized snapshot are immutable.")
        _validate_text_values(self, vals, 6000)
        _clean_text(vals.get("attachment_references"), "Attachment references", 4000)
        return super().write(vals)



class DevWorkExternalLink(models.Model):
    _name = "dev.work.external.link"
    _description = "Development Work External Link"
    _order = "link_type, id"

    work_item_id = fields.Many2one(
        "dev.work.item", required=True, ondelete="cascade", index=True
    )
    link_type = fields.Selection(
        [
            ("github_issue", "GitHub Issue"),
            ("github_pr", "GitHub Pull Request"),
            ("commit", "Git Commit"),
            ("chatwoot", "Chatwoot"),
            ("attachment", "Attachment"),
            ("evidence", "Evidence"),
            ("other", "Other"),
        ],
        required=True,
        index=True,
    )
    name = fields.Char(required=True)
    external_id = fields.Char(index=True)
    external_reference = fields.Char(related="external_id", readonly=False)
    url = fields.Char(required=True)
    sync_state = fields.Selection(
        [("reference", "Reference"), ("synced", "Synced"), ("stale", "Stale")],
        default="reference",
        required=True,
    )
    last_sync_at = fields.Datetime()
    metadata_summary = fields.Text()

    _typed_external_unique = models.UniqueIndex(
        "(work_item_id, link_type, external_id) WHERE external_id IS NOT NULL",
        "This external identity is already linked to the work item.",
    )

    @api.constrains("name", "url", "metadata_summary")
    def _check_safe_fields(self):
        for record in self:
            _clean_text(record.name, "External link name", 300)
            _clean_text(record.url, "External link URL", 1000)
            _clean_text(record.metadata_summary, "External link metadata", 2000)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            _normalize_aliases(vals, {"external_reference": "external_id"})
            _validate_text_values(self, vals, 2000)
        return super().create(vals_list)

    def write(self, vals):
        vals = dict(vals)
        _normalize_aliases(vals, {"external_reference": "external_id"})
        _validate_text_values(self, vals, 2000)
        return super().write(vals)



class DevCompletionReport(models.Model):
    _name = "dev.completion.report"
    _description = "Versioned Development Completion Report"
    _order = "work_item_id, revision desc"

    work_item_id = fields.Many2one(
        "dev.work.item", required=True, ondelete="cascade", index=True
    )
    revision = fields.Integer(required=True, readonly=True, copy=False)
    parent_revision_id = fields.Many2one(
        "dev.completion.report", ondelete="restrict", readonly=True, copy=False
    )
    content_hash = fields.Char(required=True, readonly=True, copy=False, index=True)
    status = fields.Selection(
        [
            ("draft", "Draft"),
            ("ready_review", "Ready for Review"),
            ("approved", "Approved"),
            ("superseded", "Superseded"),
        ],
        default="draft",
        required=True,
        index=True,
    )
    original_request_summary = fields.Text(required=True)
    original_request = fields.Text(
        related="original_request_summary", readonly=False
    )
    source_message_ids = fields.Many2many(
        "dev.work.source.message",
        related="work_item_id.source_message_ids",
        readonly=True,
    )
    implemented_summary = fields.Text(required=True)
    plan_id = fields.Many2one("dev.work.plan", required=True, ondelete="restrict")
    completed_steps_summary = fields.Text(required=True)
    completed_steps = fields.Text(
        related="completed_steps_summary", readonly=False
    )
    skipped_steps_summary = fields.Text()
    skipped_steps = fields.Text(related="skipped_steps_summary", readonly=False)
    changed_components_summary = fields.Text(required=True)
    modules_files_changed = fields.Text(
        related="changed_components_summary", readonly=False
    )
    repository_reference = fields.Char(required=True)
    repository_id = fields.Many2one(
        "dev.repository", related="plan_id.work_item_id.preferred_repository_id"
    )
    branch = fields.Char(required=True)
    commit_references = fields.Text()
    pull_request_references = fields.Text()
    commit_pr_references = fields.Text(
        compute="_compute_commit_pr_references",
        inverse="_inverse_commit_pr_references",
    )
    tests_summary = fields.Text(required=True)
    tests_and_results = fields.Text(related="tests_summary", readonly=False)
    uat_status = fields.Selection(
        [
            ("not_applicable", "Not Applicable"),
            ("not_run", "Not Run"),
            ("pending", "Pending"),
            ("passed", "Passed"),
            ("failed", "Failed"),
        ],
        default="not_run",
        required=True,
    )
    uat_evidence_references = fields.Text()
    uat_result = fields.Selection(
        related="uat_status", readonly=False, string="UAT Result (Compatibility)"
    )
    evidence_references = fields.Text(
        related="uat_evidence_references", readonly=False
    )
    known_limitations = fields.Text(required=True)
    rollback_notes = fields.Text(required=True)
    rollback_deployment_notes = fields.Text(
        related="rollback_notes", readonly=False
    )
    deployment_status = fields.Selection(
        [
            ("not_deployed", "Not Deployed"),
            ("test", "Test"),
            ("staging", "Staging"),
            ("production", "Production"),
        ],
        default="not_deployed",
        required=True,
    )
    production_status = fields.Selection(
        [
            ("not_applicable", "Not Applicable"),
            ("not_verified", "Not Verified"),
            ("verified", "Verified"),
            ("failed", "Failed"),
        ],
        default="not_verified",
        required=True,
    )
    test_deployment_status = fields.Selection(
        related="deployment_status",
        readonly=False,
        string="Test Deployment Status (Compatibility)",
    )
    status_evidence_references = fields.Text()
    follow_up_items = fields.Text()
    generated_by = fields.Selection(
        [("human", "Human"), ("automation", "Automation"), ("agent", "Agent")],
        default="human",
        required=True,
    )
    run_reference = fields.Char()
    reviewer_id = fields.Many2one("res.users", ondelete="restrict", readonly=True)
    approved_at = fields.Datetime(readonly=True)
    approval_date = fields.Datetime(related="approved_at", readonly=True)
    schema_version = fields.Char(default="dev-completion-report.v1", required=True)

    _revision_unique = models.Constraint(
        "unique(work_item_id, revision)", "Report revision must be unique per work item."
    )

    @api.depends("commit_references", "pull_request_references")
    def _compute_commit_pr_references(self):
        for record in self:
            parts = [
                value
                for value in (
                    record.commit_references,
                    record.pull_request_references,
                )
                if value
            ]
            record.commit_pr_references = "\n".join(parts)

    def _inverse_commit_pr_references(self):
        for record in self:
            record.commit_references = record.commit_pr_references
            record.pull_request_references = False

    def _hash_values(self, values=None):
        self.ensure_one()
        values = values or {}
        names = (
            "original_request_summary",
            "implemented_summary",
            "completed_steps_summary",
            "skipped_steps_summary",
            "changed_components_summary",
            "repository_reference",
            "branch",
            "commit_references",
            "pull_request_references",
            "tests_summary",
            "uat_status",
            "uat_evidence_references",
            "known_limitations",
            "rollback_notes",
            "deployment_status",
            "production_status",
            "status_evidence_references",
            "follow_up_items",
            "schema_version",
        )
        payload = {name: values.get(name, self[name]) or "" for name in names}
        payload["plan_hash"] = self.plan_id.content_hash
        return _canonical_hash(payload)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            _normalize_aliases(
                vals,
                {
                    "original_request": "original_request_summary",
                    "completed_steps": "completed_steps_summary",
                    "skipped_steps": "skipped_steps_summary",
                    "modules_files_changed": "changed_components_summary",
                    "tests_and_results": "tests_summary",
                    "uat_result": "uat_status",
                    "evidence_references": "uat_evidence_references",
                    "rollback_deployment_notes": "rollback_notes",
                    "test_deployment_status": "deployment_status",
                },
            )
            if "commit_pr_references" in vals:
                vals.setdefault("commit_references", vals.pop("commit_pr_references"))
            work = self.env["dev.work.item"].browse(vals.get("work_item_id")).exists()
            plan = self.env["dev.work.plan"].browse(vals.get("plan_id")).exists()
            if not work or not plan or plan.work_item_id != work:
                raise ValidationError("Report plan must belong to its work item.")
            if plan.status != "approved":
                raise ValidationError("Completion report requires an approved plan.")
            if not vals.get("repository_reference") and work.preferred_repository_id:
                vals["repository_reference"] = (
                    work.preferred_repository_id.git_remote
                    or work.preferred_repository_id.name
                )
            latest = self.search(
                [("work_item_id", "=", work.id)], order="revision desc", limit=1
            )
            vals["revision"] = latest.revision + 1 if latest else 1
            vals["content_hash"] = "pending"
            if vals.get("status") == "approved":
                raise ValidationError("Use the explicit report approval action.")
            for name, value in vals.items():
                field = self._fields.get(name)
                if field and field.type in ("char", "text"):
                    _clean_text(value, field.string or name)
        records = super().create(vals_list)
        for record in records:
            super(DevCompletionReport, record).write(
                {"content_hash": record._hash_values()}
            )
        return records

    def write(self, vals):
        vals = dict(vals)
        _normalize_aliases(
            vals,
            {
                "original_request": "original_request_summary",
                "completed_steps": "completed_steps_summary",
                "skipped_steps": "skipped_steps_summary",
                "modules_files_changed": "changed_components_summary",
                "tests_and_results": "tests_summary",
                "uat_result": "uat_status",
                "evidence_references": "uat_evidence_references",
                "rollback_deployment_notes": "rollback_notes",
                "test_deployment_status": "deployment_status",
            },
        )
        if "commit_pr_references" in vals:
            vals.setdefault("commit_references", vals.pop("commit_pr_references"))
        if any(record.status in ("approved", "superseded") for record in self):
            raise AccessError("Approved and superseded reports are immutable.")
        if {
            "revision",
            "parent_revision_id",
            "content_hash",
            "work_item_id",
            "reviewer_id",
            "approved_at",
        } & set(vals):
            raise AccessError("Protected report fields are immutable.")
        if vals.get("status") == "approved":
            raise AccessError("Use the explicit report approval action.")
        for name, value in vals.items():
            field = self._fields.get(name)
            if field and field.type in ("char", "text"):
                _clean_text(value, field.string or name)
        result = super().write(vals)
        for record in self:
            super(DevCompletionReport, record).write(
                {"content_hash": record._hash_values()}
            )
        return result

    def action_ready_review(self):
        self.ensure_one()
        if self.status != "draft":
            raise UserError("Only a Draft report can be submitted.")
        super(DevCompletionReport, self).write({"status": "ready_review"})
        return True

    def action_approve(self):
        self.ensure_one()
        _require_approver(self.env)
        if self.work_item_id.current_phase != "ready_for_review":
            raise UserError("Report approval requires the Ready for Review phase.")
        if self.status != "ready_review":
            raise UserError("Only a report ready for review can be approved.")
        if self.uat_status not in ("not_applicable", "passed"):
            raise UserError("Report approval requires passed or not-applicable UAT.")
        if not self.repository_reference or not self.branch:
            raise UserError("Report approval requires repository and Git branch references.")
        old = self.work_item_id.completion_report_ids.filtered(
            lambda r: r.status == "approved" and r != self
        )
        if old:
            super(DevCompletionReport, old).write({"status": "superseded"})
        super(DevCompletionReport, self).write(
            {
                "status": "approved",
                "reviewer_id": self.env.user.id,
                "approved_at": fields.Datetime.now(),
            }
        )
        self.work_item_id._refresh_context_revision()
        return True

    def action_new_revision(self):
        self.ensure_one()
        values = self.copy_data()[0]
        values.update(
            parent_revision_id=self.id,
            status="draft",
            content_hash=False,
            revision=0,
            reviewer_id=False,
            approved_at=False,
        )
        return self.create(values)



class DevWorkCommunication(models.Model):
    _name = "dev.work.communication"
    _description = "Reviewed Development Work Communication"
    _order = "write_date desc, id desc"

    work_item_id = fields.Many2one(
        "dev.work.item", required=True, ondelete="cascade", index=True
    )
    completion_report_id = fields.Many2one(
        "dev.completion.report", ondelete="restrict"
    )
    source_message_id = fields.Many2one(
        "dev.work.source.message", ondelete="restrict"
    )
    communication_type = fields.Selection(
        [("completion", "Completion"), ("progress", "Progress"), ("blocker", "Blocker")],
        required=True,
        default="completion",
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("in_review", "In Review"),
            ("approved", "Approved"),
            ("queued", "Queued"),
        ],
        default="draft",
        required=True,
        readonly=True,
        index=True,
    )
    review_status = fields.Selection(related="state", readonly=True)
    language_code = fields.Char(default="ar")
    language = fields.Char(related="language_code", readonly=False)
    body = fields.Text(required=True)
    draft_message = fields.Text(related="body", readonly=False)
    chatwoot_account_id = fields.Integer()
    chatwoot_inbox_id = fields.Integer()
    chatwoot_conversation_id = fields.Integer(index=True)
    reply_to_chatwoot_message_id = fields.Integer()
    destination_type = fields.Selection(
        [("group_jid", "WhatsApp Group"), ("individual_jid", "WhatsApp Individual")],
        required=True,
        default="group_jid",
    )
    destination_reference = fields.Char()
    group_jid = fields.Char(related="destination_reference", readonly=False)
    reviewed_by = fields.Many2one("res.users", ondelete="restrict", readonly=True)
    reviewed_by_id = fields.Many2one(
        "res.users", related="reviewed_by", readonly=True
    )
    reviewed_at = fields.Datetime(readonly=True)
    review_hash = fields.Char(readonly=True, copy=False, index=True)
    approved_by = fields.Many2one("res.users", ondelete="restrict", readonly=True)
    approved_at = fields.Datetime(readonly=True)
    approved_hash = fields.Char(readonly=True, copy=False, index=True)
    send_approved = fields.Boolean(readonly=True)
    queued_at = fields.Datetime(readonly=True)
    idempotency_key = fields.Char(readonly=True, copy=False, index=True)
    chatwoot_message_id = fields.Integer(readonly=True, copy=False)
    chatwoot_outbound_message_id = fields.Integer(
        related="chatwoot_message_id", readonly=True
    )
    evolution_message_id = fields.Char(readonly=True, copy=False)
    evolution_provider_message_id = fields.Char(
        related="evolution_message_id", readonly=True
    )
    delivery_summary = fields.Char(readonly=True, copy=False)
    delivery_status = fields.Selection(
        [
            ("not_queued", "Not Queued"),
            ("queued", "Queued"),
            (
                "delivery_pending_confirmation",
                "Delivery Pending Confirmation",
            ),
            ("handed_off", "Handed Off"),
            ("delivered", "Delivered"),
            ("failed", "Failed"),
            ("dead_letter", "Dead Letter"),
        ],
        default="not_queued",
        required=True,
        readonly=True,
    )
    error_state = fields.Char(readonly=True)

    _idempotency_unique = models.UniqueIndex(
        "(idempotency_key) WHERE idempotency_key IS NOT NULL",
        "Communication idempotency key must be unique.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            _normalize_aliases(
                vals,
                {
                    "language": "language_code",
                    "draft_message": "body",
                    "group_jid": "destination_reference",
                },
            )
            report = self.env["dev.completion.report"].browse(
                vals.get("completion_report_id")
            ).exists()
            work = self.env["dev.work.item"].browse(vals.get("work_item_id")).exists()
            if report and report.work_item_id != work:
                raise ValidationError("Communication report must belong to the work item.")
            source = self.env["dev.work.source.message"].browse(
                vals.get("source_message_id")
            ).exists()
            if source and work not in source.work_item_ids:
                raise ValidationError("Source message must belong to the work item.")
            _validate_text_values(self, vals, 4000)
            _clean_text(vals.get("body"), "Communication body", 4000)
            _clean_text(
                vals.get("destination_reference"), "Destination reference", 300
            )
            if vals.get("state", "draft") != "draft":
                raise ValidationError("Communications must be created as Draft.")
        return super().create(vals_list)

    def write(self, vals):
        vals = dict(vals)
        _normalize_aliases(
            vals,
            {
                "language": "language_code",
                "draft_message": "body",
                "group_jid": "destination_reference",
            },
        )
        protected = {
            "state",
            "reviewed_by",
            "reviewed_at",
            "review_hash",
            "approved_by",
            "approved_at",
            "approved_hash",
            "queued_at",
            "idempotency_key",
            "chatwoot_message_id",
            "evolution_message_id",
            "delivery_summary",
            "delivery_status",
            "error_state",
            "send_approved",
        }
        if protected & set(vals):
            raise AccessError("Communication audit fields change only through actions.")
        if any(record.state != "draft" for record in self) and {
            "body",
            "destination_type",
            "destination_reference",
            "chatwoot_account_id",
            "chatwoot_inbox_id",
            "chatwoot_conversation_id",
            "reply_to_chatwoot_message_id",
        } & set(vals):
            raise AccessError(
                "Communication content and destination are immutable after review starts."
            )
        _validate_text_values(self, vals, 4000)
        _clean_text(vals.get("body"), "Communication body", 4000)
        return super().write(vals)

    def _message_destination_hash(self):
        self.ensure_one()
        return _canonical_hash(
            {
                "body": self.body or "",
                "language": self.language_code or "",
                "account_id": self.chatwoot_account_id or None,
                "inbox_id": self.chatwoot_inbox_id or None,
                "conversation_id": self.chatwoot_conversation_id or None,
                "reply_to_message_id": self.reply_to_chatwoot_message_id or None,
                "destination_type": self.destination_type,
                "destination_reference": self.destination_reference or "",
                "source_message_id": self.source_message_id.id or None,
            }
        )

    def _integration_update(self, values):
        """Private audited write path used only by guarded service callbacks."""
        return super(DevWorkCommunication, self).write(values)

    def action_review(self):
        self.ensure_one()
        if self.state != "draft":
            raise UserError("Only a Draft communication can be reviewed.")
        if self.communication_type == "completion":
            if self.work_item_id.current_phase != "completed":
                raise UserError(
                    "Completion communication review requires completed lifecycle work."
                )
            if (
                not self.completion_report_id
                or self.completion_report_id.status != "approved"
            ):
                raise UserError(
                    "A completion communication requires an approved completion report."
                )
            if not self.source_message_id:
                raise UserError(
                    "Select the original source message before reviewing completion."
                )
            source = self.source_message_id
            expected = (
                source.chatwoot_account_id,
                source.chatwoot_inbox_id,
                source.chatwoot_conversation_id,
            )
            actual = (
                self.chatwoot_account_id,
                self.chatwoot_inbox_id,
                self.chatwoot_conversation_id,
            )
            if not all(expected) or actual != expected:
                raise UserError(
                    "The Chatwoot account, inbox, and conversation must exactly "
                    "match the original source message."
                )
            if source.group_jid and (
                self.destination_type != "group_jid"
                or self.destination_reference != source.group_jid
            ):
                raise UserError(
                    "The WhatsApp group destination must match the original source."
                )
        review_hash = self._message_destination_hash()
        super(DevWorkCommunication, self).write(
            {
                "state": "in_review",
                "reviewed_by": self.env.user.id,
                "reviewed_at": fields.Datetime.now(),
                "review_hash": review_hash,
            }
        )
        return True

    def action_submit_review(self):
        return self.action_review()

    def action_approve(self):
        self.ensure_one()
        _require_approver(self.env)
        if self.state != "in_review":
            raise UserError("Only a reviewed communication can be approved.")
        current_hash = self._message_destination_hash()
        if not self.review_hash or self.review_hash != current_hash:
            raise UserError("Communication changed after review; start review again.")
        super(DevWorkCommunication, self).write(
            {
                "state": "approved",
                "approved_by": self.env.user.id,
                "approved_at": fields.Datetime.now(),
                "send_approved": True,
                "approved_hash": current_hash,
            }
        )
        return True

    def action_queue(self):
        self.ensure_one()
        self.env.cr.execute(
            "SELECT id FROM dev_work_communication WHERE id = %s FOR UPDATE", [self.id]
        )
        self.invalidate_recordset()
        if self.state == "queued" and self.idempotency_key:
            existing = self.env["dev.external.outbox"].sudo().search(
                [("idempotency_key", "=", self.idempotency_key)], limit=1
            )
            if existing:
                return existing
        if self.state != "approved":
            raise UserError("Only an approved communication can be queued.")
        if (
            not self.approved_hash
            or self.approved_hash != self._message_destination_hash()
        ):
            raise UserError("Approved communication hash no longer matches.")
        if not (
            self.chatwoot_account_id
            and self.chatwoot_inbox_id
            and self.chatwoot_conversation_id
            and self.destination_reference
        ):
            raise UserError(
                "Chatwoot account, inbox, conversation, and destination are required."
            )
        payload = {
            "schema": "dev-hub.chatwoot-public-message.v1",
            "account_id": self.chatwoot_account_id,
            "inbox_id": self.chatwoot_inbox_id,
            "conversation_id": self.chatwoot_conversation_id,
            "reply_to_message_id": self.reply_to_chatwoot_message_id or None,
            "destination_type": self.destination_type,
            "destination_reference": self.destination_reference,
            "body": self.body,
            "communication_id": self.id,
            "idempotency_key": self.approved_hash,
        }
        key = "chatwoot:%s:%s:%s" % (
            self.chatwoot_account_id,
            self.chatwoot_conversation_id,
            _canonical_hash(payload)[:24],
        )
        outbox = self.work_item_id._queue_outbox(
            "chatwoot", "public_message", payload, key, communication=self
        )
        super(DevWorkCommunication, self).write(
            {
                "state": "queued",
                "queued_at": fields.Datetime.now(),
                "idempotency_key": key,
                "delivery_status": "queued",
            }
        )
        return outbox

    def record_delivery_references(
        self, chatwoot_message_id=None, evolution_message_id=None, summary=None
    ):
        self.ensure_one()
        if not self.env.is_superuser() and not self.env.user.has_group(
            "devhub_core.group_dev_hub_integration"
        ):
            raise AccessError("Only the guarded integration callback may record delivery.")
        if self.state != "queued":
            raise UserError("Delivery references require a queued communication.")
        super(DevWorkCommunication, self).write(
            {
                "chatwoot_message_id": chatwoot_message_id or False,
                "evolution_message_id": _clean_text(
                    evolution_message_id, "Evolution message ID", 300
                ),
                "delivery_summary": _clean_text(summary, "Delivery summary", 500),
                "delivery_status": (
                    "handed_off"
                    if chatwoot_message_id or evolution_message_id
                    else "queued"
                ),
            }
        )
        return True



class DevExternalOutbox(models.Model):
    _name = "dev.external.outbox"
    _description = "Sanitized Development External Outbox"
    _order = "next_attempt_at, id"

    work_item_id = fields.Many2one(
        "dev.work.item", required=True, ondelete="restrict", index=True
    )
    channel = fields.Selection(
        [("openproject", "OpenProject"), ("chatwoot", "Chatwoot")],
        required=True,
        index=True,
    )
    destination = fields.Selection(related="channel", readonly=True, store=True)
    operation = fields.Selection(
        [("milestone", "Milestone"), ("public_message", "Public Message")],
        required=True,
        index=True,
    )
    payload_json = fields.Text(required=True, readonly=True)
    payload_hash = fields.Char(required=True, readonly=True, index=True)
    idempotency_key = fields.Char(required=True, readonly=True, copy=False, index=True)
    state = fields.Selection(
        [
            ("pending", "Pending"),
            ("retry", "Retry"),
            ("dead_letter", "Dead Letter"),
            ("done", "Done"),
        ],
        default="pending",
        required=True,
        readonly=True,
        index=True,
    )
    attempt_count = fields.Integer(default=0, readonly=True)
    next_attempt_at = fields.Datetime(
        default=fields.Datetime.now, required=True, readonly=True, index=True
    )
    last_attempt_at = fields.Datetime(readonly=True)
    completed_at = fields.Datetime(readonly=True)
    last_error_code = fields.Char(readonly=True)
    last_error_summary = fields.Char(readonly=True)
    last_error = fields.Char(related="last_error_summary", readonly=True)
    external_reference = fields.Char(readonly=True)
    created_by = fields.Many2one(
        "res.users",
        required=True,
        default=lambda self: self.env.user,
        ondelete="restrict",
        readonly=True,
    )

    _idempotency_unique = models.Constraint(
        "unique(idempotency_key)", "Outbox idempotency key must be unique."
    )

    @api.model
    def _validate_intent_payload(self, channel, operation, payload):
        if (channel, operation) == ("chatwoot", "public_message"):
            allowed = {
                "schema",
                "account_id",
                "inbox_id",
                "conversation_id",
                "reply_to_message_id",
                "destination_type",
                "destination_reference",
                "body",
                "communication_id",
                "idempotency_key",
            }
            if set(payload) != allowed:
                raise ValidationError("Chatwoot outbox payload fields do not match v1.")
            if payload.get("schema") != "dev-hub.chatwoot-public-message.v1":
                raise ValidationError("Unsupported Chatwoot outbox schema.")
            for name in ("account_id", "inbox_id", "conversation_id", "communication_id"):
                value = payload.get(name)
                if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                    raise ValidationError("%s must be a positive integer." % name)
            reply_id = payload.get("reply_to_message_id")
            if reply_id is not None and (
                isinstance(reply_id, bool)
                or not isinstance(reply_id, int)
                or reply_id <= 0
            ):
                raise ValidationError("reply_to_message_id must be a positive integer.")
            if payload.get("destination_type") not in ("group_jid", "conversation"):
                raise ValidationError("Unsupported Chatwoot destination type.")
            _clean_text(payload.get("destination_reference"), "Destination", 300)
            _clean_text(payload.get("body"), "Communication body", 4000)
            _clean_text(payload.get("idempotency_key"), "Payload idempotency key", 300)
            return
        if (channel, operation) == ("openproject", "milestone"):
            required = {
                "schema",
                "backend_id",
                "work_package_id",
                "milestone",
                "summary",
            }
            optional = {"status_hint", "dev_hub_link"}
            if not required.issubset(payload) or set(payload) - required - optional:
                raise ValidationError("OpenProject milestone payload fields do not match v1.")
            if payload.get("schema") != "dev-hub.op-milestone.v1":
                raise ValidationError("Unsupported OpenProject outbox schema.")
            for name in ("backend_id", "work_package_id"):
                value = payload.get(name)
                if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                    raise ValidationError("%s must be a positive integer." % name)
            if payload.get("milestone") not in (
                "analysis_plan_ready",
                "material_blocker",
                "completion",
            ):
                raise ValidationError("Unsupported OpenProject milestone.")
            if payload.get("status_hint") not in (
                None,
                "new",
                "in_progress",
                "on_hold",
                "in_review",
                "closed",
            ):
                raise ValidationError("Unsupported OpenProject status hint.")
            _clean_text(payload.get("summary"), "OpenProject milestone summary", 2000)
            if payload.get("dev_hub_link"):
                _clean_text(payload["dev_hub_link"], "Dev Hub link", 500)
            return
        raise ValidationError("Unsupported external outbox action.")

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("dev_internal_outbox"):
            raise AccessError("External intents may be created only by guarded actions.")
        for vals in vals_list:
            if vals.get("state", "pending") != "pending":
                raise ValidationError("Outbox records must be created Pending.")
            payload = json.loads(_validated_json(vals.get("payload_json")))
            self._validate_intent_payload(
                vals.get("channel"), vals.get("operation"), payload
            )
            payload_json = _validated_json(payload)
            vals["payload_json"] = payload_json
            vals["payload_hash"] = hashlib.sha256(
                payload_json.encode("utf-8")
            ).hexdigest()
            _clean_text(vals.get("idempotency_key"), "Idempotency key", 300)
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.context.get("dev_outbox_action"):
            raise AccessError("Outbox records change only through status callbacks.")
        if {"payload_json", "payload_hash", "idempotency_key", "channel", "operation"} & set(
            vals
        ):
            raise AccessError("Outbox intent and idempotency are immutable.")
        return super().write(vals)

    def unlink(self):
        raise AccessError("Outbox audit records cannot be deleted.")

    def mark_retry(self, error_code, error_summary, next_attempt_at):
        self.ensure_one()
        if self.state not in ("pending", "retry"):
            raise UserError("Only pending or retry outbox records can retry.")
        self.with_context(dev_outbox_action=True).write(
            {
                "state": "retry",
                "attempt_count": self.attempt_count + 1,
                "last_attempt_at": fields.Datetime.now(),
                "next_attempt_at": next_attempt_at,
                "last_error_code": _clean_text(error_code, "Error code", 100),
                "last_error_summary": _clean_text(
                    error_summary, "Error summary", 1000
                ),
            }
        )
        return True

    def mark_dead_letter(self, error_code, error_summary):
        self.ensure_one()
        if self.state not in ("pending", "retry"):
            raise UserError("Only active outbox records can become dead letters.")
        self.with_context(dev_outbox_action=True).write(
            {
                "state": "dead_letter",
                "attempt_count": self.attempt_count + 1,
                "last_attempt_at": fields.Datetime.now(),
                "last_error_code": _clean_text(error_code, "Error code", 100),
                "last_error_summary": _clean_text(
                    error_summary, "Error summary", 1000
                ),
            }
        )
        return True

    def mark_done(self, external_reference=None):
        self.ensure_one()
        if self.state not in ("pending", "retry"):
            raise UserError("Only pending or retry outbox records can complete.")
        self.with_context(dev_outbox_action=True).write(
            {
                "state": "done",
                "attempt_count": self.attempt_count + 1,
                "last_attempt_at": fields.Datetime.now(),
                "completed_at": fields.Datetime.now(),
                "external_reference": _clean_text(
                    external_reference, "External reference", 500
                ),
                "last_error_code": False,
                "last_error_summary": False,
            }
        )
        return True

