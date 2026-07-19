# -*- coding: utf-8 -*-
from odoo import fields, models
from odoo.exceptions import AccessError


class DevGitPushApprovalWizard(models.TransientModel):
    _name = "dev.git.push.approval.wizard"
    _description = "Human Git Push Approval Wizard"

    workspace_id = fields.Many2one(
        "dev.execution.workspace", required=True, readonly=True
    )
    remote_id = fields.Many2one("dev.git.remote", required=True, readonly=True)
    work_item_id = fields.Many2one(
        related="workspace_id.work_item_id", readonly=True
    )
    local_branch = fields.Char(
        related="workspace_id.execution_branch", readonly=True
    )
    local_head = fields.Char(related="workspace_id.current_head", readonly=True)
    commit_sha = fields.Char(related="workspace_id.committed_sha", readonly=True)
    commit_message = fields.Text(
        related="workspace_id.commit_record_id.approval_id.commit_message", readonly=True
    )
    remote_branch = fields.Char(
        related="workspace_id.push_remote_branch", readonly=True
    )
    remote_head = fields.Char(
        related="workspace_id.push_remote_head", readonly=True
    )
    ahead_count = fields.Integer(
        related="workspace_id.push_ahead_count", readonly=True
    )
    behind_count = fields.Integer(
        related="workspace_id.push_behind_count", readonly=True
    )
    last_remote_check_at = fields.Datetime(
        related="workspace_id.last_remote_check_at", readonly=True
    )
    confirmation_text = fields.Text(compute="_compute_confirmation")
    confirm_exact_push = fields.Boolean(
        string="I approve exactly this normal non-force Push"
    )

    def _compute_confirmation(self):
        for wizard in self:
            wizard.confirmation_text = (
                "This will approve commit %s from branch %s for remote %s/%s. "
                "It will not create a PR, merge, or deploy."
                % (
                    wizard.commit_sha or "",
                    wizard.local_branch or "",
                    wizard.remote_id.name or "",
                    wizard.remote_branch or "",
                )
            )

    def action_approve(self):
        self.ensure_one()
        if not self.confirm_exact_push:
            raise AccessError("Explicit human Push approval is required.")
        approval = self.workspace_id.create_push_approval(self.remote_id)
        return self.workspace_id._form_action()


class DevGitPushExecutionWizard(models.TransientModel):
    _name = "dev.git.push.execution.wizard"
    _description = "Human Git Push Execution Confirmation"

    workspace_id = fields.Many2one(
        "dev.execution.workspace", required=True, readonly=True
    )
    approval_id = fields.Many2one(
        "dev.git.push.approval", required=True, readonly=True
    )
    local_branch = fields.Char(related="approval_id.local_branch", readonly=True)
    commit_sha = fields.Char(related="approval_id.commit_sha", readonly=True)
    remote_id = fields.Many2one(related="approval_id.remote_id", readonly=True)
    remote_branch = fields.Char(related="approval_id.remote_branch", readonly=True)
    approver_id = fields.Many2one(related="approval_id.approver_id", readonly=True)
    approved_at = fields.Datetime(related="approval_id.approved_at", readonly=True)
    binding_hash = fields.Char(related="approval_id.binding_hash", readonly=True)
    confirmation_text = fields.Text(compute="_compute_confirmation")
    confirm_push_now = fields.Boolean(
        string="I confirm Push now and understand it stops afterward"
    )

    def _compute_confirmation(self):
        for wizard in self:
            wizard.confirmation_text = (
                "This will push commit %s from branch %s to remote %s/%s. "
                "It will not create a PR, merge, or deploy."
                % (
                    wizard.commit_sha or "",
                    wizard.local_branch or "",
                    wizard.remote_id.name or "",
                    wizard.remote_branch or "",
                )
            )

    def action_execute(self):
        self.ensure_one()
        if not self.confirm_push_now:
            raise AccessError("Explicit human Push confirmation is required.")
        self.workspace_id.execute_approved_push(self.approval_id)
        return self.workspace_id._form_action()
