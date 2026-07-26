# -*- coding: utf-8 -*-
import json
import os
import re
import subprocess
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from .dev_execution import SHA1_RE
from .dev_git_commit import _canonical_hash
from .dev_github_credentials import CREDENTIAL_ROOT


STAGING_ENV_TYPES = frozenset({"test", "staging"})
PRODUCTION = "production"
RUNNER_ROOT = "/srv/devhub/runners/"
MODULE_NAME_RE = re.compile(r"^[a-z0-9_]+$")
DEPLOYED_OR_FAILED_STATES = (
    "deployed_staging_reviewed",
    "deploy_staging_failed_safely",
    "deploy_staging_uncertain",
    "deployed_production_reviewed",
    "deploy_production_failed_safely",
    "deploy_production_uncertain",
)


def _module_lines(text):
    return sorted({line.strip() for line in (text or "").splitlines() if line.strip()})


class DevDeployTarget(models.Model):
    _name = "dev.deploy.target"
    _description = "Registered Human-Approved Deploy Target"
    _order = "repository_id, target_kind, name"

    name = fields.Char(required=True)
    repository_id = fields.Many2one("dev.repository", required=True, ondelete="restrict")
    environment_id = fields.Many2one("dev.environment", required=True, ondelete="restrict")
    target_kind = fields.Selection(
        [("staging", "Staging"), ("production", "Production")],
        required=True,
        default="staging",
    )
    machine_id = fields.Many2one("dev.machine", required=True, ondelete="restrict")
    database_identifier = fields.Char(required=True)
    module_allowlist = fields.Text(
        required=True, help="One lowercase snake_case module name per line."
    )
    runner_profile_reference = fields.Char(required=True)
    backup_profile_reference = fields.Char(required=True)
    required_protected_branch = fields.Char(required=True, default="staging")
    approved = fields.Boolean(default=False, required=True)
    active = fields.Boolean(default=True)
    non_production = fields.Boolean(default=True, required=True)
    soak_days_required = fields.Integer(default=7, required=True)

    @api.onchange("target_kind")
    def _onchange_target_kind(self):
        for record in self:
            if record.target_kind == "staging":
                record.non_production = True
                record.required_protected_branch = "staging"
            else:
                record.non_production = False
                if record.required_protected_branch not in ("main", "master", "production"):
                    record.required_protected_branch = "main"

    @api.constrains(
        "target_kind",
        "environment_id",
        "non_production",
        "required_protected_branch",
        "database_identifier",
        "module_allowlist",
        "runner_profile_reference",
        "backup_profile_reference",
        "soak_days_required",
    )
    def _check_target_policy(self):
        for record in self:
            if record.target_kind == "staging":
                if (
                    record.environment_id.environment_type not in STAGING_ENV_TYPES
                    or record.environment_id.is_production
                ):
                    raise ValidationError(
                        "A staging deploy target cannot reference a production environment."
                    )
                if record.non_production is not True:
                    raise ValidationError(
                        "Staging deploy targets must be marked non-production."
                    )
                if record.required_protected_branch != "staging":
                    raise ValidationError(
                        "Staging deploy targets require the exact staging protected branch."
                    )
            elif record.target_kind == "production":
                if not record.environment_id.is_production:
                    raise ValidationError(
                        "A production deploy target requires a production environment."
                    )
                if record.non_production is not False:
                    raise ValidationError(
                        "Production deploy targets must not be marked non-production."
                    )
                if record.required_protected_branch not in ("main", "master", "production"):
                    raise ValidationError(
                        "Production deploy targets require an exact protected branch name."
                    )
                if record.soak_days_required < 1:
                    raise ValidationError(
                        "Production deploy targets require at least one soak day."
                    )
            else:
                raise ValidationError("Unknown deploy target kind.")
            if record.database_identifier != record.environment_id.database_identifier:
                raise ValidationError(
                    "The deploy target database must match its environment database."
                )
            for line in (record.module_allowlist or "").splitlines():
                line = line.strip()
                if line and not MODULE_NAME_RE.fullmatch(line):
                    raise ValidationError(
                        "Module allowlist entries must be lowercase snake_case names."
                    )
            canonical_runner = os.path.realpath(record.runner_profile_reference or "")
            if not canonical_runner.startswith(RUNNER_ROOT):
                raise ValidationError(
                    "Runner profile references must stay under the protected runner root."
                )
            canonical_backup = os.path.realpath(record.backup_profile_reference or "")
            if not (
                canonical_backup.startswith(CREDENTIAL_ROOT)
                or canonical_backup.startswith(RUNNER_ROOT)
            ):
                raise ValidationError(
                    "Backup profile references must stay under an approved protected root."
                )

    def assert_target_ready(self):
        self.ensure_one()
        if not self.active or not self.approved:
            raise AccessError("Deploy target is not approved for use.")
        policy = self.env["dev.policy"].sudo().search(
            [
                ("active", "=", True),
                ("project_id", "=", self.repository_id.project_id.id),
                ("environment_id", "in", [self.environment_id.id, False]),
            ],
            order="environment_id desc",
            limit=1,
        )
        if not policy or not policy.deploy_permission:
            raise AccessError(
                "Deploy target requires an active policy granting deploy permission."
            )
        return policy


class DevDeployApproval(models.Model):
    _name = "dev.deploy.approval"
    _description = "Immutable Human Deploy Approval"
    _order = "approved_at desc, id desc"

    workspace_id = fields.Many2one(
        "dev.execution.workspace", required=True, readonly=True, ondelete="restrict"
    )
    target_id = fields.Many2one(
        "dev.deploy.target", required=True, readonly=True, ondelete="restrict"
    )
    merge_sha = fields.Char(required=True, readonly=True)
    merge_record_id = fields.Many2one(
        "dev.git.merge.record", required=True, readonly=True, ondelete="restrict"
    )
    protected_branch = fields.Char(required=True, readonly=True)
    environment_type = fields.Char(required=True, readonly=True)
    database_identifier = fields.Char(required=True, readonly=True)
    module_allowlist_digest = fields.Char(required=True, readonly=True)
    runner_profile_reference = fields.Char(required=True, readonly=True)
    plan_hash = fields.Char(required=True, readonly=True)
    policy_hash = fields.Char(required=True, readonly=True)
    contract_hash = fields.Char(required=True, readonly=True)
    idempotency_key = fields.Char(required=True, readonly=True, index=True)
    requester_id = fields.Many2one(
        "res.users", required=True, readonly=True, ondelete="restrict"
    )
    approver_id = fields.Many2one(
        "res.users", required=True, readonly=True, ondelete="restrict"
    )
    approved_at = fields.Datetime(required=True, readonly=True)
    binding_hash = fields.Char(required=True, readonly=True, copy=False)
    event_ids = fields.One2many("dev.deploy.approval.event", "approval_id", readonly=True)

    def _binding(self):
        self.ensure_one()
        names = (
            "workspace_id",
            "target_id",
            "merge_sha",
            "merge_record_id",
            "protected_branch",
            "environment_type",
            "database_identifier",
            "module_allowlist_digest",
            "runner_profile_reference",
            "plan_hash",
            "policy_hash",
            "contract_hash",
            "idempotency_key",
            "requester_id",
            "approver_id",
            "approved_at",
        )
        return {
            name: self[name].id
            if self._fields[name].type == "many2one"
            else fields.Datetime.to_string(self[name])
            if self._fields[name].type == "datetime"
            else self[name] or ""
            for name in names
        }

    def assert_integrity(self):
        for record in self:
            if record.binding_hash != _canonical_hash(record._binding()):
                raise AccessError("Deploy approval integrity validation failed.")
        return True

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("dev_deploy_approval"):
            raise AccessError("Deploy approvals require guarded human review.")
        records = super().create(vals_list)
        for record in records:
            super(DevDeployApproval, record).write(
                {"binding_hash": _canonical_hash(record._binding())}
            )
        return records.with_context(dev_deploy_approval=False)

    def write(self, values):
        raise AccessError("Deploy approvals are immutable.")

    def unlink(self):
        raise AccessError("Deploy approvals are retained for audit.")


class DevDeployApprovalEvent(models.Model):
    _name = "dev.deploy.approval.event"
    _description = "Immutable Deploy Approval Event"
    _order = "occurred_at desc, id desc"

    approval_id = fields.Many2one(
        "dev.deploy.approval", required=True, readonly=True, ondelete="restrict"
    )
    event_type = fields.Selection(
        [
            ("consumed", "Consumed"),
            ("failed_safely", "Failed Safely"),
            ("uncertain", "Uncertain"),
            ("reconciled", "Reconciled"),
            ("rejected", "Rejected"),
        ],
        required=True,
        readonly=True,
    )
    occurred_at = fields.Datetime(
        required=True, readonly=True, default=fields.Datetime.now
    )
    actor_id = fields.Many2one(
        "res.users", required=True, readonly=True, ondelete="restrict"
    )
    summary = fields.Char(required=True, readonly=True)
    payload_json = fields.Text(readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("dev_deploy_event"):
            raise AccessError("Deploy events require a guarded action.")
        return super().create(vals_list)

    def write(self, values):
        raise AccessError("Deploy events are immutable.")

    def unlink(self):
        raise AccessError("Deploy events are retained for audit.")


class DevDeployRecord(models.Model):
    _name = "dev.deploy.record"
    _description = "Immutable Terminal Deploy Record"
    _order = "deployed_at desc, id desc"

    workspace_id = fields.Many2one(
        "dev.execution.workspace", required=True, readonly=True, ondelete="restrict"
    )
    target_id = fields.Many2one(
        "dev.deploy.target", required=True, readonly=True, ondelete="restrict"
    )
    approval_id = fields.Many2one(
        "dev.deploy.approval", required=True, readonly=True, ondelete="restrict"
    )
    result_state = fields.Selection(
        [
            ("succeeded", "Succeeded"),
            ("failed_safely", "Failed Safely"),
            ("uncertain", "Uncertain"),
            ("reconciled", "Reconciled"),
        ],
        required=True,
        readonly=True,
    )
    remote_result = fields.Text(required=True, readonly=True)
    deployed_at = fields.Datetime(required=True, readonly=True)
    idempotency_key = fields.Char(required=True, readonly=True, index=True)
    audit_hash = fields.Char(required=True, readonly=True, copy=False)

    _idempotency_unique = models.Constraint(
        "unique(idempotency_key)",
        "A deploy with this exact idempotency key was already recorded; replay is denied.",
    )

    def _audit_values(self):
        self.ensure_one()
        return {
            "workspace_id": self.workspace_id.id,
            "target_id": self.target_id.id,
            "approval_id": self.approval_id.id,
            "result_state": self.result_state,
            "deployed_at": fields.Datetime.to_string(self.deployed_at),
            "idempotency_key": self.idempotency_key,
        }

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("dev_deploy_record"):
            raise AccessError("Deploy records require guarded creation.")
        records = super().create(vals_list)
        for record in records:
            super(DevDeployRecord, record).write(
                {"audit_hash": _canonical_hash(record._audit_values())}
            )
        return records

    def write(self, values):
        raise AccessError("Deploy records are immutable.")

    def unlink(self):
        raise AccessError("Deploy records are retained for audit.")


class DevDeployPromotionEvidence(models.Model):
    _name = "dev.deploy.promotion.evidence"
    _description = "Staging Soak Evidence Required Before Production Promotion"
    _order = "soak_started_at desc, id desc"

    staging_deploy_record_id = fields.Many2one(
        "dev.deploy.record", required=True, ondelete="restrict"
    )
    staging_merge_sha = fields.Char(required=True, index=True)
    soak_started_at = fields.Datetime(required=True)
    soak_days_required = fields.Integer(
        related="staging_deploy_record_id.target_id.soak_days_required",
        store=True,
        readonly=True,
    )
    soak_satisfied = fields.Boolean(compute="_compute_soak_satisfied", store=True)
    notes = fields.Text()
    active = fields.Boolean(default=True)

    @api.depends("soak_started_at", "soak_days_required")
    def _compute_soak_satisfied(self):
        now = fields.Datetime.now()
        for record in self:
            record.soak_satisfied = bool(
                record.soak_started_at
                and record.soak_days_required
                and now >= record.soak_started_at + timedelta(days=record.soak_days_required)
            )

    @api.constrains("staging_deploy_record_id")
    def _check_staging_record(self):
        for record in self:
            deploy_record = record.staging_deploy_record_id
            if (
                deploy_record.target_id.target_kind != "staging"
                or deploy_record.result_state not in ("succeeded", "reconciled")
            ):
                raise ValidationError(
                    "Promotion evidence requires one succeeded staging deploy record."
                )


class DevDeployRollbackApproval(models.Model):
    _name = "dev.deploy.rollback.approval"
    _description = "Immutable Human Deploy Rollback Approval"
    _order = "approved_at desc, id desc"

    workspace_id = fields.Many2one(
        "dev.execution.workspace", required=True, readonly=True, ondelete="restrict"
    )
    deploy_record_id = fields.Many2one(
        "dev.deploy.record", required=True, readonly=True, ondelete="restrict"
    )
    target_id = fields.Many2one(
        "dev.deploy.target", required=True, readonly=True, ondelete="restrict"
    )
    rollback_kind = fields.Selection(
        [("code_rollback", "Code Rollback"), ("database_rollback", "Database Rollback")],
        required=True,
        readonly=True,
    )
    destructive = fields.Boolean(required=True, readonly=True)
    reason = fields.Text(required=True, readonly=True)
    requester_id = fields.Many2one(
        "res.users", required=True, readonly=True, ondelete="restrict"
    )
    approver_id = fields.Many2one(
        "res.users", required=True, readonly=True, ondelete="restrict"
    )
    idempotency_key = fields.Char(required=True, readonly=True, index=True)
    approved_at = fields.Datetime(required=True, readonly=True)
    binding_hash = fields.Char(required=True, readonly=True, copy=False)
    event_ids = fields.One2many(
        "dev.deploy.rollback.approval.event", "approval_id", readonly=True
    )

    def _binding(self):
        self.ensure_one()
        names = (
            "workspace_id",
            "deploy_record_id",
            "target_id",
            "rollback_kind",
            "destructive",
            "reason",
            "requester_id",
            "approver_id",
            "idempotency_key",
            "approved_at",
        )
        return {
            name: self[name].id
            if self._fields[name].type == "many2one"
            else fields.Datetime.to_string(self[name])
            if self._fields[name].type == "datetime"
            else self[name] or ""
            for name in names
        }

    def assert_integrity(self):
        for record in self:
            if record.binding_hash != _canonical_hash(record._binding()):
                raise AccessError("Rollback approval integrity validation failed.")
        return True

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("dev_deploy_rollback_approval"):
            raise AccessError("Rollback approvals require guarded human review.")
        records = super().create(vals_list)
        for record in records:
            super(DevDeployRollbackApproval, record).write(
                {"binding_hash": _canonical_hash(record._binding())}
            )
        return records.with_context(dev_deploy_rollback_approval=False)

    def write(self, values):
        raise AccessError("Rollback approvals are immutable.")

    def unlink(self):
        raise AccessError("Rollback approvals are retained for audit.")


class DevDeployRollbackApprovalEvent(models.Model):
    _name = "dev.deploy.rollback.approval.event"
    _description = "Immutable Rollback Approval Event"
    _order = "occurred_at desc, id desc"

    approval_id = fields.Many2one(
        "dev.deploy.rollback.approval", required=True, readonly=True, ondelete="restrict"
    )
    event_type = fields.Selection(
        [
            ("consumed", "Consumed"),
            ("failed_safely", "Failed Safely"),
            ("uncertain", "Uncertain"),
            ("rejected", "Rejected"),
        ],
        required=True,
        readonly=True,
    )
    occurred_at = fields.Datetime(
        required=True, readonly=True, default=fields.Datetime.now
    )
    actor_id = fields.Many2one(
        "res.users", required=True, readonly=True, ondelete="restrict"
    )
    summary = fields.Char(required=True, readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("dev_deploy_rollback_event"):
            raise AccessError("Rollback events require a guarded action.")
        return super().create(vals_list)

    def write(self, values):
        raise AccessError("Rollback events are immutable.")

    def unlink(self):
        raise AccessError("Rollback events are retained for audit.")


class DevDeployRollbackRecord(models.Model):
    _name = "dev.deploy.rollback.record"
    _description = "Immutable Terminal Rollback Record"
    _order = "rolled_back_at desc, id desc"

    workspace_id = fields.Many2one(
        "dev.execution.workspace", required=True, readonly=True, ondelete="restrict"
    )
    approval_id = fields.Many2one(
        "dev.deploy.rollback.approval", required=True, readonly=True, ondelete="restrict"
    )
    result_state = fields.Selection(
        [
            ("succeeded", "Succeeded"),
            ("failed_safely", "Failed Safely"),
            ("uncertain", "Uncertain"),
        ],
        required=True,
        readonly=True,
    )
    remote_result = fields.Text(required=True, readonly=True)
    rolled_back_at = fields.Datetime(required=True, readonly=True)
    idempotency_key = fields.Char(required=True, readonly=True, index=True)
    audit_hash = fields.Char(required=True, readonly=True, copy=False)

    _rollback_idempotency_unique = models.Constraint(
        "unique(idempotency_key)",
        "A rollback with this exact idempotency key was already recorded; replay is denied.",
    )

    def _audit_values(self):
        self.ensure_one()
        return {
            "workspace_id": self.workspace_id.id,
            "approval_id": self.approval_id.id,
            "result_state": self.result_state,
            "rolled_back_at": fields.Datetime.to_string(self.rolled_back_at),
            "idempotency_key": self.idempotency_key,
        }

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("dev_deploy_rollback_record"):
            raise AccessError("Rollback records require guarded creation.")
        records = super().create(vals_list)
        for record in records:
            super(DevDeployRollbackRecord, record).write(
                {"audit_hash": _canonical_hash(record._audit_values())}
            )
        return records

    def write(self, values):
        raise AccessError("Rollback records are immutable.")

    def unlink(self):
        raise AccessError("Rollback records are retained for audit.")


class DevExecutionWorkspaceDeploy(models.Model):
    _inherit = "dev.execution.workspace"

    deploy_target_id = fields.Many2one("dev.deploy.target", readonly=True)
    deploy_approval_id = fields.Many2one("dev.deploy.approval", readonly=True)
    deploy_record_id = fields.Many2one("dev.deploy.record", readonly=True)
    deployed_at = fields.Datetime(readonly=True)
    rollback_target_id = fields.Many2one("dev.deploy.target", readonly=True)
    rollback_approval_id = fields.Many2one("dev.deploy.rollback.approval", readonly=True)
    rollback_record_id = fields.Many2one("dev.deploy.rollback.record", readonly=True)
    rolled_back_at = fields.Datetime(readonly=True)

    def _verify_sha_on_branch(self, target, sha):
        """Mocked-friendly SHA verification; patch this in tests or use the skip-remote context."""
        self.ensure_one()
        if self.env.context.get("dev_deploy_skip_remote"):
            return True
        runner = os.path.realpath(target.runner_profile_reference or "")
        if not runner.startswith(RUNNER_ROOT) or not os.path.isfile(runner):
            raise UserError(
                "Deploy runner is not configured; the merge SHA cannot be verified "
                "on the protected branch."
            )
        try:
            result = subprocess.run(
                ["git", "ls-remote", self.repository_id.git_remote, target.required_protected_branch],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
                check=False,
                env={
                    "PATH": "/usr/bin:/bin",
                    "HOME": "/nonexistent",
                    "GIT_TERMINAL_PROMPT": "0",
                    "LANG": "C",
                },
            )
        except (OSError, subprocess.TimeoutExpired):
            raise UserError("Unable to reach the remote to verify the protected branch.")
        if result.returncode:
            raise UserError("Unable to verify the merge SHA on the protected branch.")
        remote_sha = result.stdout.decode().split()[0] if result.stdout.strip() else ""
        if not SHA1_RE.fullmatch(remote_sha or "") or remote_sha != sha:
            raise UserError("The merge SHA does not match the protected branch tip.")
        return True

    def create_deploy_approval(self, target):
        self.ensure_one()
        if self.state != "merged_reviewed":
            raise UserError("Deploy approval requires a Merged — Reviewed workspace.")
        if target.repository_id != self.repository_id:
            raise AccessError("Deploy target repository must match the workspace repository.")
        target.assert_target_ready()
        merge_record = self.merge_record_id
        if not merge_record or merge_record.result_state not in ("merged", "reconciled_success"):
            raise AccessError("Deploy requires one verified Merge record.")
        sha = merge_record.merge_sha
        if not SHA1_RE.fullmatch(sha or ""):
            raise UserError("A valid merge SHA is required for deploy.")
        if target.target_kind == "production":
            evidence = self.env["dev.deploy.promotion.evidence"].sudo().search(
                [
                    ("staging_merge_sha", "=", sha),
                    ("soak_satisfied", "=", True),
                ],
                limit=1,
            )
            if not evidence:
                raise AccessError(
                    "Production deploy requires satisfied staging soak evidence for this merge."
                )
        self._verify_sha_on_branch(target, sha)
        requester = self.merge_requester_id or merge_record.requester_id
        approver = self.env.user
        if not requester:
            raise UserError("A deploy requester could not be determined.")
        if requester == approver:
            raise AccessError("Deploy requester and approver must be distinct.")
        module_digest = _canonical_hash(_module_lines(target.module_allowlist))
        idempotency_key = _canonical_hash(
            {
                "target": target.id,
                "merge_sha": sha,
                "database": target.database_identifier,
                "module_digest": module_digest,
            }
        )
        if self.env["dev.deploy.record"].sudo().search_count(
            [("idempotency_key", "=", idempotency_key)]
        ):
            raise AccessError("This exact deploy has already reached a terminal result.")
        approval = self.env["dev.deploy.approval"].sudo().with_context(
            dev_deploy_approval=True
        ).create(
            {
                "workspace_id": self.id,
                "target_id": target.id,
                "merge_sha": sha,
                "merge_record_id": merge_record.id,
                "protected_branch": target.required_protected_branch,
                "environment_type": target.environment_id.environment_type,
                "database_identifier": target.database_identifier,
                "module_allowlist_digest": module_digest,
                "runner_profile_reference": target.runner_profile_reference,
                "plan_hash": self.approved_plan_hash,
                "policy_hash": self.policy_hash,
                "contract_hash": self.execution_contract_hash,
                "idempotency_key": idempotency_key,
                "requester_id": requester.id,
                "approver_id": approver.id,
                "approved_at": fields.Datetime.now(),
                "binding_hash": "pending",
            }
        )
        state = (
            "deploy_staging_approved"
            if target.target_kind == "staging"
            else "deploy_production_approved"
        )
        self.sudo()._internal_write(
            {"state": state, "deploy_target_id": target.id, "deploy_approval_id": approval.id}
        )
        self._event(
            "deploy_approved",
            "Distinct approver approved deploy to %s" % target.target_kind,
        )
        return approval

    def _assert_deploy_approval_current(self, approval):
        self.ensure_one()
        approval.ensure_one()
        expected_state = (
            "deploy_staging_approved"
            if approval.target_id.target_kind == "staging"
            else "deploy_production_approved"
        )
        if self.state != expected_state or self.deploy_approval_id != approval:
            raise AccessError("A current deploy approval is required.")
        if approval.event_ids:
            raise AccessError("Deploy approval was already consumed or invalidated.")
        approval.assert_integrity()
        if approval.requester_id == approval.approver_id:
            raise AccessError("Self-approved deploys are forbidden.")
        self._assert_plan_unchanged()
        return True

    def _run_deploy_runner(self, approval):
        self.ensure_one()
        target = approval.target_id
        runner = os.path.realpath(target.runner_profile_reference or "")
        if not runner.startswith(RUNNER_ROOT) or not os.path.isfile(runner):
            raise UserError("Deploy runner script is not configured.")
        try:
            result = subprocess.run(
                [
                    runner,
                    "--database",
                    target.database_identifier,
                    "--sha",
                    approval.merge_sha,
                    "--idempotency-key",
                    approval.idempotency_key,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=1800,
                check=False,
                env={"PATH": "/usr/bin:/bin", "HOME": "/nonexistent", "LANG": "C"},
            )
        except (OSError, subprocess.TimeoutExpired):
            return {"result_state": "uncertain", "summary": "Deploy runner is unavailable."}
        if result.returncode == 0:
            return {
                "result_state": "succeeded",
                "summary": result.stdout.decode("utf-8", "replace")[:2000],
            }
        return {
            "result_state": "failed_safely",
            "summary": result.stderr.decode("utf-8", "replace")[:2000],
        }

    def _record_deploy_result(self, approval, result_state, summary):
        self.ensure_one()
        now = fields.Datetime.now()
        record = self.env["dev.deploy.record"].sudo().with_context(
            dev_deploy_record=True
        ).create(
            {
                "workspace_id": self.id,
                "target_id": approval.target_id.id,
                "approval_id": approval.id,
                "result_state": result_state,
                "remote_result": summary,
                "deployed_at": now,
                "idempotency_key": approval.idempotency_key,
                "audit_hash": "pending",
            }
        )
        event = "consumed" if result_state in ("succeeded", "reconciled") else result_state
        self.env["dev.deploy.approval.event"].sudo().with_context(
            dev_deploy_event=True
        ).create(
            {
                "approval_id": approval.id,
                "event_type": event,
                "actor_id": self.env.user.id,
                "summary": summary[:200] or result_state,
                "payload_json": json.dumps({"result": result_state}, sort_keys=True),
            }
        )
        kind = approval.target_id.target_kind
        if result_state in ("succeeded", "reconciled"):
            state = (
                "deployed_staging_reviewed" if kind == "staging" else "deployed_production_reviewed"
            )
        elif result_state == "failed_safely":
            state = (
                "deploy_staging_failed_safely"
                if kind == "staging"
                else "deploy_production_failed_safely"
            )
        else:
            state = (
                "deploy_staging_uncertain" if kind == "staging" else "deploy_production_uncertain"
            )
        self.sudo()._internal_write(
            {"state": state, "deploy_record_id": record.id, "deployed_at": now}
        )
        self._event("deploy_%s" % result_state, summary[:200] or result_state)
        return record

    def execute_approved_deploy(self, approval):
        self.ensure_one()
        self.env.cr.execute(
            "SELECT id FROM dev_execution_workspace WHERE id = %s FOR UPDATE NOWAIT",
            [self.id],
        )
        self._assert_deploy_approval_current(approval)
        if self.env["dev.deploy.record"].sudo().search_count(
            [("idempotency_key", "=", approval.idempotency_key)]
        ):
            raise AccessError("Duplicate or replayed deploy execution is denied.")
        if self.env.context.get("dev_deploy_execute_runner"):
            outcome = self._run_deploy_runner(approval)
        elif self.env.context.get("dev_deploy_simulate"):
            outcome = {
                "result_state": "succeeded",
                "summary": "Simulated deploy success (test-only context).",
            }
        else:
            raise UserError(
                "Deploy execution requires an explicit runner or the test-only simulate context."
            )
        return self._record_deploy_result(approval, outcome["result_state"], outcome["summary"])

    def action_request_rollback(self):
        self.ensure_one()
        if self.state not in DEPLOYED_OR_FAILED_STATES:
            raise UserError("Rollback may be requested only after a deploy attempt.")
        self.sudo()._internal_write(
            {"state": "rollback_requested", "rollback_target_id": self.deploy_target_id.id}
        )
        self._event("rollback_requested", "Human requested a deploy rollback")
        return self._form_action()

    def create_rollback_approval(self, rollback_kind, destructive, reason):
        self.ensure_one()
        if self.state != "rollback_requested":
            raise UserError("Rollback approval requires a pending rollback request.")
        if not self.deploy_record_id:
            raise AccessError("Rollback requires one prior deploy record.")
        if not (reason or "").strip():
            raise ValidationError("A rollback reason is required.")
        requester = (
            self.deploy_approval_id.requester_id
            if self.deploy_approval_id
            else self.merge_requester_id
        )
        approver = self.env.user
        if requester and requester == approver:
            raise AccessError("Rollback requester and approver must be distinct.")
        idempotency_key = _canonical_hash(
            {
                "deploy_record": self.deploy_record_id.id,
                "rollback_kind": rollback_kind,
                "destructive": bool(destructive),
            }
        )
        if self.env["dev.deploy.rollback.record"].sudo().search_count(
            [("idempotency_key", "=", idempotency_key)]
        ):
            raise AccessError("This exact rollback has already reached a terminal result.")
        approval = self.env["dev.deploy.rollback.approval"].sudo().with_context(
            dev_deploy_rollback_approval=True
        ).create(
            {
                "workspace_id": self.id,
                "deploy_record_id": self.deploy_record_id.id,
                "target_id": self.rollback_target_id.id or self.deploy_target_id.id,
                "rollback_kind": rollback_kind,
                "destructive": bool(destructive),
                "reason": reason,
                "requester_id": (requester or approver).id,
                "approver_id": approver.id,
                "idempotency_key": idempotency_key,
                "approved_at": fields.Datetime.now(),
                "binding_hash": "pending",
            }
        )
        self.sudo()._internal_write(
            {"state": "rollback_approved", "rollback_approval_id": approval.id}
        )
        self._event("rollback_approved", "Human approved rollback; never automatic")
        return approval

    def _assert_rollback_approval_current(self, approval):
        self.ensure_one()
        approval.ensure_one()
        if self.state != "rollback_approved" or self.rollback_approval_id != approval:
            raise AccessError("A current rollback approval is required.")
        if approval.event_ids:
            raise AccessError("Rollback approval was already consumed or invalidated.")
        approval.assert_integrity()
        if approval.requester_id == approval.approver_id:
            raise AccessError("Self-approved rollbacks are forbidden.")
        return True

    def execute_approved_rollback(self, approval):
        self.ensure_one()
        self.env.cr.execute(
            "SELECT id FROM dev_execution_workspace WHERE id = %s FOR UPDATE NOWAIT",
            [self.id],
        )
        self._assert_rollback_approval_current(approval)
        if self.env["dev.deploy.rollback.record"].sudo().search_count(
            [("idempotency_key", "=", approval.idempotency_key)]
        ):
            raise AccessError("Duplicate or replayed rollback execution is denied.")
        if self.env.context.get("dev_deploy_execute_runner"):
            target = approval.target_id
            runner = os.path.realpath(target.runner_profile_reference or "")
            if not runner.startswith(RUNNER_ROOT) or not os.path.isfile(runner):
                raise UserError("Rollback runner script is not configured.")
            try:
                result = subprocess.run(
                    [runner, "--rollback", "--database", target.database_identifier],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=1800,
                    check=False,
                    env={"PATH": "/usr/bin:/bin", "HOME": "/nonexistent", "LANG": "C"},
                )
            except (OSError, subprocess.TimeoutExpired):
                outcome = {"result_state": "uncertain", "summary": "Rollback runner is unavailable."}
            else:
                outcome = (
                    {"result_state": "succeeded", "summary": result.stdout.decode("utf-8", "replace")[:2000]}
                    if result.returncode == 0
                    else {"result_state": "failed_safely", "summary": result.stderr.decode("utf-8", "replace")[:2000]}
                )
        elif self.env.context.get("dev_deploy_simulate"):
            outcome = {
                "result_state": "succeeded",
                "summary": "Simulated rollback success (test-only context).",
            }
        else:
            raise UserError(
                "Rollback execution requires an explicit runner or the test-only simulate context."
            )
        now = fields.Datetime.now()
        record = self.env["dev.deploy.rollback.record"].sudo().with_context(
            dev_deploy_rollback_record=True
        ).create(
            {
                "workspace_id": self.id,
                "approval_id": approval.id,
                "result_state": outcome["result_state"],
                "remote_result": outcome["summary"],
                "rolled_back_at": now,
                "idempotency_key": approval.idempotency_key,
                "audit_hash": "pending",
            }
        )
        event = "consumed" if outcome["result_state"] == "succeeded" else outcome["result_state"]
        self.env["dev.deploy.rollback.approval.event"].sudo().with_context(
            dev_deploy_rollback_event=True
        ).create(
            {
                "approval_id": approval.id,
                "event_type": event,
                "actor_id": self.env.user.id,
                "summary": outcome["summary"][:200] or outcome["result_state"],
            }
        )
        state = {
            "succeeded": "rolled_back",
            "failed_safely": "rollback_failed",
            "uncertain": "rollback_uncertain",
        }[outcome["result_state"]]
        self.sudo()._internal_write({"state": state, "rollback_record_id": record.id, "rolled_back_at": now})
        self._event("rollback_%s" % outcome["result_state"], outcome["summary"][:200])
        return record
