# -*- coding: utf-8 -*-
from __future__ import annotations

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from odoo.addons.devhub_work.models.dev_work_utils import (
    _clean_text,
    _require_approver,
)
from odoo.addons.devhub_plan.models.dev_work_plan import DevWorkPlan


class DevWorkPlanApproval(models.Model):
    _inherit = "dev.work.plan"

    approval_ids = fields.One2many("dev.work.approval", "plan_id", readonly=True)

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

