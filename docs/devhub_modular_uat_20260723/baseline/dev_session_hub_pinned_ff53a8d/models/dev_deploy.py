# -*- coding: utf-8 -*-
import os
import re
import uuid
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from .dev_execution import SHA1_RE
from .dev_git_commit import _canonical_hash


STAGING_ENV_TYPES = frozenset({"test", "staging"})
MODULE_NAME_RE = re.compile(r"^[a-z0-9_]+$")
RUNNER_ROOT = "/srv/devhub/runners/"
BACKUP_ROOTS = ("/srv/devhub/runners/", "/srv/devhub/credentials/")


def _assert_runner_path(path):
    canonical = os.path.realpath(path or "")
    if not canonical.startswith(RUNNER_ROOT):
        raise ValidationError("Runner profile must stay under /srv/devhub/runners/.")
    return canonical


def _assert_backup_path(path):
    canonical = os.path.realpath(path or "")
    if not any(canonical.startswith(root) for root in BACKUP_ROOTS):
        raise ValidationError("Backup profile must stay under protected Dev Hub roots.")
    return canonical


def _module_allowlist_digest(text):
    modules = []
    for line in (text or "").splitlines():
        name = line.strip()
        if not name or name.startswith("#"):
            continue
        if not MODULE_NAME_RE.fullmatch(name):
            raise ValidationError("Module allowlist entries must match [a-z0-9_]+.")
        modules.append(name)
    if not modules:
        raise ValidationError("Module allowlist must contain at least one module.")
    return _canonical_hash({"modules": modules}), tuple(modules)


class DevDeployTarget(models.Model):
    _name = "dev.deploy.target"
    _description = "Registered Human-Approved Deployment Target"
    _order = "target_kind, repository_id, name"

    name = fields.Char(required=True)
    target_kind = fields.Selection(
        [("staging", "Test/Staging"), ("production", "Production")],
        required=True,
        default="staging",
    )
    repository_id = fields.Many2one("dev.repository", required=True, ondelete="restrict")
    environment_id = fields.Many2one("dev.environment", required=True, ondelete="restrict")
    machine_id = fields.Many2one(
        related="environment_id.machine_id", store=True, readonly=True
    )
    database_identifier = fields.Char(required=True)
    module_allowlist = fields.Text(required=True)
    runner_profile_reference = fields.Char(required=True)
    backup_profile_reference = fields.Char(required=True)
    required_protected_branch = fields.Char(required=True, default="staging")
    soak_days_required = fields.Integer(default=7, required=True)
    approved = fields.Boolean(default=False, required=True)
    non_production = fields.Boolean(default=True, required=True)
    active = fields.Boolean(default=True)

    _target_unique = models.Constraint(
        "unique(repository_id, environment_id, target_kind)",
        "Deploy target registration must be unique.",
    )

    @api.constrains(
        "target_kind",
        "environment_id",
        "database_identifier",
        "module_allowlist",
        "runner_profile_reference",
        "backup_profile_reference",
        "required_protected_branch",
        "non_production",
        "soak_days_required",
    )
    def _check_target_policy(self):
        for record in self:
            env = record.environment_id
            if env.project_id != record.repository_id.project_id:
                raise ValidationError("Deploy target environment must match repository project.")
            if record.database_identifier != env.database_identifier:
                raise ValidationError("Database identifier must match the environment record.")
            _module_allowlist_digest(record.module_allowlist)
            _assert_runner_path(record.runner_profile_reference)
            _assert_backup_path(record.backup_profile_reference)
            if record.target_kind == "staging":
                if env.environment_type not in STAGING_ENV_TYPES or env.is_production:
                    raise ValidationError(
                        "Staging deploy targets may only reference test/staging environments."
                    )
                if not record.non_production:
                    raise ValidationError("Staging targets must set non_production.")
                if record.required_protected_branch != "staging":
                    raise ValidationError(
                        "Staging deploy requires protected branch 'staging'."
                    )
            elif record.target_kind == "production":
                if env.environment_type != "production" or not env.is_production:
                    raise ValidationError(
                        "Production deploy targets require a production environment."
                    )
                if record.non_production:
                    raise ValidationError("Production targets cannot be marked non_production.")
                if record.soak_days_required < 1:
                    raise ValidationError("Production soak_days_required must be >= 1.")

    def assert_deploy_allowed(self):
        self.ensure_one()
        self._check_target_policy()
        if not self.active or not self.approved:
            raise AccessError("Deploy target is not approved for controlled use.")
        policy = self.env["dev.policy"].search(
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
                "Deploy requires an active policy with deploy_permission enabled "
                "for this environment scope."
            )
        if self.target_kind == "staging" and policy.production_access_policy != "denied":
            raise AccessError("Staging deploy policy must deny production access.")
        if (
            self.target_kind == "production"
            and policy.production_access_policy != "approved_only"
        ):
            raise AccessError(
                "Production deploy requires production_access_policy=approved_only."
            )
        return policy


class DevDeployApproval(models.Model):
    _name = "dev.deploy.approval"
    _description = "Immutable Human Deployment Approval"
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
    requester_id = fields.Many2one("res.users", required=True, readonly=True, ondelete="restrict")
    approver_id = fields.Many2one("res.users", required=True, readonly=True, ondelete="restrict")
    binding_hash = fields.Char(required=True, readonly=True, copy=False)
    approved_at = fields.Datetime(required=True, readonly=True)
    event_ids = fields.One2many("dev.deploy.approval.event", "approval_id")

    _idempotency_unique = models.Constraint(
        "unique(idempotency_key)",
        "Deploy idempotency keys must be unique.",
    )

    def _binding(self):
        self.ensure_one()
        return {
            "workspace_id": self.workspace_id.id,
            "target_id": self.target_id.id,
            "merge_sha": self.merge_sha,
            "merge_record_id": self.merge_record_id.id,
            "protected_branch": self.protected_branch,
            "environment_type": self.environment_type,
            "database_identifier": self.database_identifier,
            "module_allowlist_digest": self.module_allowlist_digest,
            "runner_profile_reference": self.runner_profile_reference,
            "plan_hash": self.plan_hash,
            "policy_hash": self.policy_hash,
            "contract_hash": self.contract_hash,
            "idempotency_key": self.idempotency_key,
            "requester_id": self.requester_id.id,
            "approver_id": self.approver_id.id,
        }

    def assert_integrity(self):
        self.ensure_one()
        if self.binding_hash != _canonical_hash(self._binding()):
            raise AccessError("Deploy approval binding hash integrity check failed.")
        return True

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("dev_deploy_approval"):
            raise AccessError("Deploy approvals may only be created through the guarded flow.")
        records = super().create(vals_list)
        for record in records:
            record.with_context(dev_deploy_approval_hash=True).write(
                {"binding_hash": _canonical_hash(record._binding())}
            )
        return records

    def write(self, vals):
        if self.env.context.get("dev_deploy_approval_hash"):
            return super().write(vals)
        raise AccessError("Deploy approvals are immutable.")

    def unlink(self):
        raise AccessError("Deploy approvals are immutable.")


class DevDeployApprovalEvent(models.Model):
    _name = "dev.deploy.approval.event"
    _description = "Deployment Approval Event"
    _order = "id desc"

    approval_id = fields.Many2one(
        "dev.deploy.approval", required=True, readonly=True, ondelete="restrict"
    )
    event_type = fields.Selection(
        [
            ("consumed", "Consumed"),
            ("rejected", "Rejected"),
            ("superseded", "Superseded"),
        ],
        required=True,
        readonly=True,
    )
    note = fields.Char(readonly=True)
    created_at = fields.Datetime(required=True, readonly=True, default=fields.Datetime.now)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("dev_deploy_event"):
            raise AccessError("Deploy events may only be created through the guarded flow.")
        return super().create(vals_list)

    def write(self, vals):
        raise AccessError("Deploy events are immutable.")

    def unlink(self):
        raise AccessError("Deploy events are immutable.")


class DevDeployRecord(models.Model):
    _name = "dev.deploy.record"
    _description = "Terminal Deployment Record"
    _order = "id desc"

    approval_id = fields.Many2one(
        "dev.deploy.approval", required=True, readonly=True, ondelete="restrict"
    )
    workspace_id = fields.Many2one(
        "dev.execution.workspace", required=True, readonly=True, ondelete="restrict"
    )
    target_id = fields.Many2one(
        "dev.deploy.target", required=True, readonly=True, ondelete="restrict"
    )
    merge_sha = fields.Char(required=True, readonly=True)
    idempotency_key = fields.Char(required=True, readonly=True, index=True)
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
    lease_token = fields.Char(required=True, readonly=True)
    backup_checkpoint_ref = fields.Char(readonly=True)
    audit_hash = fields.Char(required=True, readonly=True, copy=False)
    deployed_at = fields.Datetime(required=True, readonly=True, default=fields.Datetime.now)

    _deploy_idempotency_unique = models.Constraint(
        "unique(idempotency_key)",
        "Deploy records must be unique per idempotency key.",
    )

    def _payload(self):
        self.ensure_one()
        return {
            "approval_id": self.approval_id.id,
            "workspace_id": self.workspace_id.id,
            "target_id": self.target_id.id,
            "merge_sha": self.merge_sha,
            "idempotency_key": self.idempotency_key,
            "result_state": self.result_state,
            "lease_token": self.lease_token,
            "backup_checkpoint_ref": self.backup_checkpoint_ref or "",
        }

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("dev_deploy_record"):
            raise AccessError("Deploy records may only be created through the guarded flow.")
        records = super().create(vals_list)
        for record in records:
            record.with_context(dev_deploy_record_hash=True).write(
                {"audit_hash": _canonical_hash(record._payload())}
            )
        return records

    def write(self, vals):
        if self.env.context.get("dev_deploy_record_hash"):
            return super().write(vals)
        raise AccessError("Deploy records are immutable.")

    def unlink(self):
        raise AccessError("Deploy records are immutable.")


class DevDeployRollbackApproval(models.Model):
    _name = "dev.deploy.rollback.approval"
    _description = "Immutable Human Rollback Approval"
    _order = "approved_at desc, id desc"

    deploy_record_id = fields.Many2one(
        "dev.deploy.record", required=True, readonly=True, ondelete="restrict"
    )
    workspace_id = fields.Many2one(
        "dev.execution.workspace", required=True, readonly=True, ondelete="restrict"
    )
    rollback_kind = fields.Selection(
        [("code", "Code Rollback"), ("database", "Database/Filestore Rollback")],
        required=True,
        readonly=True,
    )
    destructive = fields.Boolean(required=True, readonly=True, default=True)
    requester_id = fields.Many2one("res.users", required=True, readonly=True, ondelete="restrict")
    approver_id = fields.Many2one("res.users", required=True, readonly=True, ondelete="restrict")
    binding_hash = fields.Char(required=True, readonly=True, copy=False)
    approved_at = fields.Datetime(required=True, readonly=True)
    event_ids = fields.One2many("dev.deploy.rollback.approval.event", "approval_id")

    def _binding(self):
        self.ensure_one()
        return {
            "deploy_record_id": self.deploy_record_id.id,
            "workspace_id": self.workspace_id.id,
            "rollback_kind": self.rollback_kind,
            "destructive": self.destructive,
            "requester_id": self.requester_id.id,
            "approver_id": self.approver_id.id,
        }

    def assert_integrity(self):
        self.ensure_one()
        if self.binding_hash != _canonical_hash(self._binding()):
            raise AccessError("Rollback approval integrity check failed.")
        return True

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("dev_deploy_rollback_approval"):
            raise AccessError("Rollback approvals may only be created through the guarded flow.")
        records = super().create(vals_list)
        for record in records:
            record.with_context(dev_deploy_rollback_hash=True).write(
                {"binding_hash": _canonical_hash(record._binding())}
            )
        return records

    def write(self, vals):
        if self.env.context.get("dev_deploy_rollback_hash"):
            return super().write(vals)
        raise AccessError("Rollback approvals are immutable.")

    def unlink(self):
        raise AccessError("Rollback approvals are immutable.")


class DevDeployRollbackApprovalEvent(models.Model):
    _name = "dev.deploy.rollback.approval.event"
    _description = "Rollback Approval Event"
    _order = "id desc"

    approval_id = fields.Many2one(
        "dev.deploy.rollback.approval", required=True, readonly=True, ondelete="restrict"
    )
    event_type = fields.Selection(
        [("consumed", "Consumed"), ("rejected", "Rejected")],
        required=True,
        readonly=True,
    )
    note = fields.Char(readonly=True)
    created_at = fields.Datetime(required=True, readonly=True, default=fields.Datetime.now)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("dev_deploy_rollback_event"):
            raise AccessError("Rollback events may only be created through the guarded flow.")
        return super().create(vals_list)

    def write(self, vals):
        raise AccessError("Rollback events are immutable.")

    def unlink(self):
        raise AccessError("Rollback events are immutable.")


class DevDeployRollbackRecord(models.Model):
    _name = "dev.deploy.rollback.record"
    _description = "Terminal Rollback Record"
    _order = "id desc"

    approval_id = fields.Many2one(
        "dev.deploy.rollback.approval", required=True, readonly=True, ondelete="restrict"
    )
    result_state = fields.Selection(
        [
            ("rolled_back", "Rolled Back"),
            ("rollback_failed", "Rollback Failed"),
            ("rollback_uncertain", "Rollback Uncertain"),
        ],
        required=True,
        readonly=True,
    )
    audit_hash = fields.Char(required=True, readonly=True, copy=False)
    rolled_back_at = fields.Datetime(required=True, readonly=True, default=fields.Datetime.now)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("dev_deploy_rollback_record"):
            raise AccessError("Rollback records may only be created through the guarded flow.")
        records = super().create(vals_list)
        for record in records:
            payload = {
                "approval_id": record.approval_id.id,
                "result_state": record.result_state,
            }
            record.with_context(dev_deploy_rollback_record_hash=True).write(
                {"audit_hash": _canonical_hash(payload)}
            )
        return records

    def write(self, vals):
        if self.env.context.get("dev_deploy_rollback_record_hash"):
            return super().write(vals)
        raise AccessError("Rollback records are immutable.")

    def unlink(self):
        raise AccessError("Rollback records are immutable.")


class DevDeployPromotionEvidence(models.Model):
    _name = "dev.deploy.promotion.evidence"
    _description = "Staging Evidence Required for Production Promotion"
    _order = "id desc"

    staging_deploy_record_id = fields.Many2one(
        "dev.deploy.record", required=True, ondelete="restrict", index=True
    )
    staging_merge_sha = fields.Char(required=True, readonly=True)
    soak_started_at = fields.Datetime(required=True)
    soak_days_required = fields.Integer(required=True, default=7)
    soak_satisfied = fields.Boolean(compute="_compute_soak_satisfied", store=True)
    active = fields.Boolean(default=True)

    @api.depends("soak_started_at", "soak_days_required")
    def _compute_soak_satisfied(self):
        now = fields.Datetime.now()
        for record in self:
            if not record.soak_started_at:
                record.soak_satisfied = False
                continue
            elapsed = now - record.soak_started_at
            record.soak_satisfied = elapsed >= timedelta(days=record.soak_days_required)

    def assert_ready_for_production(self, merge_sha):
        self.ensure_one()
        if not self.active:
            raise AccessError("Promotion evidence is inactive.")
        if self.staging_deploy_record_id.result_state != "succeeded":
            raise AccessError("Staging deploy must have succeeded.")
        if self.staging_merge_sha != merge_sha:
            raise AccessError("Promotion evidence SHA does not match merge SHA.")
        if not self.soak_satisfied:
            raise AccessError("Soak period has not been satisfied.")
        return True


class DevExecutionWorkspaceDeploy(models.Model):
    _inherit = "dev.execution.workspace"

    deploy_approval_ids = fields.One2many("dev.deploy.approval", "workspace_id")
    deploy_record_ids = fields.One2many("dev.deploy.record", "workspace_id")

    def _require_deploy_approver(self, production=False):
        group = (
            "dev_session_hub.group_dev_hub_production_approver"
            if production
            else "dev_session_hub.group_dev_hub_deploy_approver"
        )
        if not self.env.user.has_group(group) and not self.env.user.has_group(
            "dev_session_hub.group_dev_hub_manager"
        ):
            raise AccessError("Insufficient rights for deployment approval.")

    def _latest_merge_record(self):
        self.ensure_one()
        record = self.env["dev.git.merge.record"].search(
            [
                ("workspace_id", "=", self.id),
                ("result_state", "in", ["merged", "reconciled_success"]),
            ],
            order="id desc",
            limit=1,
        )
        if not record or not SHA1_RE.fullmatch(record.merge_sha or ""):
            raise UserError("A terminal successful merge record with SHA is required.")
        return record

    def _verify_sha_on_branch(self, merge_sha, branch):
        if self.env.context.get("dev_deploy_skip_remote"):
            return True
        raise UserError(
            "Remote SHA verification requires an allowlisted runner preflight "
            "(set test context dev_deploy_skip_remote for simulated flows)."
        )

    def create_deploy_approval(self, target, requester):
        self.ensure_one()
        production = target.target_kind == "production"
        self._require_deploy_approver(production=production)
        target.assert_deploy_allowed()
        if self.state != "merged_reviewed":
            raise UserError("Deploy requires workspace state merged_reviewed.")
        if target.repository_id != self.repository_id:
            raise UserError("Deploy target repository must match the workspace.")
        if requester == self.env.user:
            raise AccessError("Deploy requester and approver must be distinct.")
        merge_record = self._latest_merge_record()
        if production:
            evidence = self.env["dev.deploy.promotion.evidence"].search(
                [
                    ("staging_merge_sha", "=", merge_record.merge_sha),
                    ("active", "=", True),
                ],
                limit=1,
            )
            if not evidence:
                raise AccessError("Production deploy requires staging promotion evidence.")
            evidence.assert_ready_for_production(merge_record.merge_sha)
        self._verify_sha_on_branch(merge_record.merge_sha, target.required_protected_branch)
        digest, _modules = _module_allowlist_digest(target.module_allowlist)
        policy = target.assert_deploy_allowed()
        plan_hash = self.execution_contract_hash or _canonical_hash({"workspace": self.id})
        policy_hash = _canonical_hash(
            {
                "policy_id": policy.id,
                "deploy_permission": policy.deploy_permission,
                "production_access_policy": policy.production_access_policy,
            }
        )
        idempotency_key = "%s:%s:%s:%s" % (
            self.id,
            target.id,
            merge_record.merge_sha,
            digest,
        )
        if self.env["dev.deploy.approval"].search_count(
            [("idempotency_key", "=", idempotency_key)]
        ) or self.env["dev.deploy.record"].search_count(
            [("idempotency_key", "=", idempotency_key)]
        ):
            raise AccessError("Deploy replay denied for this idempotency key.")
        approval = (
            self.env["dev.deploy.approval"]
            .with_context(dev_deploy_approval=True, dev_deploy_approval_hash=True)
            .create(
                {
                    "workspace_id": self.id,
                    "target_id": target.id,
                    "merge_sha": merge_record.merge_sha,
                    "merge_record_id": merge_record.id,
                    "protected_branch": target.required_protected_branch,
                    "environment_type": target.environment_id.environment_type,
                    "database_identifier": target.database_identifier,
                    "module_allowlist_digest": digest,
                    "runner_profile_reference": target.runner_profile_reference,
                    "plan_hash": plan_hash,
                    "policy_hash": policy_hash,
                    "contract_hash": self.execution_contract_hash or plan_hash,
                    "idempotency_key": idempotency_key,
                    "requester_id": requester.id,
                    "approver_id": self.env.user.id,
                    "binding_hash": "pending",
                    "approved_at": fields.Datetime.now(),
                }
            )
        )
        new_state = (
            "deploy_production_approved" if production else "deploy_staging_approved"
        )
        self.write({"state": new_state})
        return approval

    def execute_approved_deploy(self, approval):
        self.ensure_one()
        approval.ensure_one()
        production = approval.target_id.target_kind == "production"
        self._require_deploy_approver(production=production)
        approval.assert_integrity()
        if approval.workspace_id != self:
            raise UserError("Approval workspace mismatch.")
        if approval.event_ids:
            raise AccessError("A current immutable Deploy approval is required.")
        if approval.approver_id != self.env.user:
            raise AccessError("Only the deploy approver may execute.")
        if self.env["dev.deploy.record"].search_count(
            [("idempotency_key", "=", approval.idempotency_key)]
        ):
            raise AccessError("Deploy replay denied.")
        running_state = (
            "deploy_production_running" if production else "deploy_staging_running"
        )
        self.write({"state": running_state})
        lease_token = uuid.uuid4().hex
        simulate = self.env.context.get("dev_deploy_simulate")
        execute_runner = self.env.context.get("dev_deploy_execute_runner")
        result_state = "succeeded"
        backup_ref = ""
        if execute_runner and not simulate:
            raise UserError(
                "Live runner execution is disabled in this control-plane build; "
                "use an approved operator runbook with the allowlisted runner stub."
            )
        if not simulate and not self.env.context.get("dev_deploy_skip_remote"):
            result_state = "failed_safely"
            self.write({"state": "deploy_staging_failed_safely"})
        elif simulate:
            backup_ref = "simulate://checkpoint/%s" % lease_token[:12]
            result_state = "succeeded"
            done_state = (
                "deployed_production_reviewed"
                if production
                else "deployed_staging_reviewed"
            )
            self.write({"state": done_state})
        record = (
            self.env["dev.deploy.record"]
            .with_context(dev_deploy_record=True)
            .create(
                {
                    "approval_id": approval.id,
                    "workspace_id": self.id,
                    "target_id": approval.target_id.id,
                    "merge_sha": approval.merge_sha,
                    "idempotency_key": approval.idempotency_key,
                    "result_state": result_state,
                    "lease_token": lease_token,
                    "backup_checkpoint_ref": backup_ref,
                    "audit_hash": "pending",
                }
            )
        )
        self.env["dev.deploy.approval.event"].with_context(dev_deploy_event=True).create(
            {
                "approval_id": approval.id,
                "event_type": "consumed",
                "note": "Deploy execution recorded (%s)." % result_state,
            }
        )
        if result_state == "succeeded" and not production:
            self.env["dev.deploy.promotion.evidence"].create(
                {
                    "staging_deploy_record_id": record.id,
                    "staging_merge_sha": record.merge_sha,
                    "soak_started_at": fields.Datetime.now(),
                    "soak_days_required": approval.target_id.soak_days_required or 7,
                }
            )
        return record

    def create_rollback_approval(self, deploy_record, rollback_kind, requester):
        self.ensure_one()
        self._require_deploy_approver(production=False)
        deploy_record.ensure_one()
        if deploy_record.workspace_id != self:
            raise UserError("Rollback deploy record workspace mismatch.")
        if requester == self.env.user:
            raise AccessError("Rollback requester and approver must be distinct.")
        if rollback_kind not in ("code", "database"):
            raise ValidationError("Invalid rollback kind.")
        self.write({"state": "rollback_requested"})
        approval = (
            self.env["dev.deploy.rollback.approval"]
            .with_context(
                dev_deploy_rollback_approval=True, dev_deploy_rollback_hash=True
            )
            .create(
                {
                    "deploy_record_id": deploy_record.id,
                    "workspace_id": self.id,
                    "rollback_kind": rollback_kind,
                    "destructive": rollback_kind == "database",
                    "requester_id": requester.id,
                    "approver_id": self.env.user.id,
                    "binding_hash": "pending",
                    "approved_at": fields.Datetime.now(),
                }
            )
        )
        self.write({"state": "rollback_approved"})
        return approval

    def execute_approved_rollback(self, approval):
        self.ensure_one()
        approval.ensure_one()
        self._require_deploy_approver(production=approval.destructive)
        approval.assert_integrity()
        if approval.event_ids:
            raise AccessError("Rollback approval already consumed.")
        if approval.approver_id != self.env.user:
            raise AccessError("Only the rollback approver may execute.")
        simulate = self.env.context.get("dev_deploy_simulate")
        if simulate:
            result_state = "rolled_back"
            self.write({"state": "rolled_back"})
        else:
            result_state = "rollback_uncertain"
            self.write({"state": "rollback_uncertain"})
        record = (
            self.env["dev.deploy.rollback.record"]
            .with_context(dev_deploy_rollback_record=True)
            .create(
                {
                    "approval_id": approval.id,
                    "result_state": result_state,
                    "audit_hash": "pending",
                }
            )
        )
        self.env["dev.deploy.rollback.approval.event"].with_context(
            dev_deploy_rollback_event=True
        ).create(
            {
                "approval_id": approval.id,
                "event_type": "consumed",
                "note": "Rollback execution recorded (%s)." % result_state,
            }
        )
        return record

