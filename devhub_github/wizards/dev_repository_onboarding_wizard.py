# -*- coding: utf-8 -*-
from odoo import fields, models
from odoo.exceptions import UserError


class DevRepositoryDiscoveryWizard(models.TransientModel):
    _name = "dev.repository.discovery.wizard"
    _description = "Repository Discovery Scan Wizard"

    project_id = fields.Many2one("dev.project", required=True)
    local_path = fields.Char(required=True)
    selected_remote_name = fields.Char()

    def action_scan(self):
        self.ensure_one()
        discovery = self.env["dev.repository.discovery"].create(
            {
                "name": "Scan %s" % self.local_path,
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
    _description = "Human Repository Bind Approval Wizard"

    discovery_id = fields.Many2one("dev.repository.discovery", required=True, readonly=True)
    installation_id = fields.Many2one("dev.github.app.installation", required=True)
    requester_id = fields.Many2one("res.users", required=True)
    confirm_exact_bind = fields.Boolean(
        string="I approve binding this exact local path to this exact GitHub repository"
    )
    confirm_app_authorized = fields.Boolean(
        string="I confirm the GitHub App Selected-repositories allowlist includes this repository"
    )
    confirm_origin_lock = fields.Boolean(
        string="I confirm origin will be locked and agents cannot retarget it"
    )

    def action_approve(self):
        self.ensure_one()
        if not (
            self.confirm_exact_bind
            and self.confirm_app_authorized
            and self.confirm_origin_lock
        ):
            raise UserError("All bind confirmations are required.")
        approval = self.discovery_id.project_id.create_repository_bind_approval(
            self.discovery_id, self.installation_id, self.requester_id
        )
        record = self.discovery_id.project_id.execute_repository_bind(approval)
        return {
            "type": "ir.actions.act_window",
            "name": "Bind Record",
            "res_model": "dev.repository.bind.record",
            "res_id": record.id,
            "view_mode": "form",
            "target": "current",
        }


class DevRepositoryBootstrapApprovalWizard(models.TransientModel):
    _name = "dev.repository.bootstrap.approval.wizard"
    _description = "Human Repository Bootstrap Approval Wizard"

    discovery_id = fields.Many2one("dev.repository.discovery", required=True, readonly=True)
    proposed_github_repository = fields.Char(required=True)
    requester_id = fields.Many2one("res.users", required=True)
    confirm_secret_review = fields.Boolean(
        string="I confirm secret/code/IP ownership review is complete"
    )
    confirm_no_upload = fields.Boolean(
        string="I understand bootstrap does not upload code; push gate is still required"
    )

    def action_approve(self):
        self.ensure_one()
        if not (self.confirm_secret_review and self.confirm_no_upload):
            raise UserError("All bootstrap confirmations are required.")
        approval = self.discovery_id.project_id.create_repository_bootstrap_approval(
            self.discovery_id, self.proposed_github_repository, self.requester_id
        )
        record = self.discovery_id.project_id.execute_repository_bootstrap(approval)
        return {
            "type": "ir.actions.act_window",
            "name": "Bootstrap Record",
            "res_model": "dev.repository.bootstrap.record",
            "res_id": record.id,
            "view_mode": "form",
            "target": "current",
        }
