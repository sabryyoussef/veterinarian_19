# -*- coding: utf-8 -*-
from odoo import fields, models
from odoo.exceptions import UserError


class DevGitPullRequestApprovalWizard(models.TransientModel):
    _name = "dev.git.pr.approval.wizard"
    _description = "Human Pull Request Creation Approval"

    workspace_id = fields.Many2one(
        "dev.execution.workspace", required=True, readonly=True
    )
    target_id = fields.Many2one("dev.git.pr.target", required=True, readonly=True)
    source_branch = fields.Char(related="workspace_id.pr_source_branch", readonly=True)
    source_sha = fields.Char(related="workspace_id.pr_source_sha", readonly=True)
    target_branch = fields.Char(related="target_id.target_branch", readonly=True)
    github_repository = fields.Char(
        related="target_id.github_repository", readonly=True
    )
    pr_title = fields.Char(required=True)
    pr_body = fields.Text(required=True)
    confirm_exact_pr = fields.Boolean(
        string="I approve exactly this PR source, target, title, and body"
    )
    confirm_no_merge = fields.Boolean(
        string="I understand this creates an open PR only; it will not merge or deploy"
    )

    def action_approve(self):
        self.ensure_one()
        if not self.confirm_exact_pr or not self.confirm_no_merge:
            raise UserError("Both explicit human confirmations are required.")
        approval = self.workspace_id.create_pr_approval(
            self.target_id, self.pr_title, self.pr_body
        )
        return {
            "type": "ir.actions.act_window",
            "name": "Execution Workspace",
            "res_model": "dev.execution.workspace",
            "res_id": approval.workspace_id.id,
            "view_mode": "form",
            "target": "current",
        }


class DevGitPullRequestExecutionWizard(models.TransientModel):
    _name = "dev.git.pr.execution.wizard"
    _description = "Confirm Exact Pull Request Creation"

    workspace_id = fields.Many2one(
        "dev.execution.workspace", required=True, readonly=True
    )
    approval_id = fields.Many2one(
        "dev.git.pr.approval", required=True, readonly=True
    )
    github_repository = fields.Char(
        related="approval_id.github_repository", readonly=True
    )
    source_branch = fields.Char(related="approval_id.source_branch", readonly=True)
    source_sha = fields.Char(related="approval_id.source_commit_sha", readonly=True)
    target_branch = fields.Char(related="approval_id.target_branch", readonly=True)
    pr_title = fields.Char(related="approval_id.pr_title", readonly=True)
    pr_body = fields.Text(related="approval_id.pr_body", readonly=True)
    confirmation_text = fields.Text(
        compute="_compute_confirmation_text", readonly=True
    )
    confirm_create_open_pr = fields.Boolean(
        string="Create exactly this one open Pull Request"
    )
    confirm_stop_after_creation = fields.Boolean(
        string="Stop after verification; do not merge, auto-merge, or deploy"
    )

    def _compute_confirmation_text(self):
        for wizard in self:
            approval = wizard.approval_id
            wizard.confirmation_text = (
                "This will create one open Pull Request for commit %s from branch %s "
                "to %s/%s. It will not merge, enable auto-merge, or deploy."
                % (
                    approval.source_commit_sha,
                    approval.source_branch,
                    approval.github_repository,
                    approval.target_branch,
                )
                if approval
                else ""
            )

    def action_create_pr(self):
        self.ensure_one()
        if not self.confirm_create_open_pr or not self.confirm_stop_after_creation:
            raise UserError("Both final human confirmations are required.")
        record = self.workspace_id.execute_approved_pr(self.approval_id)
        return {
            "type": "ir.actions.act_window",
            "name": "Execution Workspace",
            "res_model": "dev.execution.workspace",
            "res_id": record.workspace_id.id,
            "view_mode": "form",
            "target": "current",
        }
