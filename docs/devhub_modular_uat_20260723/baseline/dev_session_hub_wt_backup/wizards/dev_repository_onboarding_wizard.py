# -*- coding: utf-8 -*-
from odoo import fields, models
from odoo.exceptions import UserError


class DevRepositoryDiscoveryScanWizard(models.TransientModel):
    _name = "dev.repository.discovery.scan.wizard"
    _description = "Read-Only Local Repository Discovery Scan"

    project_id = fields.Many2one("dev.project", required=True)
    local_path = fields.Char(required=True)
    selected_remote_name = fields.Char(
        help="Required only when the repository has more than one remote."
    )

    def action_scan(self):
        self.ensure_one()
        discovery = self.env["dev.repository.discovery"].create(
            {
                "project_id": self.project_id.id,
                "local_path": self.local_path,
                "selected_remote_name": self.selected_remote_name,
            }
        )
        discovery.action_scan()
        return {
            "type": "ir.actions.act_window",
            "name": "Repository Discovery",
            "res_model": "dev.repository.discovery",
            "res_id": discovery.id,
            "view_mode": "form",
            "target": "current",
        }


class DevRepositoryBindApprovalWizard(models.TransientModel):
    _name = "dev.repository.bind.approval.wizard"
    _description = "Human Repository Bind Approval"

    discovery_id = fields.Many2one("dev.repository.discovery", required=True, readonly=True)
    github_repository = fields.Char(related="discovery_id.github_repository", readonly=True)
    local_path = fields.Char(related="discovery_id.local_path", readonly=True)
    allowlist_id = fields.Many2one(
        "dev.github.repository.allowlist",
        required=True,
        domain="[('github_repository', '=', github_repository), ('active', '=', True)]",
    )
    confirm_allowlisted = fields.Boolean(
        string="I confirm this exact repository is on the approved Selected-repo allowlist"
    )
    confirm_no_secrets = fields.Boolean(
        string="I confirm the discovery scan found no forbidden filename markers"
    )

    def action_approve(self):
        self.ensure_one()
        if not (self.confirm_allowlisted and self.confirm_no_secrets):
            raise UserError("Both explicit bind confirmations are required.")
        approval = self.discovery_id.create_bind_approval(self.allowlist_id)
        return {
            "type": "ir.actions.act_window",
            "name": "Repository Discovery",
            "res_model": "dev.repository.discovery",
            "res_id": approval.discovery_id.id,
            "view_mode": "form",
            "target": "current",
        }


class DevRepositoryBindExecutionWizard(models.TransientModel):
    _name = "dev.repository.bind.execution.wizard"
    _description = "Final Repository Bind Confirmation"

    discovery_id = fields.Many2one("dev.repository.discovery", required=True, readonly=True)
    approval_id = fields.Many2one("dev.repository.bind.approval", required=True, readonly=True)
    confirm_bind = fields.Boolean(
        string="Bind this exact local path to this exact GitHub repository"
    )

    def action_bind(self):
        self.ensure_one()
        if not self.confirm_bind:
            raise UserError("The bind confirmation is required.")
        record = self.discovery_id.execute_approved_bind(self.approval_id)
        return {
            "type": "ir.actions.act_window",
            "name": "Repository Bind Record",
            "res_model": "dev.repository.bind.record",
            "res_id": record.id,
            "view_mode": "form",
            "target": "current",
        }


class DevRepositoryBootstrapApprovalWizard(models.TransientModel):
    _name = "dev.repository.bootstrap.approval.wizard"
    _description = "Human Repository Bootstrap Approval"

    discovery_id = fields.Many2one("dev.repository.discovery", required=True, readonly=True)
    github_repository = fields.Char(related="discovery_id.github_repository", readonly=True)
    allowlist_id = fields.Many2one(
        "dev.github.repository.allowlist",
        required=True,
        domain="[('github_repository', '=', github_repository), ('active', '=', True)]",
    )
    confirm_allowlisted = fields.Boolean(
        string="I confirm this exact repository is on the approved Selected-repo allowlist"
    )
    confirm_no_upload_yet = fields.Boolean(
        string="I understand this approval never uploads code; the initial push "
        "still requires the separate push approval gate"
    )

    def action_approve(self):
        self.ensure_one()
        if not (self.confirm_allowlisted and self.confirm_no_upload_yet):
            raise UserError("Both explicit bootstrap confirmations are required.")
        approval = self.discovery_id.create_bootstrap_approval(self.allowlist_id)
        return {
            "type": "ir.actions.act_window",
            "name": "Repository Discovery",
            "res_model": "dev.repository.discovery",
            "res_id": approval.discovery_id.id,
            "view_mode": "form",
            "target": "current",
        }


class DevRepositoryBootstrapExecutionWizard(models.TransientModel):
    _name = "dev.repository.bootstrap.execution.wizard"
    _description = "Final Repository Bootstrap Confirmation"

    discovery_id = fields.Many2one("dev.repository.discovery", required=True, readonly=True)
    approval_id = fields.Many2one(
        "dev.repository.bootstrap.approval", required=True, readonly=True
    )
    confirm_pending_push_only = fields.Boolean(
        string="Record this bootstrap as approved and pending push; do not upload code now"
    )

    def action_bootstrap(self):
        self.ensure_one()
        if not self.confirm_pending_push_only:
            raise UserError("The bootstrap confirmation is required.")
        record = self.discovery_id.execute_approved_bootstrap(self.approval_id)
        return {
            "type": "ir.actions.act_window",
            "name": "Repository Bootstrap Record",
            "res_model": "dev.repository.bootstrap.record",
            "res_id": record.id,
            "view_mode": "form",
            "target": "current",
        }
