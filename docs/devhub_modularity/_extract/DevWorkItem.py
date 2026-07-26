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

class DevWorkItem(models.Model):
    _name = "dev.work.item"
    _description = "Development Work Item"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "write_date desc, id desc"

    uuid = fields.Char(required=True, default=_uuid, readonly=True, copy=False, index=True)
    name = fields.Char(required=True, tracking=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, index=True
    )
    dev_project_id = fields.Many2one(
        "dev.project", required=True, ondelete="restrict", index=True, tracking=True
    )
    odoo_project_id = fields.Many2one(
        "project.project", required=True, ondelete="restrict", index=True, tracking=True
    )
    odoo_task_id = fields.Many2one(
        "project.task", ondelete="restrict", index=True, copy=False, tracking=True
    )
    op_backend_id = fields.Many2one(
        "openproject.backend", ondelete="restrict", index=True, copy=False, tracking=True
    )
    op_work_package_id = fields.Integer(index=True, copy=False, tracking=True)
    op_url = fields.Char(copy=False)
    responsible_user_id = fields.Many2one(
        "res.users", required=True, default=lambda self: self.env.user, index=True
    )
    priority_cache = fields.Selection(
        [("0", "Normal"), ("1", "Low"), ("2", "High"), ("3", "Very High")],
        default="0",
    )
    deadline_cache = fields.Date()
    preferred_repository_id = fields.Many2one(
        "dev.repository", ondelete="restrict", index=True
    )
    preferred_environment_id = fields.Many2one(
        "dev.environment", ondelete="restrict", index=True
    )
    current_phase = fields.Selection(
        LIFECYCLE_SELECTION,
        required=True,
        default="received",
        readonly=True,
        index=True,
        tracking=True,
    )
    lifecycle_phase = fields.Selection(
        related="current_phase", store=True, readonly=True, index=True
    )
    blocked_from_phase = fields.Selection(LIFECYCLE_SELECTION, readonly=True, copy=False)
    blocker = fields.Text()
    cancellation_reason = fields.Text(readonly=True, copy=False)
    progress_percent = fields.Float(compute="_compute_progress", store=True)
    plan_progress = fields.Float(related="progress_percent", store=True, readonly=True)
    completed_step_count = fields.Integer(compute="_compute_progress", store=True)
    actionable_step_count = fields.Integer(compute="_compute_progress", store=True)
    context_revision = fields.Char(readonly=True, copy=False, index=True)

    source_message_ids = fields.Many2many(
        "dev.work.source.message",
        "dev_work_item_source_message_rel",
        "work_item_id",
        "source_message_id",
        string="Source Messages",
    )
    external_link_ids = fields.One2many(
        "dev.work.external.link", "work_item_id", string="External Links"
    )
    analysis_ids = fields.One2many("dev.work.analysis", "work_item_id")
    plan_ids = fields.One2many("dev.work.plan", "work_item_id")
    checkpoint_ids = fields.One2many("dev.work.checkpoint", "work_item_id")
    completion_report_ids = fields.One2many("dev.completion.report", "work_item_id")
    communication_ids = fields.One2many("dev.work.communication", "work_item_id")
    lifecycle_event_ids = fields.One2many(
        "dev.work.lifecycle.event", "work_item_id", string="Lifecycle Events"
    )
    outbox_ids = fields.One2many("dev.external.outbox", "work_item_id")
    current_analysis_id = fields.Many2one(
        "dev.work.analysis", compute="_compute_current_artifacts", store=False
    )
    current_accepted_analysis_id = fields.Many2one(
        "dev.work.analysis", compute="_compute_current_artifacts", store=False
    )
    approved_plan_id = fields.Many2one(
        "dev.work.plan", compute="_compute_current_artifacts", store=False
    )
    current_approved_plan_id = fields.Many2one(
        "dev.work.plan", related="approved_plan_id", readonly=True
    )
    current_checkpoint_id = fields.Many2one(
        "dev.work.checkpoint", compute="_compute_current_artifacts", store=False
    )
    completion_report_id = fields.Many2one(
        "dev.completion.report", compute="_compute_current_artifacts", store=False
    )
    op_reference = fields.Char(compute="_compute_op_reference")

    _uuid_unique = models.Constraint("unique(uuid)", "Work item UUID must be unique.")
    _op_identity_unique = models.UniqueIndex(
        "(op_backend_id, op_work_package_id) "
        "WHERE op_backend_id IS NOT NULL AND op_work_package_id IS NOT NULL",
        "An OpenProject work package can belong to only one work item.",
    )
    _odoo_task_unique = models.UniqueIndex(
        "(odoo_task_id) WHERE odoo_task_id IS NOT NULL",
        "An Odoo task can be primary for only one work item.",
    )

    @api.depends("op_work_package_id")
    def _compute_op_reference(self):
        for record in self:
            record.op_reference = (
                "#%s" % record.op_work_package_id
                if record.op_work_package_id
                else False
            )

    @api.depends("plan_ids.status", "plan_ids.step_ids.status")
    def _compute_progress(self):
        for record in self:
            plan = record.plan_ids.filtered(lambda p: p.status == "approved")[:1]
            if not plan:
                plan = record.plan_ids.sorted(lambda p: (p.revision, p.id), reverse=True)[:1]
            steps = plan.step_ids if plan else self.env["dev.work.plan.step"]
            actionable = steps.filtered(lambda s: s.status != "skipped")
            done = actionable.filtered(lambda s: s.status == "done")
            record.actionable_step_count = len(actionable)
            record.completed_step_count = len(done)
            record.progress_percent = (
                100.0 * len(done) / len(actionable) if actionable else 0.0
            )

    @api.depends(
        "analysis_ids.status",
        "analysis_ids.revision",
        "plan_ids.status",
        "plan_ids.revision",
        "checkpoint_ids.captured_at",
        "completion_report_ids.status",
        "completion_report_ids.revision",
    )
    def _compute_current_artifacts(self):
        Analysis = self.env["dev.work.analysis"]
        Plan = self.env["dev.work.plan"]
        Checkpoint = self.env["dev.work.checkpoint"]
        Report = self.env["dev.completion.report"]
        for record in self:
            accepted_analysis = record.analysis_ids.filtered(
                lambda r: r.status == "accepted"
            ).sorted(
                lambda r: (r.revision, r.id), reverse=True
            )[:1]
            record.current_accepted_analysis_id = accepted_analysis or Analysis
            record.current_analysis_id = (
                accepted_analysis
                or record.analysis_ids.sorted(
                    lambda r: (r.revision, r.id), reverse=True
                )[:1]
                or Analysis
            )
            record.approved_plan_id = (
                record.plan_ids.filtered(lambda r: r.status == "approved").sorted(
                    lambda r: (r.revision, r.id), reverse=True
                )[:1]
                or Plan
            )
            record.current_checkpoint_id = (
                record.checkpoint_ids.sorted(
                    lambda r: (r.captured_at, r.id), reverse=True
                )[:1]
                or Checkpoint
            )
            record.completion_report_id = (
                record.completion_report_ids.filtered(
                    lambda r: r.status == "approved"
                ).sorted(lambda r: (r.revision, r.id), reverse=True)[:1]
                or record.completion_report_ids.sorted(
                    lambda r: (r.revision, r.id), reverse=True
                )[:1]
                or Report
            )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("current_phase", "received") != "received":
                raise ValidationError("Work items must be created in Received state.")
            task = self.env["project.task"].browse(vals.get("odoo_task_id")).exists()
            if task:
                vals.setdefault("odoo_project_id", task.project_id.id)
                vals.setdefault("op_backend_id", task.op_backend_id.id)
                vals.setdefault("op_work_package_id", task.op_work_package_id)
                vals.setdefault("op_url", task.op_url)
                vals.setdefault("priority_cache", task.priority or "0")
                vals.setdefault("deadline_cache", task.date_deadline)
            _validate_text_values(self, vals)
            _clean_text(vals.get("name"), "Work item title", 300)
        records = super().create(vals_list)
        for record in records:
            if not record.source_message_ids:
                raise ValidationError(
                    "A Received work item requires at least one source message."
                )
            record._refresh_context_revision()
            record._append_lifecycle_event(False, "received", "Work item created")
        return records

    def write(self, vals):
        if {"uuid", "current_phase", "context_revision", "cancellation_reason"} & set(vals):
            raise AccessError("Protected work-item fields can change only through actions.")
        _validate_text_values(self, vals)
        _clean_text(vals.get("name"), "Work item title", 300)
        result = super().write(vals)
        if {
            "dev_project_id",
            "odoo_project_id",
            "odoo_task_id",
            "op_backend_id",
            "op_work_package_id",
            "preferred_repository_id",
            "preferred_environment_id",
        } & set(vals):
            self._refresh_context_revision()
        return result

    @api.constrains(
        "dev_project_id",
        "odoo_project_id",
        "odoo_task_id",
        "op_backend_id",
        "op_work_package_id",
        "preferred_repository_id",
        "preferred_environment_id",
    )
    def _check_identity_consistency(self):
        for record in self:
            task = record.odoo_task_id
            if task:
                if task.project_id != record.odoo_project_id:
                    raise ValidationError("The Odoo task must belong to the selected project.")
                if task.op_backend_id and record.op_backend_id != task.op_backend_id:
                    raise ValidationError("Work item and Odoo task OP backends must match.")
                if (
                    task.op_work_package_id
                    and record.op_work_package_id != task.op_work_package_id
                ):
                    raise ValidationError("Work item and Odoo task OP package IDs must match.")
                if record.op_backend_id and not task.op_backend_id:
                    raise ValidationError("The linked Odoo task has no matching OP backend.")
                if record.op_work_package_id and not task.op_work_package_id:
                    raise ValidationError("The linked Odoo task has no matching OP package ID.")
            if bool(record.op_backend_id) != bool(record.op_work_package_id):
                raise ValidationError("OP backend and work-package ID must be set together.")
            if (
                record.preferred_repository_id
                and record.preferred_repository_id.project_id != record.dev_project_id
            ):
                raise ValidationError("Preferred repository must belong to the Dev project.")
            if (
                record.preferred_environment_id
                and record.preferred_environment_id.project_id != record.dev_project_id
            ):
                raise ValidationError("Preferred environment must belong to the Dev project.")

    def _refresh_context_revision(self):
        for record in self:
            payload = {
                "uuid": record.uuid,
                "phase": record.current_phase,
                "task": record.odoo_task_id.id or None,
                "backend": record.op_backend_id.id or None,
                "wp": record.op_work_package_id or None,
                "analysis": record.current_analysis_id.content_hash or None,
                "plan": record.approved_plan_id.content_hash or None,
                "checkpoint": record.current_checkpoint_id.snapshot_hash or None,
            }
            super(DevWorkItem, record).write({"context_revision": _canonical_hash(payload)})

    def _append_lifecycle_event(
        self, old_phase, new_phase, reason, actor_type="human", artifact=None, policy=None
    ):
        self.ensure_one()
        reason = _clean_text(reason, "Lifecycle reason", 1000)
        self.env["dev.work.lifecycle.event"].with_context(
            dev_internal_event=True
        ).sudo().create(
            {
                "work_item_id": self.id,
                "old_phase": old_phase or False,
                "new_phase": new_phase,
                "actor_type": actor_type,
                "actor_id": self.env.context.get("dev_integration_actor_id")
                or self.env.user.id,
                "occurred_at": fields.Datetime.now(),
                "reason": reason,
                "artifact_model": artifact._name if artifact else False,
                "artifact_record_id": artifact.id if artifact else False,
                "artifact_revision": getattr(artifact, "revision", 0) if artifact else 0,
                "artifact_hash": (
                    getattr(artifact, "content_hash", False)
                    or getattr(artifact, "snapshot_hash", False)
                    if artifact
                    else False
                ),
                "policy_decision": _clean_text(policy, "Policy decision", 1000),
                "correlation_id": _uuid(),
            }
        )

    def _validate_transition_requirements(self, new_phase):
        self.ensure_one()
        if new_phase == "received" and not self.source_message_ids:
            raise UserError("Received work requires at least one source message.")
        if new_phase == "registered":
            if not (
                self.odoo_task_id
                and self.op_backend_id
                and self.op_work_package_id
                and self.odoo_task_id.op_backend_id == self.op_backend_id
                and self.odoo_task_id.op_work_package_id == self.op_work_package_id
            ):
                raise UserError("Registration requires a verified OP-backed Odoo task.")
        elif new_phase == "planning":
            if not self.analysis_ids:
                raise UserError("Planning requires an analysis revision.")
        elif new_phase == "awaiting_plan_approval":
            plan = self.plan_ids.filtered(lambda p: p.status == "awaiting_approval")[:1]
            if not plan or not plan._is_complete():
                raise UserError("Approval requires a complete plan revision.")
        elif new_phase == "approved":
            if not self.approved_plan_id:
                raise UserError("The exact plan revision must be approved first.")
        elif new_phase == "implementing":
            if not self.approved_plan_id:
                raise UserError("Implementation requires an approved exact plan hash.")
            if not self.preferred_repository_id or not self.preferred_environment_id:
                raise UserError("Implementation requires registered repository and environment.")
            self.preferred_environment_id._assert_dev_hub_safe(self.dev_project_id)
        elif new_phase == "paused":
            if (
                not self.current_checkpoint_id
                or self.current_checkpoint_id.lifecycle_phase != self.current_phase
            ):
                raise UserError("Pausing requires an immutable checkpoint.")
        elif new_phase == "testing":
            if not self.plan_ids.mapped("step_ids").filtered(
                lambda s: s.status in ("in_progress", "done")
            ):
                raise UserError("Testing requires recorded implementation progress.")
        elif new_phase == "ready_for_review":
            if not self.current_checkpoint_id:
                raise UserError("Review requires a current checkpoint.")
            report = self.completion_report_ids.filtered(
                lambda r: r.status in ("ready_review", "approved")
            )
            if not report:
                raise UserError("Review requires a completion report ready for review.")
        elif new_phase == "completed":
            if not self.completion_report_ids.filtered(lambda r: r.status == "approved"):
                raise UserError("Completion requires an approved completion report.")
        elif new_phase == "reported":
            if not self.communication_ids.filtered(lambda c: c.state == "queued"):
                raise UserError("Reported requires a reviewed message handed to the outbox.")

    def transition_lifecycle(
        self, new_phase, reason, actor_type="human", artifact=None, policy=None
    ):
        self.ensure_one()
        self.env.cr.execute("SELECT id FROM dev_work_item WHERE id = %s FOR UPDATE", [self.id])
        self.invalidate_recordset()
        if new_phase not in LIFECYCLE_TRANSITIONS.get(self.current_phase, set()):
            raise UserError(
                "Invalid work lifecycle transition: %s → %s"
                % (self.current_phase, new_phase)
            )
        reason = _clean_text(reason, "Lifecycle reason", 1000)
        if new_phase in ("blocked", "cancelled") and not reason:
            raise UserError("Blocked and cancelled transitions require a reason.")
        self._validate_transition_requirements(new_phase)
        old_phase = self.current_phase
        vals = {"current_phase": new_phase}
        if new_phase == "blocked":
            vals.update(blocked_from_phase=old_phase, blocker=reason)
        elif old_phase == "blocked":
            vals.update(blocked_from_phase=False, blocker=False)
        if new_phase == "cancelled":
            vals["cancellation_reason"] = reason
        super(DevWorkItem, self).write(vals)
        self._append_lifecycle_event(
            old_phase, new_phase, reason, actor_type, artifact, policy
        )
        self._refresh_context_revision()
        return True

    def action_triage(self):
        return self.transition_lifecycle("triage", "Intake moved to triage")

    def action_start_triage(self):
        return self.action_triage()

    def action_register(self):
        return self.transition_lifecycle("registered", "External identity verified")

    def action_analyze(self):
        return self.transition_lifecycle("analyzing", "Analysis started")

    def action_start_analysis(self):
        return self.action_analyze()

    def action_plan(self):
        return self.transition_lifecycle("planning", "Planning started")

    def action_start_planning(self):
        return self.action_plan()

    def action_request_plan_approval(self):
        return self.transition_lifecycle(
            "awaiting_plan_approval", "Plan submitted for exact-hash approval"
        )

    def action_start_implementation(self):
        return self.transition_lifecycle(
            "implementing", "Implementation explicitly started"
        )

    def action_start_testing(self):
        return self.transition_lifecycle("testing", "Testing started")

    def action_ready_for_review(self):
        self.ensure_one()
        if (
            not self.current_checkpoint_id
            or self.current_checkpoint_id.lifecycle_phase != self.current_phase
        ):
            session = self.env["dev.session"].search(
                [("work_item_id", "=", self.id)], order="write_date desc, id desc", limit=1
            )
            if not session:
                raise UserError("Ready for review requires a session checkpoint.")
            session._create_work_checkpoint("client_review")
        return self.transition_lifecycle("ready_for_review", "Ready for human review")

    def action_complete(self):
        return self.transition_lifecycle("completed", "Completion report approved")

    def action_reported(self):
        return self.transition_lifecycle("reported", "Outbound handoff recorded")

    def action_resume(self):
        self.ensure_one()
        target = (
            self.blocked_from_phase
            if self.current_phase == "blocked" and self.blocked_from_phase
            else "implementing"
        )
        return self.transition_lifecycle(target, "Work resumed from checkpoint")

    def action_pause(self):
        self.ensure_one()
        if (
            not self.current_checkpoint_id
            or self.current_checkpoint_id.lifecycle_phase != self.current_phase
        ):
            session = self.env["dev.session"].search(
                [
                    ("work_item_id", "=", self.id),
                    ("state", "in", ["started", "in_progress", "resumed", "paused"]),
                ],
                order="write_date desc, id desc",
                limit=1,
            )
            if not session:
                raise UserError("Pausing requires a linked session checkpoint.")
            session._create_work_checkpoint("pause")
        return self.transition_lifecycle("paused", "Work paused at latest checkpoint")

    def action_block(self, reason=None):
        reason = reason or self.blocker or self.env.context.get("dev_transition_reason")
        if not reason:
            raise UserError("Record a blocker reason before blocking work.")
        return self.transition_lifecycle("blocked", reason)

    def action_cancel(self, reason=None):
        reason = reason or self.env.context.get("dev_transition_reason")
        if not reason:
            raise UserError("Cancellation requires an explicit reason.")
        return self.transition_lifecycle("cancelled", reason)

    def action_report(self):
        return self.action_reported()

    def action_open_openproject(self):
        self.ensure_one()
        url = self.op_url or self.odoo_task_id.op_url
        if not url:
            raise UserError("No OpenProject URL is available.")
        return {"type": "ir.actions.act_url", "url": url, "target": "new"}

    def action_open_odoo_task(self):
        self.ensure_one()
        if not self.odoo_task_id:
            raise UserError("No Odoo task is linked.")
        return {
            "type": "ir.actions.act_window",
            "res_model": "project.task",
            "res_id": self.odoo_task_id.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_open_source_conversation(self):
        self.ensure_one()
        message = self.source_message_ids.filtered(lambda m: m.source_url)[:1]
        if not message:
            raise UserError("No source conversation URL is available.")
        return {"type": "ir.actions.act_url", "url": message.source_url, "target": "new"}

    def build_resume_brief(self, session=None):
        self.ensure_one()
        if session:
            session.ensure_one()
            if session.work_item_id != self:
                raise ValidationError("The session does not belong to this work item.")
        analysis = self.current_accepted_analysis_id
        plan = self.approved_plan_id
        checkpoint = self.current_checkpoint_id
        workspace = session.execution_workspace_id if session else self.execution_workspace_id
        source = self.source_message_ids.sorted(
            lambda r: (r.message_timestamp or fields.Datetime.now(), r.id)
        )[:3]
        steps = plan.step_ids.sorted(lambda r: (r.sequence, r.id)) if plan else []
        source_text = "\n".join(
            "- %s" % _bounded(message.text_snapshot, 900) for message in source
        ) or "- No sanitized source snapshot."
        step_text = "\n".join(
            "- [%s] %s: %s"
            % ("x" if step.status == "done" else " ", step.step_key, step.title)
            for step in steps[:40]
        ) or "- No approved plan steps."
        lines = [
            "# Development Resume Brief",
            "",
            "Context revision: `%s`" % (self.context_revision or "unavailable"),
            "Work item: %s (`%s`)" % (self.name, self.uuid),
            "Lifecycle: %s" % self.current_phase,
            "OpenProject: %s" % (self.op_url or self.op_work_package_id or "unlinked"),
            "Odoo task: %s" % (self.odoo_task_id.display_name or "unlinked"),
            "",
            "## Source request",
            source_text,
            "",
            "## Accepted analysis",
            _bounded(analysis.problem_summary, 1800) if analysis else "No analysis.",
            "",
            "## Approved plan",
            (
                "Revision %s, hash `%s`, progress %s / %s\n\n%s"
                % (
                    plan.revision,
                    plan.content_hash,
                    self.completed_step_count,
                    self.actionable_step_count,
                    _bounded(plan.goal, 1200),
                )
                if plan
                else "No approved plan."
            ),
            step_text,
            "",
            "## Execution workspace",
            (
                "Workspace: %s\nBranch: %s\nWorktree: %s\nBase HEAD: %s\n"
                "Current HEAD: %s\nPlan: Revision %s\nProgress: %s/%s"
                % (
                    workspace.name,
                    workspace.execution_branch,
                    workspace.worktree_path,
                    workspace.base_head,
                    workspace.current_head or "unavailable",
                    workspace.plan_revision,
                    self.completed_step_count,
                    self.actionable_step_count,
                )
                if workspace
                else "No isolated execution workspace."
            ),
            "",
            "## Latest checkpoint",
            (
                "Next: %s\nBlockers: %s\nDecisions: %s\nPending decisions: %s\n"
                "Remaining: %s\nGit baseline: %s @ %s (%s)"
                % (
                    _bounded(checkpoint.next_recommended_step, 700),
                    _bounded(checkpoint.blockers, 700) or "none",
                    _bounded(checkpoint.decisions_made, 700) or "none",
                    _bounded(checkpoint.pending_decisions, 700) or "none",
                    checkpoint.remaining_step_keys or "none",
                    checkpoint.branch or "unavailable",
                    checkpoint.git_head or "unavailable",
                    checkpoint.dirty_summary or "unavailable",
                )
                if checkpoint
                else "No checkpoint."
            ),
            "",
            "## Current session",
            (
                "Environment: %s\nMachine: %s\nClient: %s\nWorking directory: %s\n"
                "Current Git: %s @ %s\nDrift: %s"
                % (
                    session.environment_id.name,
                    session.machine_id.name,
                    session.client_id.name,
                    session.working_directory,
                    session.git_branch_snapshot or "unavailable",
                    session.git_head_snapshot or "unavailable",
                    session.drift_warning or "none",
                )
                if session
                else "No session selected."
            ),
            "",
            "## Guardrails",
            "- No production access or deployment.",
            "- No automatic branch switch, commit, push, service restart, or Docker action.",
            "- Follow only the approved plan hash and create a checkpoint before handoff.",
            "",
            "## Exact recommended next action",
            (
                _bounded(checkpoint.next_recommended_step, 1000)
                if checkpoint
                else "Create a checkpoint before continuing implementation."
            ),
        ]
        brief = _clean_text("\n".join(lines), "Resume brief", MAX_BRIEF)
        return brief, self.context_revision

    @api.model
    def import_analysis_draft(self, payload):
        """Strict authenticated RPC callback; it never executes code or starts work."""
        _require_importer(self.env)
        actor_id = self.env.user.id
        if not isinstance(payload, dict):
            raise ValidationError("Analysis import must be a JSON object.")
        allowed = {
            "work_item_uuid",
            "problem_summary",
            "original_request_summary",
            "reproduction_context",
            "current_behavior",
            "expected_behavior",
            "technical_findings",
            "affected_components",
            "risks",
            "dependencies",
            "open_questions",
            "evidence_references",
            "model_reference",
            "provider_reference",
            "run_reference",
            "observed_head",
        }
        unknown = set(payload) - allowed
        if unknown:
            raise ValidationError(
                "Unsupported analysis import fields: %s" % ", ".join(sorted(unknown))
            )
        required = ("problem_summary", "original_request_summary")
        missing = [name for name in required if not payload.get(name)]
        if missing:
            raise ValidationError(
                "Analysis import requires: %s." % ", ".join(missing)
            )
        work = self.sudo().with_context(
            dev_integration_actor_id=actor_id
        ).search([("uuid", "=", payload.get("work_item_uuid"))], limit=1)
        if not work:
            raise ValidationError("Unknown Work Item UUID.")
        if work.current_phase == "registered":
            work.transition_lifecycle(
                "analyzing", "Bounded analysis draft imported", actor_type="automation"
            )
        if work.current_phase != "analyzing":
            raise UserError("Analysis drafts may be imported only while Analyzing.")
        values = {key: value for key, value in payload.items() if key != "work_item_uuid"}
        values.update(
            work_item_id=work.id,
            status="generated",
            origin="generated",
            repository_id=work.preferred_repository_id.id,
            generated_at=fields.Datetime.now(),
            author_id=actor_id,
        )
        return self.env["dev.work.analysis"].sudo().create(values).id

    @api.model
    def import_merged_analysis_draft(self, payload):
        """Strict callback for the guarded 'merge_analysis' generation kind.

        Creates a new mixed-origin analysis revision that consolidates a base
        analysis with the human 'My Analysis' notes. It never overwrites the
        base revision; traceability links the new revision back to its base.
        """
        _require_importer(self.env)
        actor_id = self.env.user.id
        if not isinstance(payload, dict):
            raise ValidationError("Merged analysis import must be a JSON object.")
        allowed = {
            "work_item_uuid",
            "problem_summary",
            "original_request_summary",
            "reproduction_context",
            "current_behavior",
            "expected_behavior",
            "technical_findings",
            "affected_components",
            "risks",
            "dependencies",
            "open_questions",
            "evidence_references",
            "model_reference",
            "provider_reference",
            "run_reference",
            "observed_head",
            "base_analysis_id",
            "human_input_snapshot",
            "merged_by_id",
        }
        unknown = set(payload) - allowed
        if unknown:
            raise ValidationError(
                "Unsupported merged analysis fields: %s" % ", ".join(sorted(unknown))
            )
        required = ("problem_summary", "original_request_summary")
        missing = [name for name in required if not payload.get(name)]
        if missing:
            raise ValidationError(
                "Merged analysis import requires: %s." % ", ".join(missing)
            )
        work = self.sudo().with_context(
            dev_integration_actor_id=actor_id
        ).search([("uuid", "=", payload.get("work_item_uuid"))], limit=1)
        if not work:
            raise ValidationError("Unknown Work Item UUID.")
        if work.current_phase != "analyzing":
            raise UserError(
                "Merged analysis may be imported only while Analyzing."
            )
        base = self.env["dev.work.analysis"].sudo().browse(
            payload.get("base_analysis_id") or 0
        ).exists()
        if not base or base.work_item_id != work:
            raise ValidationError("The base analysis is unknown for this work item.")
        values = {
            key: value
            for key, value in payload.items()
            if key not in ("work_item_uuid", "base_analysis_id", "merged_by_id")
        }
        merged_by = self.env["res.users"].sudo().browse(
            payload.get("merged_by_id") or actor_id
        ).exists()
        values.update(
            work_item_id=work.id,
            status="generated",
            origin="mixed",
            parent_revision_id=base.id,
            base_analysis_id=base.id,
            merged_by_id=(merged_by.id if merged_by else actor_id),
            merged_at=fields.Datetime.now(),
            repository_id=(base.repository_id.id or work.preferred_repository_id.id),
            generated_at=fields.Datetime.now(),
            author_id=actor_id,
        )
        return self.env["dev.work.analysis"].sudo().create(values).id

    @api.model
    def import_plan_draft(self, payload):
        """Strict authenticated RPC callback; exact human approval remains mandatory."""
        _require_importer(self.env)
        actor_id = self.env.user.id
        if not isinstance(payload, dict):
            raise ValidationError("Plan import must be a JSON object.")
        allowed = {
            "work_item_uuid",
            "analysis_revision",
            "goal",
            "scope",
            "out_of_scope",
            "proposed_changes",
            "affected_components",
            "migration_impact",
            "security_impact",
            "test_plan",
            "rollback_plan",
            "dependencies",
            "risks",
            "acceptance_criteria",
            "run_reference",
            "steps",
        }
        unknown = set(payload) - allowed
        if unknown:
            raise ValidationError(
                "Unsupported plan import fields: %s" % ", ".join(sorted(unknown))
            )
        required = (
            "goal",
            "scope",
            "out_of_scope",
            "proposed_changes",
            "affected_components",
            "migration_impact",
            "security_impact",
            "test_plan",
            "rollback_plan",
            "dependencies",
            "risks",
            "acceptance_criteria",
        )
        missing = [name for name in required if not payload.get(name)]
        if missing:
            raise ValidationError("Plan import requires: %s." % ", ".join(missing))
        work = self.sudo().with_context(
            dev_integration_actor_id=actor_id
        ).search([("uuid", "=", payload.get("work_item_uuid"))], limit=1)
        if not work:
            raise ValidationError("Unknown Work Item UUID.")
        analysis = work.analysis_ids.filtered(lambda item: item.status == "accepted")
        if payload.get("analysis_revision"):
            analysis = analysis.filtered(
                lambda item: item.revision == payload["analysis_revision"]
            )
        analysis = analysis.sorted(lambda item: (item.revision, item.id), reverse=True)[:1]
        if not analysis:
            raise UserError("Plan import requires an accepted analysis revision.")
        if work.current_phase == "analyzing":
            work.transition_lifecycle(
                "planning", "Bounded plan draft imported", actor_type="automation"
            )
        if work.current_phase != "planning":
            raise UserError("Plan drafts may be imported only while Planning.")
        steps = payload.get("steps") or []
        if not isinstance(steps, list) or not 1 <= len(steps) <= 30:
            raise ValidationError("Plan steps must contain between 1 and 30 items.")
        values = {
            key: value
            for key, value in payload.items()
            if key not in ("work_item_uuid", "analysis_revision", "steps")
        }
        values.update(
            work_item_id=work.id,
            analysis_id=analysis.id,
            status="draft",
            origin="generated",
            generated_at=fields.Datetime.now(),
            author_id=actor_id,
        )
        plan = self.env["dev.work.plan"].sudo().with_context(
            dev_integration_actor_id=actor_id
        ).create(values)
        step_allowed = {
            "step_key",
            "sequence",
            "title",
            "description",
            "dependency_keys",
            "acceptance_evidence",
        }
        for item in steps:
            if not isinstance(item, dict) or set(item) - step_allowed:
                raise ValidationError("Plan step import contains unsupported fields.")
            self.env["dev.work.plan.step"].sudo().create({"plan_id": plan.id, **item})
        return plan.id

    def _queue_outbox(
        self, channel, operation, payload, idempotency_key, communication=None
    ):
        self.ensure_one()
        lock_key = int(
            hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()[:16], 16
        ) & 0x7FFFFFFFFFFFFFFF
        self.env.cr.execute("SELECT pg_advisory_xact_lock(%s)", [lock_key])
        existing = self.env["dev.external.outbox"].sudo().search(
            [("idempotency_key", "=", idempotency_key)], limit=1
        )
        if existing:
            return existing
        return self.env["dev.external.outbox"].with_context(
            dev_internal_outbox=True
        ).sudo().create(
            {
                "work_item_id": self.id,
                "channel": channel,
                "operation": operation,
                "payload_json": payload,
                "idempotency_key": idempotency_key,
                "communication_id": communication.id if communication else False,
            }
        )

    def _prepare_op_milestone(self, milestone, summary, status_hint=None, link=None):
        self.ensure_one()
        if not self.op_backend_id or not self.op_work_package_id:
            raise UserError("An OP identity is required to prepare a milestone.")
        if milestone not in ("analysis_plan_ready", "material_blocker", "completion"):
            raise ValidationError("Only sparse approved OpenProject milestones are allowed.")
        summary = _clean_text(summary, "OpenProject milestone summary", 2000)
        payload = {
            "schema": "dev-hub.op-milestone.v1",
            "backend_id": self.op_backend_id.id,
            "work_package_id": self.op_work_package_id,
            "milestone": milestone,
            "summary": summary,
        }
        if status_hint:
            if status_hint not in ("new", "in_progress", "on_hold", "in_review", "closed"):
                raise ValidationError("Unsupported broad OpenProject status hint.")
            payload["status_hint"] = status_hint
        if link:
            payload["dev_hub_link"] = _clean_text(link, "Dev Hub link", 500)
        key = "op:%s:%s:%s:%s" % (
            self.op_backend_id.id,
            self.op_work_package_id,
            milestone,
            _canonical_hash(payload)[:16],
        )
        return self._queue_outbox("openproject", "milestone", payload, key)

    def action_prepare_analysis_plan_milestone(self):
        self.ensure_one()
        analysis = self.current_accepted_analysis_id
        plan = self.plan_ids.filtered(
            lambda p: p.status in ("awaiting_approval", "approved")
        ).sorted(lambda p: (p.revision, p.id), reverse=True)[:1]
        if not analysis or not plan:
            raise UserError(
                "This milestone requires accepted analysis and a submitted plan."
            )
        return self._prepare_op_milestone(
            "analysis_plan_ready",
            "Development analysis and plan revision %s are ready." % plan.revision,
            "in_progress",
        )

    def action_prepare_blocker_milestone(self):
        self.ensure_one()
        if self.current_phase != "blocked" or not self.blocker:
            raise UserError("A material blocker must be recorded first.")
        return self._prepare_op_milestone(
            "material_blocker", _bounded(self.blocker, 1800), "on_hold"
        )

    def action_prepare_completion_milestone(self):
        self.ensure_one()
        report = self.completion_report_ids.filtered(lambda r: r.status == "approved")[:1]
        if self.current_phase != "completed" or not report:
            raise UserError(
                "Completed lifecycle work and an approved report are required."
            )
        return self._prepare_op_milestone(
            "completion", _bounded(report.implemented_summary, 1800), "closed"
        )

    def _invalidate_effective_plan(self, reason):
        for record in self:
            if record.current_phase in ("approved", "implementing", "paused", "testing"):
                raise UserError(
                    "An approved plan cannot be changed during execution; create and "
                    "approve a new revision before starting implementation."
                )
            if record.current_phase == "awaiting_plan_approval":
                super(DevWorkItem, record).write({"current_phase": "planning"})
                record._append_lifecycle_event(
                    "awaiting_plan_approval", "planning", reason, "automation"
                )
            record._refresh_context_revision()



