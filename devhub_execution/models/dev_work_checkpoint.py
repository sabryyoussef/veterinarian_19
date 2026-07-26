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

class DevWorkCheckpoint(models.Model):
    _name = "dev.work.checkpoint"
    _description = "Immutable Development Work Checkpoint"
    _order = "captured_at desc, id desc"

    work_item_id = fields.Many2one(
        "dev.work.item", required=True, ondelete="restrict", readonly=True, index=True
    )
    supersedes_id = fields.Many2one(
        "dev.work.checkpoint", ondelete="restrict", readonly=True
    )
    trigger = fields.Selection(
        [
            ("pause", "Pause"),
            ("milestone", "Milestone"),
            ("client_review", "Client Review"),
            ("machine_switch", "Machine Switch"),
            ("agent_handoff", "Agent Handoff"),
            ("manual", "Manual"),
        ],
        required=True,
        readonly=True,
    )
    captured_at = fields.Datetime(
        required=True, default=fields.Datetime.now, readonly=True, index=True
    )
    timestamp = fields.Datetime(related="captured_at", readonly=True)
    actor_id = fields.Many2one(
        "res.users",
        required=True,
        default=lambda self: self.env.user,
        ondelete="restrict",
        readonly=True,
    )
    lifecycle_phase = fields.Selection(
        LIFECYCLE_SELECTION, required=True, readonly=True
    )
    approved_plan_id = fields.Many2one(
        "dev.work.plan", ondelete="restrict", readonly=True
    )
    last_completed_step_id = fields.Many2one(
        "dev.work.plan.step", ondelete="restrict", readonly=True
    )
    current_step_id = fields.Many2one(
        "dev.work.plan.step", ondelete="restrict", readonly=True
    )
    current_plan_step_id = fields.Many2one(
        "dev.work.plan.step", related="current_step_id", readonly=True
    )
    next_recommended_step = fields.Text(required=True, readonly=True)
    remaining_step_keys = fields.Char(readonly=True)
    remaining_step_references = fields.Char(
        related="remaining_step_keys", readonly=True
    )
    blockers = fields.Text(readonly=True)
    decisions_made = fields.Text(readonly=True)
    pending_decisions = fields.Text(readonly=True)
    last_agent_note = fields.Text(readonly=True)
    repository_id = fields.Many2one("dev.repository", ondelete="restrict", readonly=True)
    working_directory = fields.Char(readonly=True)
    branch = fields.Char(readonly=True)
    git_head = fields.Char(readonly=True)
    full_head = fields.Char(related="git_head", readonly=True)
    base_head = fields.Char(readonly=True)
    dirty_summary = fields.Char(readonly=True)
    dirty_digest = fields.Char(readonly=True)
    ahead_count = fields.Integer(readonly=True)
    behind_count = fields.Integer(readonly=True)
    files_touched_summary = fields.Text(readonly=True)
    tests_run = fields.Integer(readonly=True)
    tests_passed = fields.Integer(readonly=True)
    tests_failed = fields.Integer(readonly=True)
    tests_skipped = fields.Integer(readonly=True)
    test_commands_summary = fields.Text(readonly=True)
    sanitized_test_commands = fields.Text(
        related="test_commands_summary", readonly=True
    )
    test_duration_seconds = fields.Float(readonly=True)
    duration_seconds = fields.Float(
        related="test_duration_seconds", readonly=True
    )
    test_evidence_references = fields.Text(readonly=True)
    evidence_references = fields.Text(
        related="test_evidence_references", readonly=True
    )
    environment_id = fields.Many2one(
        "dev.environment", ondelete="restrict", readonly=True
    )
    machine_id = fields.Many2one("dev.machine", ondelete="restrict", readonly=True)
    client_id = fields.Many2one("dev.client", ondelete="restrict", readonly=True)
    manifest_revision = fields.Char(readonly=True)
    op_work_package_id = fields.Integer(readonly=True)
    op_work_package_reference = fields.Char(
        compute="_compute_reference_labels"
    )
    odoo_task_id = fields.Many2one("project.task", ondelete="restrict", readonly=True)
    odoo_task_reference = fields.Char(compute="_compute_reference_labels")
    cursor_thread_reference = fields.Char(readonly=True)
    cursor_thread_id = fields.Char(related="cursor_thread_reference", readonly=True)
    cursor_run_reference = fields.Char(readonly=True)
    run_reference = fields.Char(related="cursor_run_reference", readonly=True)
    snapshot_hash = fields.Char(required=True, readonly=True, copy=False, index=True)
    schema_version = fields.Char(
        default="dev-work-checkpoint.v1", required=True, readonly=True
    )

    @api.depends("op_work_package_id", "odoo_task_id")
    def _compute_reference_labels(self):
        for record in self:
            record.op_work_package_reference = (
                "#%s" % record.op_work_package_id
                if record.op_work_package_id
                else False
            )
            record.odoo_task_reference = (
                record.odoo_task_id.display_name if record.odoo_task_id else False
            )

    def _snapshot_values(self, values=None):
        self.ensure_one()
        values = values or {}
        names = (
            "trigger",
            "lifecycle_phase",
            "next_recommended_step",
            "remaining_step_keys",
            "blockers",
            "decisions_made",
            "pending_decisions",
            "last_agent_note",
            "working_directory",
            "branch",
            "git_head",
            "base_head",
            "dirty_summary",
            "dirty_digest",
            "ahead_count",
            "behind_count",
            "files_touched_summary",
            "tests_run",
            "tests_passed",
            "tests_failed",
            "tests_skipped",
            "test_commands_summary",
            "test_duration_seconds",
            "test_evidence_references",
            "manifest_revision",
            "op_work_package_id",
            "cursor_thread_reference",
            "cursor_run_reference",
            "schema_version",
        )
        payload = {name: values.get(name, self[name]) or "" for name in names}
        payload.update(
            work_item_id=self.work_item_id.id,
            session_id=self.session_id.id or None,
            approved_plan_id=self.approved_plan_id.id or None,
            execution_workspace_id=self.execution_workspace_id.id or None,
            current_step_id=self.current_step_id.id or None,
        )
        return payload

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            work = self.env["dev.work.item"].browse(vals.get("work_item_id")).exists()
            if not work:
                raise ValidationError("Checkpoint requires a work item.")
            vals.setdefault("lifecycle_phase", work.current_phase)
            vals.setdefault("approved_plan_id", work.approved_plan_id.id)
            vals.setdefault("op_work_package_id", work.op_work_package_id)
            vals.setdefault("odoo_task_id", work.odoo_task_id.id)
            session = self.env["dev.session"].browse(vals.get("session_id")).exists()
            if session:
                if session.work_item_id != work:
                    raise ValidationError("Checkpoint session must belong to the work item.")
                vals.setdefault("repository_id", session.repository_id.id)
                vals.setdefault(
                    "execution_workspace_id", session.execution_workspace_id.id
                )
                vals.setdefault("working_directory", session.working_directory)
                vals.setdefault("branch", session.git_branch_snapshot)
                vals.setdefault("git_head", session.git_head_snapshot)
                vals.setdefault("dirty_summary", session.dirty_state_summary)
                vals.setdefault("environment_id", session.environment_id.id)
                vals.setdefault("machine_id", session.machine_id.id)
                vals.setdefault("client_id", session.client_id.id)
                vals.setdefault("manifest_revision", session.manifest_revision)
                vals.setdefault(
                    "cursor_thread_reference", session.cursor_agent_thread_id
                )
            for name, value in vals.items():
                field = self._fields.get(name)
                if field and field.type in ("char", "text"):
                    _clean_text(value, field.string or name, 4000)
            vals.setdefault("snapshot_hash", "pending")
        records = super().create(vals_list)
        for record in records:
            super(DevWorkCheckpoint, record).write(
                {"snapshot_hash": _canonical_hash(record._snapshot_values())}
            )
            record.work_item_id._refresh_context_revision()
        return records

    def write(self, vals):
        raise AccessError("Checkpoints are immutable; create a superseding checkpoint.")

    def unlink(self):
        raise AccessError("Checkpoints are immutable.")

    def action_new_revision(self):
        self.ensure_one()
        values = self.copy_data()[0]
        values.update(
            supersedes_id=self.id,
            captured_at=fields.Datetime.now(),
            actor_id=self.env.user.id,
            snapshot_hash="pending",
        )
        return self.create(values)



