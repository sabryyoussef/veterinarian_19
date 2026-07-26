# -*- coding: utf-8 -*-
from odoo import fields, models
from odoo.exceptions import UserError


class DevGitMergeApprovalWizard(models.TransientModel):
    _name = "dev.git.merge.approval.wizard"
    _description = "Dedicated Human Merge Approval"

    workspace_id = fields.Many2one(
        "dev.execution.workspace", required=True, readonly=True
    )
    target_id = fields.Many2one("dev.git.merge.target", required=True, readonly=True)
    github_repository = fields.Char(
        related="target_id.github_repository", readonly=True
    )
    pr_number = fields.Integer(related="workspace_id.merge_pr_number", readonly=True)
    pr_url = fields.Char(related="workspace_id.merge_pr_url", readonly=True)
    requester_id = fields.Many2one(
        related="workspace_id.merge_requester_id", readonly=True
    )
    head_branch = fields.Char(
        related="workspace_id.merge_head_branch", readonly=True
    )
    head_sha = fields.Char(related="workspace_id.merge_head_sha", readonly=True)
    base_branch = fields.Char(
        related="workspace_id.merge_base_branch", readonly=True
    )
    base_sha = fields.Char(related="workspace_id.merge_base_sha", readonly=True)
    merge_method = fields.Char(
        related="workspace_id.merge_method", readonly=True
    )
    checks_summary = fields.Text(
        related="workspace_id.merge_checks_summary", readonly=True
    )
    confirm_exact_merge = fields.Boolean(
        string="I approve this exact repository, PR, head SHA, staging base, and squash method"
    )
    confirm_distinct_approval = fields.Boolean(
        string="I am an Administrator distinct from the merge requester"
    )
    confirm_no_deployment = fields.Boolean(
        string="I understand approval does not merge or trigger deployment"
    )

    def action_approve(self):
        self.ensure_one()
        if not (
            self.confirm_exact_merge
            and self.confirm_distinct_approval
            and self.confirm_no_deployment
        ):
            raise UserError("All explicit Merge confirmations are required.")
        approval = self.workspace_id.create_merge_approval(self.target_id)
        return {
            "type": "ir.actions.act_window",
            "name": "Execution Workspace",
            "res_model": "dev.execution.workspace",
            "res_id": approval.workspace_id.id,
            "view_mode": "form",
            "target": "current",
        }


class DevGitMergeExecutionWizard(models.TransientModel):
    _name = "dev.git.merge.execution.wizard"
    _description = "Final Irreversible Merge Confirmation"

    workspace_id = fields.Many2one(
        "dev.execution.workspace", required=True, readonly=True
    )
    approval_id = fields.Many2one(
        "dev.git.merge.approval", required=True, readonly=True
    )
    github_repository = fields.Char(
        related="approval_id.github_repository", readonly=True
    )
    pr_number = fields.Integer(related="approval_id.pr_number", readonly=True)
    pr_url = fields.Char(related="approval_id.pr_url_reference", readonly=True)
    head_branch = fields.Char(related="approval_id.head_branch", readonly=True)
    head_sha = fields.Char(related="approval_id.head_sha", readonly=True)
    base_branch = fields.Char(related="approval_id.base_branch", readonly=True)
    base_sha = fields.Char(related="approval_id.base_sha", readonly=True)
    merge_method = fields.Char(related="approval_id.merge_method", readonly=True)
    confirmation_text = fields.Text(
        compute="_compute_confirmation_text", readonly=True
    )
    confirm_irreversible_remote_merge = fields.Boolean(
        string="Perform this one irreversible remote squash merge"
    )
    confirm_stop_after_merge = fields.Boolean(
        string="Stop after remote verification; do not deploy, restart, upgrade, or delete branches"
    )

    def _compute_confirmation_text(self):
        for wizard in self:
            approval = wizard.approval_id
            wizard.confirmation_text = (
                "This final action will squash-merge PR #%s at exact head %s into "
                "%s/%s. It is irreversible. It will not deploy, restart services, "
                "upgrade Odoo, or delete branches."
                % (
                    approval.pr_number,
                    approval.head_sha,
                    approval.github_repository,
                    approval.base_branch,
                )
                if approval
                else ""
            )

    def action_merge(self):
        self.ensure_one()
        if not (
            self.confirm_irreversible_remote_merge and self.confirm_stop_after_merge
        ):
            raise UserError("Both final Merge confirmations are required.")
        record = self.workspace_id.execute_approved_merge(self.approval_id)
        return {
            "type": "ir.actions.act_window",
            "name": "Execution Workspace",
            "res_model": "dev.execution.workspace",
            "res_id": record.workspace_id.id,
            "view_mode": "form",
            "target": "current",
        }
