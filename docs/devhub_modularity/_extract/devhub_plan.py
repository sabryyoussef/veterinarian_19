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

class DevWorkPlan(models.Model):
    _name = "dev.work.plan"
    _description = "Versioned Development Work Plan"
    _order = "work_item_id, revision desc"

    work_item_id = fields.Many2one(
        "dev.work.item", required=True, ondelete="cascade", index=True
    )
    revision = fields.Integer(required=True, readonly=True, copy=False)
    parent_revision_id = fields.Many2one(
        "dev.work.plan", ondelete="restrict", readonly=True, copy=False
    )
    analysis_id = fields.Many2one("dev.work.analysis", ondelete="restrict")
    content_hash = fields.Char(required=True, readonly=True, copy=False, index=True)
    status = fields.Selection(
        [
            ("draft", "Draft"),
            ("awaiting_approval", "Awaiting Approval"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
            ("superseded", "Superseded"),
        ],
        default="draft",
        required=True,
        index=True,
    )
    origin = fields.Selection(
        [("manual", "Manual"), ("generated", "Generated"), ("mixed", "Mixed")],
        required=True,
        default="manual",
    )
    generated_by = fields.Selection(
        related="origin", readonly=False
    )
    goal = fields.Text(required=True)
    scope = fields.Text(required=True)
    out_of_scope = fields.Text(required=True)
    proposed_changes = fields.Text(required=True)
    affected_components = fields.Text(required=True)
    affected_modules_files = fields.Text(
        related="affected_components", readonly=False
    )
    migration_impact = fields.Text(required=True)
    security_impact = fields.Text(required=True)
    test_plan = fields.Text(required=True)
    rollback_plan = fields.Text(required=True)
    dependencies = fields.Text(required=True)
    risks = fields.Text(required=True)
    acceptance_criteria = fields.Text(required=True)
    user_plan_notes = fields.Text(
        string="My Plan",
        help="Your own planning notes. Editable separately from the approved plan "
        "content and excluded from the plan content hash.",
    )
    schema_version = fields.Char(default="dev-work-plan.v1", required=True)
    author_id = fields.Many2one(
        "res.users", required=True, default=lambda self: self.env.user, ondelete="restrict"
    )
    generated_at = fields.Datetime()
    agent_reference = fields.Char()
    run_reference = fields.Char(related="agent_reference", readonly=False)
    step_ids = fields.One2many("dev.work.plan.step", "plan_id")
    approval_ids = fields.One2many("dev.work.approval", "plan_id", readonly=True)
    progress = fields.Float(compute="_compute_progress")

    _revision_unique = models.Constraint(
        "unique(work_item_id, revision)", "Plan revision must be unique per work item."
    )

    @api.depends("step_ids.status")
    def _compute_progress(self):
        for record in self:
            actionable = record.step_ids.filtered(lambda step: step.status != "skipped")
            done = actionable.filtered(lambda step: step.status == "done")
            record.progress = 100.0 * len(done) / len(actionable) if actionable else 0.0

    def _hash_values(self, values=None):
        self.ensure_one()
        values = values or {}
        names = (
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
            "schema_version",
        )
        steps = [
            {
                "key": step.step_key,
                "sequence": step.sequence,
                "title": step.title,
                "description": step.description or "",
                "acceptance": step.acceptance_evidence or "",
                "dependencies": step.dependency_keys or "",
                "parallel_group": step.parallel_group or "",
            }
            for step in self.step_ids.sorted(lambda r: (r.sequence, r.id))
        ]
        return _canonical_hash(
            {
                "fields": {name: values.get(name, self[name]) or "" for name in names},
                "steps": steps,
            }
        )

    def _is_complete(self):
        self.ensure_one()
        required = (
            self.goal,
            self.scope,
            self.out_of_scope,
            self.proposed_changes,
            self.affected_components,
            self.migration_impact,
            self.security_impact,
            self.test_plan,
            self.rollback_plan,
            self.dependencies,
            self.risks,
            self.acceptance_criteria,
        )
        return all((value or "").strip() for value in required) and bool(self.step_ids)

    def _refresh_hash(self):
        for record in self:
            super(DevWorkPlan, record).write({"content_hash": record._hash_values()})
            record.work_item_id._refresh_context_revision()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            _normalize_aliases(
                vals,
                {
                    "generated_by": "origin",
                    "affected_modules_files": "affected_components",
                    "run_reference": "agent_reference",
                },
            )
            work_item = self.env["dev.work.item"].browse(vals.get("work_item_id")).exists()
            if not work_item:
                raise ValidationError("Plan requires a work item.")
            latest = self.search(
                [("work_item_id", "=", work_item.id)], order="revision desc", limit=1
            )
            vals["revision"] = latest.revision + 1 if latest else 1
            vals["content_hash"] = "pending"
            if vals.get("status") == "approved":
                raise ValidationError("Use exact-hash plan approval.")
            for name, value in vals.items():
                field = self._fields.get(name)
                if field and field.type in ("char", "text"):
                    _clean_text(value, field.string or name)
        records = super().create(vals_list)
        records._refresh_hash()
        return records

    def write(self, vals):
        vals = dict(vals)
        _normalize_aliases(
            vals,
            {
                "generated_by": "origin",
                "affected_modules_files": "affected_components",
                "run_reference": "agent_reference",
            },
        )
        user_note_keys = {"user_plan_notes"}
        only_user_notes = bool(vals) and set(vals.keys()) <= user_note_keys
        content_names = {
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
            "schema_version",
        }
        if only_user_notes:
            if any(record.status == "superseded" for record in self):
                raise AccessError("Superseded plans cannot receive new notes.")
            for name, value in vals.items():
                field = self._fields.get(name)
                if field and field.type in ("char", "text"):
                    _clean_text(value, field.string or name)
            return super().write(vals)
        if content_names & set(vals) and any(record.status != "draft" for record in self):
            raise AccessError(
                "Submitted plans are immutable; use the explicit New Revision action."
            )
        if any(record.status in ("approved", "superseded") for record in self):
            raise AccessError("Approved and superseded plans are immutable.")
        if {"revision", "parent_revision_id", "content_hash", "work_item_id"} & set(vals):
            raise AccessError("Plan revision identity is immutable.")
        if vals.get("status") == "approved":
            raise AccessError("Use exact-hash plan approval.")
        for name, value in vals.items():
            field = self._fields.get(name)
            if field and field.type in ("char", "text"):
                _clean_text(value, field.string or name)
        material_change = bool(content_names & set(vals))
        result = super().write(vals)
        if material_change:
            self._refresh_hash()
            self.mapped("work_item_id")._invalidate_effective_plan(
                "Material plan content changed"
            )
        return result

    def unlink(self):
        if any(record.status in ("approved", "superseded") for record in self):
            raise AccessError("Approved and superseded plans cannot be deleted.")
        return super().unlink()

    def action_submit_for_approval(self):
        self.ensure_one()
        if self.work_item_id.current_phase != "planning":
            raise UserError("Plan submission requires the Work Item Planning phase.")
        if self.status != "draft" or not self._is_complete():
            raise UserError("Only a complete Draft plan can be submitted.")
        self._refresh_hash()
        super(DevWorkPlan, self).write({"status": "awaiting_approval"})
        if self.work_item_id.current_phase == "planning":
            self.work_item_id.transition_lifecycle(
                "awaiting_plan_approval", "Plan revision submitted", artifact=self
            )
        return True

    def action_approve_exact(self, expected_hash=None, comment=None, policy_version="manual"):
        self.ensure_one()
        _require_approver(self.env)
        if self.work_item_id.current_phase != "awaiting_plan_approval":
            raise UserError("Plan approval requires the Work Item approval gate.")
        expected_hash = expected_hash or self.content_hash
        self._refresh_hash()
        if self.status != "awaiting_approval" or expected_hash != self.content_hash:
            raise UserError("Plan approval hash is stale or does not match exactly.")
        approval = self.env["dev.work.approval"].with_context(
            dev_internal_approval=True
        ).sudo().create(
            {
                "work_item_id": self.work_item_id.id,
                "plan_id": self.id,
                "plan_revision": self.revision,
                "plan_hash": expected_hash,
                "decision": "approved",
                "approver_id": self.env.user.id,
                "decided_at": fields.Datetime.now(),
                "comment": _clean_text(comment, "Approval comment", 2000),
                "policy_version": _clean_text(policy_version, "Policy version", 200),
            }
        )
        old = self.work_item_id.plan_ids.filtered(
            lambda p: p.status == "approved" and p != self
        )
        if old:
            super(DevWorkPlan, old).write({"status": "superseded"})
        super(DevWorkPlan, self).write({"status": "approved"})
        if self.work_item_id.current_phase == "awaiting_plan_approval":
            self.work_item_id.transition_lifecycle(
                "approved", "Exact plan hash approved", artifact=self
            )
        self.work_item_id._refresh_context_revision()
        return approval

    def action_reject(self, comment=None, policy_version="manual"):
        self.ensure_one()
        _require_approver(self.env)
        if self.status != "awaiting_approval":
            raise UserError("Only a submitted plan can be rejected.")
        approval = self.env["dev.work.approval"].with_context(
            dev_internal_approval=True
        ).sudo().create(
            {
                "work_item_id": self.work_item_id.id,
                "plan_id": self.id,
                "plan_revision": self.revision,
                "plan_hash": self.content_hash,
                "decision": "rejected",
                "approver_id": self.env.user.id,
                "decided_at": fields.Datetime.now(),
                "comment": _clean_text(comment, "Approval comment", 2000),
                "policy_version": _clean_text(policy_version, "Policy version", 200),
            }
        )
        super(DevWorkPlan, self).write({"status": "rejected"})
        if self.work_item_id.current_phase == "awaiting_plan_approval":
            self.work_item_id.transition_lifecycle(
                "planning", "Plan rejected; revision required", artifact=self
            )
        return approval

    def action_new_revision(self):
        self.ensure_one()
        work = self.work_item_id
        if work.current_phase in (
            "implementing",
            "paused",
            "blocked",
            "testing",
            "ready_for_review",
            "completed",
            "reported",
            "cancelled",
        ):
            raise UserError(
                "An active or closed execution cannot silently replace its approved plan."
            )
        if self.status == "approved":
            super(DevWorkPlan, self).write({"status": "superseded"})
            if work.current_phase == "approved":
                super(DevWorkItem, work).write({"current_phase": "planning"})
                work._append_lifecycle_event(
                    "approved",
                    "planning",
                    "Approved plan superseded by a new revision",
                    artifact=self,
                )
        elif self.status in ("draft", "rejected"):
            super(DevWorkPlan, self).write({"status": "superseded"})
        elif self.status == "awaiting_approval":
            raise UserError("Reject the submitted plan before creating a new revision.")
        values = self.copy_data()[0]
        values.update(
            parent_revision_id=self.id,
            status="draft",
            content_hash=False,
            revision=0,
            step_ids=[],
            approval_ids=[],
        )
        new_plan = self.create(values)
        for step in self.step_ids.sorted(lambda r: (r.sequence, r.id)):
            step_values = step.copy_data()[0]
            step_values.update(
                plan_id=new_plan.id,
                status="pending",
                started_at=False,
                completed_at=False,
                blocker=False,
                result_summary=False,
            )
            self.env["dev.work.plan.step"].create(step_values)
        new_plan._refresh_hash()
        work._refresh_context_revision()
        return new_plan



class DevWorkPlanStep(models.Model):
    _name = "dev.work.plan.step"
    _description = "Development Work Plan Step"
    _order = "plan_id, sequence, id"

    plan_id = fields.Many2one(
        "dev.work.plan", required=True, ondelete="cascade", index=True
    )
    work_item_id = fields.Many2one(
        "dev.work.item", related="plan_id.work_item_id", store=True, index=True
    )
    step_key = fields.Char(required=True)
    sequence = fields.Integer(default=10, required=True)
    title = fields.Char(required=True)
    description = fields.Text()
    acceptance_evidence = fields.Text()
    dependency_keys = fields.Char()
    dependencies = fields.Char(related="dependency_keys", readonly=False)
    parallel_group = fields.Char()
    status = fields.Selection(
        [
            ("pending", "Pending"),
            ("in_progress", "In Progress"),
            ("done", "Done"),
            ("blocked", "Blocked"),
            ("skipped", "Skipped"),
        ],
        default="pending",
        required=True,
        index=True,
    )
    assignee_type = fields.Selection(
        [("human", "Human"), ("agent", "Agent")], default="human", required=True
    )
    assignee_id = fields.Many2one("res.users", ondelete="restrict")
    run_reference = fields.Char()
    started_at = fields.Datetime(readonly=True)
    completed_at = fields.Datetime(readonly=True)
    blocker = fields.Text()
    result_summary = fields.Text()
    evidence_references = fields.Text()

    _step_key_unique = models.Constraint(
        "unique(plan_id, step_key)", "Step key must be unique within a plan revision."
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            _normalize_aliases(vals, {"dependencies": "dependency_keys"})
            plan = self.env["dev.work.plan"].browse(vals.get("plan_id")).exists()
            if plan and plan.status in ("approved", "superseded"):
                raise AccessError("Steps cannot be added to an immutable plan.")
            for name, value in vals.items():
                field = self._fields.get(name)
                if field and field.type in ("char", "text"):
                    _clean_text(value, field.string or name)
        records = super().create(vals_list)
        records.mapped("plan_id")._refresh_hash()
        return records

    def write(self, vals):
        vals = dict(vals)
        _normalize_aliases(vals, {"dependencies": "dependency_keys"})
        structural = {
            "step_key",
            "sequence",
            "title",
            "description",
            "acceptance_evidence",
            "dependency_keys",
            "parallel_group",
        }
        if structural & set(vals) and any(
            record.plan_id.status != "draft" for record in self
        ):
            raise AccessError(
                "Submitted plan structure is immutable; create a new revision."
            )
        if "status" in vals:
            allowed = {
                "pending": {"in_progress", "skipped"},
                "in_progress": {"done", "blocked", "pending"},
                "blocked": {"in_progress", "pending", "skipped"},
                "done": set(),
                "skipped": set(),
            }
            for record in self:
                if vals["status"] not in allowed.get(record.status, set()):
                    raise UserError(
                        "Invalid plan-step transition: %s → %s"
                        % (record.status, vals["status"])
                    )
                if vals["status"] in ("blocked", "skipped") and not (
                    vals.get("blocker") or record.blocker
                ):
                    raise UserError("Blocked or skipped steps require a reason.")
                if vals["status"] == "in_progress" and not record.parallel_group:
                    other = record.plan_id.step_ids.filtered(
                        lambda s: s != record and s.status == "in_progress"
                    )
                    if other:
                        raise UserError("Only one non-parallel plan step may be current.")
            if vals["status"] == "in_progress":
                vals.setdefault("started_at", fields.Datetime.now())
            elif vals["status"] in ("done", "skipped"):
                vals.setdefault("completed_at", fields.Datetime.now())
        for name, value in vals.items():
            field = self._fields.get(name)
            if field and field.type in ("char", "text"):
                _clean_text(value, field.string or name)
        result = super().write(vals)
        if structural & set(vals):
            self.mapped("plan_id")._refresh_hash()
            self.mapped("work_item_id")._invalidate_effective_plan(
                "Material plan step changed"
            )
        return result

    def unlink(self):
        if any(record.plan_id.status in ("approved", "superseded") for record in self):
            raise AccessError("Steps cannot be deleted from an immutable plan.")
        plans = self.mapped("plan_id")
        result = super().unlink()
        plans._refresh_hash()
        return result



