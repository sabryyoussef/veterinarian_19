# -*- coding: utf-8 -*-
from __future__ import annotations

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from odoo.addons.devhub_work.models.dev_work_utils import (
    MAX_TEXT,
    MAX_JSON,
    MAX_BRIEF,
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
    completion_report_ids = fields.One2many("dev.completion.report", "work_item_id")
    communication_ids = fields.One2many("dev.work.communication", "work_item_id")
    lifecycle_event_ids = fields.One2many(
        "dev.work.lifecycle.event", "work_item_id", string="Lifecycle Events"
    )
    outbox_ids = fields.One2many("dev.external.outbox", "work_item_id")
    completion_report_id = fields.Many2one(
        "dev.completion.report", compute="_compute_current_artifacts", store=False
    )

    _uuid_unique = models.Constraint("unique(uuid)", "Work item UUID must be unique.")
    _odoo_task_unique = models.UniqueIndex(
        "(odoo_task_id) WHERE odoo_task_id IS NOT NULL",
        "An Odoo task can be primary for only one work item.",
    )


    @api.depends("completion_report_ids")
    def _compute_progress(self):
        for record in self:
            # Extended by devhub_plan when installed.
            record.progress_percent = 0.0
            record.completed_step_count = 0
            record.actionable_step_count = 0

    @api.depends(
        "completion_report_ids.status",
        "completion_report_ids.revision",
    )
    def _compute_current_artifacts(self):
        for record in self:
            reports = record.completion_report_ids.sorted("revision", reverse=True)
            record.completion_report_id = reports[:1]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("current_phase", "received") != "received":
                raise ValidationError("Work items must be created in Received state.")
            task = self.env["project.task"].browse(vals.get("odoo_task_id")).exists()
            if task:
                vals.setdefault("odoo_project_id", task.project_id.id)
                if hasattr(self, "op_backend_id"):
                    vals.setdefault("op_backend_id", task.op_backend_id.id)
                if hasattr(self, "op_work_package_id"):
                    vals.setdefault("op_work_package_id", task.op_work_package_id)
                if hasattr(self, "op_url"):
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
            "preferred_repository_id",
            "preferred_environment_id",
        } & set(vals):
            self._refresh_context_revision()
        return result

    @api.constrains(
        "dev_project_id",
        "odoo_project_id",
        "odoo_task_id",
        "preferred_repository_id",
        "preferred_environment_id",
    )
    def _check_identity_consistency(self):
        for record in self:
            task = record.odoo_task_id
            if task and task.project_id != record.odoo_project_id:
                raise ValidationError("The Odoo task must belong to the selected project.")
            if hasattr(record, "_devhub_check_op_identity"):
                record._devhub_check_op_identity()
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
                "backend": getattr(record, "op_backend_id", False) and record.op_backend_id.id or None,
                "wp": getattr(record, "op_work_package_id", False) or None,
                "analysis": (
                    getattr(record, "current_analysis_id", False)
                    and record.current_analysis_id.content_hash
                    or None
                ),
                "plan": (
                    getattr(record, "approved_plan_id", False)
                    and record.approved_plan_id.content_hash
                    or None
                ),
                "checkpoint": (
                    getattr(record, "current_checkpoint_id", False)
                    and record.current_checkpoint_id.snapshot_hash
                    or None
                ),
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
            if not self.odoo_task_id:
                raise UserError("Registration requires a linked Odoo task.")
            # OpenProject verification is enforced by devhub_openproject when installed.
            if "openproject.backend" in self.env and hasattr(self, "op_backend_id"):
                self._devhub_validate_op_registration()
        elif new_phase == "planning":
            # Analysis optional: if Analysis module installed and analyses exist empty ok for manual plan.
            # Only require analysis when already in analyzing path with Analysis present and none created.
            if "dev.work.analysis" in self.env and self.env.context.get("devhub_require_analysis"):
                if not self.analysis_ids:
                    raise UserError("Planning requires an analysis revision.")
        elif new_phase == "awaiting_plan_approval":
            if "dev.work.plan" not in self.env:
                raise UserError("Plan capability is not installed.")
            plan = self.plan_ids.filtered(lambda p: p.status == "awaiting_approval")[:1]
            if not plan or not plan._is_complete():
                raise UserError("Approval requires a complete plan revision.")
        elif new_phase == "approved":
            if "dev.work.plan" not in self.env or not self.approved_plan_id:
                raise UserError("The exact plan revision must be approved first.")
        elif new_phase == "implementing":
            if "dev.work.plan" in self.env and not self.approved_plan_id:
                raise UserError("Implementation requires an approved exact plan hash.")
            if not self.preferred_repository_id or not self.preferred_environment_id:
                raise UserError("Implementation requires registered repository and environment.")
            self.preferred_environment_id._assert_dev_hub_safe(self.dev_project_id)
        elif new_phase == "paused":
            if "dev.work.checkpoint" not in self.env:
                raise UserError("Checkpoint/execution capability is not installed.")
            if (
                not self.current_checkpoint_id
                or self.current_checkpoint_id.lifecycle_phase != self.current_phase
            ):
                raise UserError("Pausing requires an immutable checkpoint.")
        elif new_phase == "testing":
            if "dev.work.plan" in self.env:
                if not self.plan_ids.mapped("step_ids").filtered(
                    lambda s: s.status in ("in_progress", "done")
                ):
                    raise UserError("Testing requires recorded implementation progress.")
        elif new_phase == "ready_for_review":
            if "dev.work.checkpoint" in self.env and not self.current_checkpoint_id:
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
        plan = self.approved_plan_id if "dev.work.plan" in self.env else False
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
            "OpenProject: %s" % (getattr(self, "op_url", False) or getattr(self, "op_work_package_id", False) or "unlinked"),
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

    @api.model

    @api.model

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
    whatsapp_message_id = fields.Many2one(
        "whatsapp.message",
        index=True,
        ondelete="set null",
        help="Canonical Hub message this source snapshot came from (nullable for legacy rows).",
    )
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
    # plan_id / repository_id related added by devhub_plan when installed
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
        plan = getattr(self, "plan_id", False)
        payload["plan_hash"] = plan.content_hash if plan else ""
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
            if not work:
                raise ValidationError("Completion report requires a work item.")
            if "dev.work.plan" in self.env:
                plan = self.env["dev.work.plan"].browse(vals.get("plan_id")).exists()
                if not plan or plan.work_item_id != work:
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

