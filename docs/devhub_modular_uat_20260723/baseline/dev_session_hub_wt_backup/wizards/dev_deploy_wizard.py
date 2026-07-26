# -*- coding: utf-8 -*-
from odoo import fields, models
from odoo.exceptions import UserError


class DevDeployApprovalWizard(models.TransientModel):
    _name = "dev.deploy.approval.wizard"
    _description = "Human Staging Deploy Approval"

    workspace_id = fields.Many2one("dev.execution.workspace", required=True, readonly=True)
    target_id = fields.Many2one(
        "dev.deploy.target",
        required=True,
        domain="[('repository_id', '=', workspace_id.repository_id), "
        "('target_kind', '=', 'staging'), ('approved', '=', True), ('active', '=', True)]",
    )
    merge_sha = fields.Char(related="workspace_id.merge_result_sha", readonly=True)
    confirm_target = fields.Boolean(
        string="I confirm this exact target, database, and module allowlist"
    )
    confirm_no_auto_merge = fields.Boolean(
        string="I understand this deploy does not merge, push, or perform any Git write"
    )
    confirm_distinct_approver = fields.Boolean(
        string="I am distinct from the requester bound to this workspace"
    )

    def action_approve(self):
        self.ensure_one()
        if not (
            self.confirm_target
            and self.confirm_no_auto_merge
            and self.confirm_distinct_approver
        ):
            raise UserError("All explicit staging deploy confirmations are required.")
        approval = self.workspace_id.create_deploy_approval(self.target_id)
        return approval.workspace_id._form_action()


class DevDeployExecutionWizard(models.TransientModel):
    _name = "dev.deploy.execution.wizard"
    _description = "Final Staging Deploy Execution Confirmation"

    workspace_id = fields.Many2one("dev.execution.workspace", required=True, readonly=True)
    approval_id = fields.Many2one("dev.deploy.approval", required=True, readonly=True)
    confirm_execute = fields.Boolean(string="Execute this exact approved staging deploy")

    def action_execute(self):
        self.ensure_one()
        if not self.confirm_execute:
            raise UserError("The execution confirmation is required.")
        record = self.workspace_id.execute_approved_deploy(self.approval_id)
        return record.workspace_id._form_action()


class DevProductionPromotionApprovalWizard(models.TransientModel):
    _name = "dev.deploy.production.approval.wizard"
    _description = "Human Production Promotion Approval"

    workspace_id = fields.Many2one("dev.execution.workspace", required=True, readonly=True)
    target_id = fields.Many2one(
        "dev.deploy.target",
        required=True,
        domain="[('repository_id', '=', workspace_id.repository_id), "
        "('target_kind', '=', 'production'), ('approved', '=', True), ('active', '=', True)]",
    )
    merge_sha = fields.Char(related="workspace_id.merge_result_sha", readonly=True)
    confirm_soak_satisfied = fields.Boolean(
        string="I confirm the required staging soak period has elapsed with evidence"
    )
    confirm_maintenance_window = fields.Boolean(
        string="I confirm this promotion is scheduled within an approved maintenance window"
    )
    confirm_distinct_approver = fields.Boolean(
        string="I am distinct from the requester bound to this workspace"
    )

    def action_approve(self):
        self.ensure_one()
        if not (
            self.confirm_soak_satisfied
            and self.confirm_maintenance_window
            and self.confirm_distinct_approver
        ):
            raise UserError(
                "Soak, maintenance-window, and distinct-approver confirmations are all required."
            )
        approval = self.workspace_id.create_deploy_approval(self.target_id)
        return approval.workspace_id._form_action()


class DevRollbackApprovalWizard(models.TransientModel):
    _name = "dev.deploy.rollback.approval.wizard"
    _description = "Human Deploy Rollback Approval"

    workspace_id = fields.Many2one("dev.execution.workspace", required=True, readonly=True)
    rollback_kind = fields.Selection(
        [("code_rollback", "Code Rollback"), ("database_rollback", "Database Rollback")],
        required=True,
        default="code_rollback",
    )
    destructive = fields.Boolean(default=False)
    reason = fields.Text(required=True)
    confirm_never_automatic = fields.Boolean(
        string="I confirm this rollback is a deliberate human decision, never automatic"
    )

    def action_approve(self):
        self.ensure_one()
        if not self.confirm_never_automatic:
            raise UserError("The explicit rollback confirmation is required.")
        approval = self.workspace_id.create_rollback_approval(
            self.rollback_kind, self.destructive, self.reason
        )
        return approval.workspace_id._form_action()


class DevRollbackExecutionWizard(models.TransientModel):
    _name = "dev.deploy.rollback.execution.wizard"
    _description = "Final Rollback Execution Confirmation"

    workspace_id = fields.Many2one("dev.execution.workspace", required=True, readonly=True)
    approval_id = fields.Many2one("dev.deploy.rollback.approval", required=True, readonly=True)
    confirm_execute_rollback = fields.Boolean(
        string="Execute this exact approved rollback"
    )

    def action_execute(self):
        self.ensure_one()
        if not self.confirm_execute_rollback:
            raise UserError("The rollback execution confirmation is required.")
        record = self.workspace_id.execute_approved_rollback(self.approval_id)
        return record.workspace_id._form_action()
