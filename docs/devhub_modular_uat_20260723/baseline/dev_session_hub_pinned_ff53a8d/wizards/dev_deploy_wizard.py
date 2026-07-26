# -*- coding: utf-8 -*-
from odoo import fields, models
from odoo.exceptions import UserError


class DevDeployApprovalWizard(models.TransientModel):
    _name = "dev.deploy.approval.wizard"
    _description = "Human Deployment Approval Wizard"

    workspace_id = fields.Many2one("dev.execution.workspace", required=True, readonly=True)
    target_id = fields.Many2one("dev.deploy.target", required=True)
    requester_id = fields.Many2one("res.users", required=True)
    confirm_exact_sha = fields.Boolean(
        string="I approve deploying this exact reviewed merge SHA only"
    )
    confirm_environment = fields.Boolean(
        string="I confirm the bound environment, database, modules, and runner allowlist"
    )
    confirm_no_production = fields.Boolean(
        string="I confirm this approval does not promote to Production"
    )

    def action_approve(self):
        self.ensure_one()
        if self.target_id.target_kind == "staging" and not (
            self.confirm_exact_sha
            and self.confirm_environment
            and self.confirm_no_production
        ):
            raise UserError("All staging deploy confirmations are required.")
        if self.target_id.target_kind == "production":
            raise UserError("Use the production promotion wizard for production targets.")
        approval = self.workspace_id.create_deploy_approval(
            self.target_id, self.requester_id
        )
        return {
            "type": "ir.actions.act_window",
            "name": "Deploy Approval",
            "res_model": "dev.deploy.approval",
            "res_id": approval.id,
            "view_mode": "form",
            "target": "current",
        }


class DevDeployExecutionWizard(models.TransientModel):
    _name = "dev.deploy.execution.wizard"
    _description = "Final Deployment Execution Wizard"

    workspace_id = fields.Many2one("dev.execution.workspace", required=True, readonly=True)
    approval_id = fields.Many2one("dev.deploy.approval", required=True, readonly=True)
    confirm_lease_backup = fields.Boolean(
        string="I confirm lease acquisition and proportional backup/checkpoint"
    )
    confirm_no_blind_retry = fields.Boolean(
        string="I understand failed/uncertain outcomes require reconciliation, not blind retry"
    )

    def action_deploy(self):
        self.ensure_one()
        if not (self.confirm_lease_backup and self.confirm_no_blind_retry):
            raise UserError("Both deploy execution confirmations are required.")
        record = self.workspace_id.execute_approved_deploy(self.approval_id)
        return {
            "type": "ir.actions.act_window",
            "name": "Deploy Record",
            "res_model": "dev.deploy.record",
            "res_id": record.id,
            "view_mode": "form",
            "target": "current",
        }


class DevDeployRollbackApprovalWizard(models.TransientModel):
    _name = "dev.deploy.rollback.approval.wizard"
    _description = "Human Rollback Approval Wizard"

    workspace_id = fields.Many2one("dev.execution.workspace", required=True, readonly=True)
    deploy_record_id = fields.Many2one("dev.deploy.record", required=True)
    rollback_kind = fields.Selection(
        [("code", "Code Rollback"), ("database", "Database/Filestore Rollback")],
        required=True,
    )
    requester_id = fields.Many2one("res.users", required=True)
    confirm_destructive = fields.Boolean(
        string="I understand this is a separate destructive approval"
    )

    def action_approve(self):
        self.ensure_one()
        if not self.confirm_destructive:
            raise UserError("Destructive rollback confirmation is required.")
        approval = self.workspace_id.create_rollback_approval(
            self.deploy_record_id, self.rollback_kind, self.requester_id
        )
        return {
            "type": "ir.actions.act_window",
            "name": "Rollback Approval",
            "res_model": "dev.deploy.rollback.approval",
            "res_id": approval.id,
            "view_mode": "form",
            "target": "current",
        }


class DevDeployRollbackExecutionWizard(models.TransientModel):
    _name = "dev.deploy.rollback.execution.wizard"
    _description = "Final Rollback Execution Wizard"

    workspace_id = fields.Many2one("dev.execution.workspace", required=True, readonly=True)
    approval_id = fields.Many2one(
        "dev.deploy.rollback.approval", required=True, readonly=True
    )
    confirm_execute = fields.Boolean(
        string="Execute this approved rollback; no blind retries"
    )

    def action_rollback(self):
        self.ensure_one()
        if not self.confirm_execute:
            raise UserError("Rollback execution confirmation is required.")
        record = self.workspace_id.execute_approved_rollback(self.approval_id)
        return {
            "type": "ir.actions.act_window",
            "name": "Rollback Record",
            "res_model": "dev.deploy.rollback.record",
            "res_id": record.id,
            "view_mode": "form",
            "target": "current",
        }


class DevDeployProductionApprovalWizard(models.TransientModel):
    _name = "dev.deploy.production.approval.wizard"
    _description = "Human Production Promotion Approval Wizard"

    workspace_id = fields.Many2one("dev.execution.workspace", required=True, readonly=True)
    target_id = fields.Many2one("dev.deploy.target", required=True)
    requester_id = fields.Many2one("res.users", required=True)
    confirm_soak = fields.Boolean(
        string="I confirm staging evidence and soak period are satisfied"
    )
    confirm_maintenance_window = fields.Boolean(
        string="I confirm the maintenance window and fresh backup validation"
    )
    confirm_exact_sha = fields.Boolean(
        string="I approve promoting this exact staging-proven merge SHA"
    )

    def action_approve(self):
        self.ensure_one()
        if self.target_id.target_kind != "production":
            raise UserError("Production wizard requires a production deploy target.")
        if not (
            self.confirm_soak
            and self.confirm_maintenance_window
            and self.confirm_exact_sha
        ):
            raise UserError("All production promotion confirmations are required.")
        approval = self.workspace_id.create_deploy_approval(
            self.target_id, self.requester_id
        )
        return {
            "type": "ir.actions.act_window",
            "name": "Production Deploy Approval",
            "res_model": "dev.deploy.approval",
            "res_id": approval.id,
            "view_mode": "form",
            "target": "current",
        }
