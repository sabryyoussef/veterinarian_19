# -*- coding: utf-8 -*-
from __future__ import annotations

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

from odoo.addons.devhub_work.models.dev_work_utils import _clean_text, _uuid


class DevWorkItemOpenProject(models.Model):
    _inherit = "dev.work.item"

    op_backend_id = fields.Many2one(
        "openproject.backend", ondelete="restrict", index=True, copy=False, tracking=True
    )
    op_work_package_id = fields.Integer(index=True, copy=False, tracking=True)
    op_url = fields.Char(copy=False)
    op_reference = fields.Char(compute="_compute_op_reference")

    _op_identity_unique = models.UniqueIndex(
        "(op_backend_id, op_work_package_id) "
        "WHERE op_backend_id IS NOT NULL AND op_work_package_id IS NOT NULL",
        "An OpenProject work package can belong to only one work item.",
    )

    @api.depends("op_work_package_id")
    def _compute_op_reference(self):
        for record in self:
            record.op_reference = (
                "#%s" % record.op_work_package_id if record.op_work_package_id else False
            )

    def _devhub_validate_op_registration(self):
        self.ensure_one()
        if not (
            self.odoo_task_id
            and self.op_backend_id
            and self.op_work_package_id
            and self.odoo_task_id.op_backend_id == self.op_backend_id
            and self.odoo_task_id.op_work_package_id == self.op_work_package_id
        ):
            raise UserError("Registration requires a verified OP-backed Odoo task.")

    def _devhub_check_op_identity(self):
        self.ensure_one()
        task = self.odoo_task_id
        if task:
            if task.op_backend_id and self.op_backend_id != task.op_backend_id:
                raise ValidationError("Work item and Odoo task OP backends must match.")
            if task.op_work_package_id and self.op_work_package_id != task.op_work_package_id:
                raise ValidationError("Work item and Odoo task OP package IDs must match.")
            if self.op_backend_id and not task.op_backend_id:
                raise ValidationError("The linked Odoo task has no matching OP backend.")
            if self.op_work_package_id and not task.op_work_package_id:
                raise ValidationError("The linked Odoo task has no matching OP package ID.")
        if bool(self.op_backend_id) != bool(self.op_work_package_id):
            raise ValidationError("OP backend and work-package ID must be set together.")

    def action_open_openproject(self):
        self.ensure_one()
        url = self.op_url or self.odoo_task_id.op_url
        if not url:
            raise UserError("No OpenProject URL is available.")
        return {"type": "ir.actions.act_url", "url": url, "target": "new"}
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
