# -*- coding: utf-8 -*-
from odoo import fields, models


class DevGitCommitApprovalWizard(models.TransientModel):
    _name = "dev.git.commit.approval.wizard"
    _description = "Explicit Human Git Commit Approval"

    workspace_id = fields.Many2one(
        "dev.execution.workspace", required=True, readonly=True
    )
    work_item_id = fields.Many2one(
        related="workspace_id.work_item_id", readonly=True
    )
    branch = fields.Char(related="workspace_id.execution_branch", readonly=True)
    base_head = fields.Char(related="workspace_id.base_head", readonly=True)
    current_head = fields.Char(related="workspace_id.current_head", readonly=True)
    dirty_digest = fields.Char(related="workspace_id.dirty_digest", readonly=True)
    changed_files_digest = fields.Char(
        related="workspace_id.changed_files_digest", readonly=True
    )
    changed_files_summary = fields.Text(
        related="workspace_id.changed_files_summary", readonly=True
    )
    git_status_summary = fields.Text(
        related="workspace_id.git_status_summary", readonly=True
    )
    diff_summary = fields.Text(
        related="workspace_id.review_diff_summary", readonly=True
    )
    tests_summary = fields.Text(
        related="workspace_id.review_tests_summary", readonly=True
    )
    plan_id = fields.Many2one(related="workspace_id.plan_id", readonly=True)
    plan_hash = fields.Char(
        related="workspace_id.approved_plan_hash", readonly=True
    )
    policy_hash = fields.Char(related="workspace_id.policy_hash", readonly=True)
    execution_contract_hash = fields.Char(
        related="workspace_id.execution_contract_hash", readonly=True
    )
    approver_id = fields.Many2one(
        "res.users", default=lambda self: self.env.user, readonly=True
    )
    commit_message = fields.Text(required=True)
    confirmation_note = fields.Char(
        default=(
            "This records an exact-state approval only. It does not create a "
            "commit, push, PR, merge, or deployment."
        ),
        readonly=True,
    )

    def action_confirm_approval(self):
        self.ensure_one()
        self.workspace_id.create_commit_approval(self.commit_message)
        return self.workspace_id._form_action()


class DevGitCommitExecutionWizard(models.TransientModel):
    _name = "dev.git.commit.execution.wizard"
    _description = "Final Human Confirmation for Local Git Commit"

    workspace_id = fields.Many2one(
        "dev.execution.workspace", required=True, readonly=True
    )
    approval_id = fields.Many2one(
        "dev.git.commit.approval", required=True, readonly=True
    )
    work_item_id = fields.Many2one(
        related="workspace_id.work_item_id", readonly=True
    )
    branch = fields.Char(related="approval_id.branch", readonly=True)
    current_head = fields.Char(related="approval_id.current_head", readonly=True)
    dirty_digest = fields.Char(related="approval_id.dirty_digest", readonly=True)
    changed_files_digest = fields.Char(
        related="approval_id.changed_files_digest", readonly=True
    )
    changed_files_summary = fields.Text(
        related="approval_id.changed_files_summary", readonly=True
    )
    commit_message = fields.Text(related="approval_id.commit_message", readonly=True)
    commit_message_hash = fields.Char(
        related="approval_id.commit_message_hash", readonly=True
    )
    approver_id = fields.Many2one(related="approval_id.approver_id", readonly=True)
    binding_hash = fields.Char(related="approval_id.binding_hash", readonly=True)
    confirmation_note = fields.Char(
        default=(
            "Confirm exactly one local commit. No push, PR, merge, deployment, "
            "Production access, branch deletion, or worktree cleanup will occur."
        ),
        readonly=True,
    )

    def action_execute_commit(self):
        self.ensure_one()
        self.workspace_id.execute_approved_commit(self.approval_id)
        return self.workspace_id._form_action()
