# -*- coding: utf-8 -*-
import hashlib
import json
import os
import re
import subprocess
from datetime import timedelta
from urllib.parse import quote

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from .dev_execution import SHA1_RE
from .dev_git_commit import _canonical_hash


MERGE_APP_SLUG = "sabry-uat-merge-agent"
MERGE_METHOD = "squash"
MERGE_PERMISSIONS = {
    "checks": "read",
    "contents": "write",
    "metadata": "read",
    "pull_requests": "read",
    "statuses": "read",
}
SAFE_CHECK_CONCLUSIONS = {"success", "neutral", "skipped"}


class DevGitMergeTarget(models.Model):
    _name = "dev.git.merge.target"
    _description = "Registered Human-Approved Merge Target"
    _order = "repository_id, github_repository, base_branch"

    name = fields.Char(required=True)
    repository_id = fields.Many2one("dev.repository", required=True, ondelete="restrict")
    pr_target_id = fields.Many2one("dev.git.pr.target", required=True, ondelete="restrict")
    github_repository = fields.Char(required=True)
    base_branch = fields.Char(required=True, default="staging")
    merge_method = fields.Selection(
        [(MERGE_METHOD, "Squash")], required=True, default=MERGE_METHOD
    )
    requester_user_id = fields.Many2one("res.users", required=True, ondelete="restrict")
    required_check_name = fields.Char(
        required=True, default="GitGuardian Security Checks"
    )
    required_check_app_id = fields.Integer(required=True, default=46505)
    credential_profile_reference = fields.Char(required=True)
    credential_broker_reference = fields.Char(required=True)
    github_app_slug = fields.Char(required=True, default=MERGE_APP_SLUG)
    github_app_id = fields.Integer(required=True)
    github_installation_id = fields.Integer(required=True)
    credential_repository_restriction = fields.Char(required=True)
    credential_permission_summary = fields.Text(required=True)
    credential_expires_at = fields.Datetime(readonly=True)
    credential_validated_at = fields.Datetime(readonly=True)
    credential_validation_digest = fields.Char(readonly=True)
    approved = fields.Boolean(default=False, required=True)
    non_production = fields.Boolean(default=True, required=True)
    active = fields.Boolean(default=True)

    _target_unique = models.Constraint(
        "unique(repository_id, github_repository, base_branch)",
        "Merge target registration must be unique.",
    )

    @api.constrains(
        "repository_id",
        "pr_target_id",
        "github_repository",
        "base_branch",
        "merge_method",
        "requester_user_id",
        "required_check_name",
        "required_check_app_id",
        "credential_profile_reference",
        "credential_broker_reference",
        "github_app_slug",
        "github_app_id",
        "github_installation_id",
        "credential_repository_restriction",
        "credential_permission_summary",
    )
    def _check_policy(self):
        expected_permissions = "\n".join(
            "%s:%s" % item for item in sorted(MERGE_PERMISSIONS.items())
        )
        for record in self:
            if (
                record.pr_target_id.repository_id != record.repository_id
                or record.pr_target_id.github_repository != record.github_repository
                or record.pr_target_id.target_branch != record.base_branch
                or record.base_branch != "staging"
                or record.merge_method != MERGE_METHOD
            ):
                raise ValidationError(
                    "Merge target must match the registered non-production PR target."
                )
            if (
                record.github_app_slug != MERGE_APP_SLUG
                or record.github_app_id <= 0
                or record.github_installation_id <= 0
                or record.credential_repository_restriction
                != record.github_repository
                or record.credential_permission_summary.strip()
                != expected_permissions
            ):
                raise ValidationError(
                    "Merge App identity and permissions must match exact policy."
                )
            for path in (
                record.credential_profile_reference,
                record.credential_broker_reference,
            ):
                canonical = os.path.realpath(path or "")
                if not canonical.startswith("/srv/devhub/credentials/github/"):
                    raise ValidationError(
                        "Merge credential references must stay under the protected root."
                    )
            if (
                not record.required_check_name
                or record.required_check_app_id <= 0
                or record.requester_user_id.has_group(
                    "dev_session_hub.group_dev_hub_manager"
                )
            ):
                raise ValidationError(
                    "Merge requester must be a dedicated non-manager service user."
                )

    def assert_merge_allowed(self):
        self.ensure_one()
        self._check_policy()
        if not self.active or not self.approved or not self.non_production:
            raise AccessError("Merge target is not approved for controlled use.")
        return True


class DevRepository(models.Model):
    _inherit = "dev.repository"

    merge_target_ids = fields.One2many(
        "dev.git.merge.target", "repository_id", readonly=True
    )


class DevGitMergeApproval(models.Model):
    _name = "dev.git.merge.approval"
    _description = "Immutable Human Merge Approval"
    _order = "approved_at desc, id desc"

    work_item_id = fields.Many2one("dev.work.item", required=True, readonly=True)
    merge_request_work_item_id = fields.Many2one(
        "dev.work.item", required=True, readonly=True
    )
    workspace_id = fields.Many2one(
        "dev.execution.workspace", required=True, readonly=True
    )
    pr_record_id = fields.Many2one("dev.git.pr.record", required=True, readonly=True)
    target_id = fields.Many2one("dev.git.merge.target", required=True, readonly=True)
    repository_id = fields.Many2one("dev.repository", required=True, readonly=True)
    github_repository = fields.Char(required=True, readonly=True)
    pr_number = fields.Integer(required=True, readonly=True)
    pr_url_reference = fields.Char(required=True, readonly=True)
    requester_id = fields.Many2one("res.users", required=True, readonly=True)
    approver_id = fields.Many2one("res.users", required=True, readonly=True)
    requested_at = fields.Datetime(required=True, readonly=True)
    head_branch = fields.Char(required=True, readonly=True)
    head_sha = fields.Char(required=True, readonly=True)
    base_branch = fields.Char(required=True, readonly=True)
    base_sha = fields.Char(required=True, readonly=True)
    merge_method = fields.Char(required=True, readonly=True)
    pr_metadata_digest = fields.Char(required=True, readonly=True)
    checks_digest = fields.Char(required=True, readonly=True)
    checks_summary = fields.Text(required=True, readonly=True)
    github_app_id = fields.Integer(required=True, readonly=True)
    github_installation_id = fields.Integer(required=True, readonly=True)
    credential_validation_digest = fields.Char(required=True, readonly=True)
    plan_id = fields.Many2one("dev.work.plan", required=True, readonly=True)
    plan_hash = fields.Char(required=True, readonly=True)
    policy_hash = fields.Char(required=True, readonly=True)
    execution_contract_hash = fields.Char(required=True, readonly=True)
    approved_at = fields.Datetime(required=True, readonly=True)
    idempotency_key = fields.Char(required=True, readonly=True, index=True)
    binding_hash = fields.Char(required=True, readonly=True, copy=False)
    event_ids = fields.One2many(
        "dev.git.merge.approval.event", "approval_id", readonly=True
    )

    def _binding(self):
        self.ensure_one()
        names = (
            "work_item_id",
            "merge_request_work_item_id",
            "workspace_id",
            "pr_record_id",
            "target_id",
            "repository_id",
            "github_repository",
            "pr_number",
            "pr_url_reference",
            "requester_id",
            "approver_id",
            "requested_at",
            "head_branch",
            "head_sha",
            "base_branch",
            "base_sha",
            "merge_method",
            "pr_metadata_digest",
            "checks_digest",
            "github_app_id",
            "github_installation_id",
            "credential_validation_digest",
            "plan_id",
            "plan_hash",
            "policy_hash",
            "execution_contract_hash",
            "approved_at",
            "idempotency_key",
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
                raise AccessError("Merge approval integrity validation failed.")
        return True

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("dev_git_merge_approval"):
            raise AccessError("Merge approvals require guarded human review.")
        records = super().create(vals_list)
        for record in records:
            super(DevGitMergeApproval, record).write(
                {"binding_hash": _canonical_hash(record._binding())}
            )
        return records.with_context(dev_git_merge_approval=False)

    def write(self, values):
        raise AccessError("Merge approvals are immutable.")

    def unlink(self):
        raise AccessError("Merge approvals are retained for audit.")

    def copy(self, default=None):
        raise AccessError("Merge approvals cannot be copied.")


class DevGitMergeApprovalEvent(models.Model):
    _name = "dev.git.merge.approval.event"
    _description = "Immutable Merge Approval Event"

    approval_id = fields.Many2one(
        "dev.git.merge.approval", required=True, readonly=True
    )
    event_type = fields.Selection(
        [
            ("consumed", "Consumed"),
            ("reconciled_success", "Reconciled Success"),
            ("merge_failed_review", "Merge Failed — Review Required"),
            ("uncertain_remote_state", "Uncertain Remote State"),
            ("rejected", "Rejected"),
        ],
        required=True,
        readonly=True,
    )
    occurred_at = fields.Datetime(
        default=fields.Datetime.now, required=True, readonly=True
    )
    actor_id = fields.Many2one("res.users", required=True, readonly=True)
    summary = fields.Char(required=True, readonly=True)
    payload_json = fields.Text(readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("dev_git_merge_event"):
            raise AccessError("Merge events require a guarded action.")
        return super().create(vals_list).with_context(dev_git_merge_event=False)

    def write(self, values):
        raise AccessError("Merge events are immutable.")

    def unlink(self):
        raise AccessError("Merge events are retained for audit.")

    def copy(self, default=None):
        raise AccessError("Merge events cannot be copied.")


class DevGitMergeRecord(models.Model):
    _name = "dev.git.merge.record"
    _description = "Immutable Controlled Merge Record"
    _order = "merged_at desc, id desc"

    work_item_id = fields.Many2one("dev.work.item", required=True, readonly=True)
    merge_request_work_item_id = fields.Many2one(
        "dev.work.item", required=True, readonly=True
    )
    workspace_id = fields.Many2one(
        "dev.execution.workspace", required=True, readonly=True
    )
    approval_id = fields.Many2one(
        "dev.git.merge.approval", required=True, readonly=True
    )
    github_repository = fields.Char(required=True, readonly=True)
    pr_number = fields.Integer(required=True, readonly=True)
    pr_url_reference = fields.Char(required=True, readonly=True)
    requester_id = fields.Many2one("res.users", required=True, readonly=True)
    approver_id = fields.Many2one("res.users", required=True, readonly=True)
    approved_head_sha = fields.Char(required=True, readonly=True)
    base_branch = fields.Char(required=True, readonly=True)
    approved_base_sha = fields.Char(required=True, readonly=True)
    merge_method = fields.Char(required=True, readonly=True)
    result_state = fields.Selection(
        [
            ("merged", "Merged"),
            ("reconciled_success", "Reconciled Success"),
            ("merge_failed_review", "Merge Failed — Review Required"),
            ("uncertain_remote_state", "Uncertain Remote State"),
        ],
        required=True,
        readonly=True,
    )
    merge_sha = fields.Char(readonly=True)
    remote_result = fields.Text(required=True, readonly=True)
    requested_at = fields.Datetime(required=True, readonly=True)
    approved_at = fields.Datetime(required=True, readonly=True)
    merged_at = fields.Datetime(required=True, readonly=True)
    idempotency_key = fields.Char(required=True, readonly=True, index=True)
    api_correlation_reference = fields.Char(required=True, readonly=True)
    audit_hash = fields.Char(required=True, readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("dev_git_merge_record"):
            raise AccessError("Merge records require guarded creation.")
        for values in vals_list:
            values.setdefault("audit_hash", "pending")
        records = super().create(vals_list)
        for record in records:
            payload = {
                name: record[name].id
                if record._fields[name].type == "many2one"
                else fields.Datetime.to_string(record[name])
                if record._fields[name].type == "datetime"
                else record[name] or ""
                for name in (
                    "work_item_id",
                    "merge_request_work_item_id",
                    "workspace_id",
                    "approval_id",
                    "github_repository",
                    "pr_number",
                    "pr_url_reference",
                    "requester_id",
                    "approver_id",
                    "approved_head_sha",
                    "base_branch",
                    "approved_base_sha",
                    "merge_method",
                    "result_state",
                    "merge_sha",
                    "remote_result",
                    "requested_at",
                    "approved_at",
                    "merged_at",
                    "idempotency_key",
                    "api_correlation_reference",
                )
            }
            super(DevGitMergeRecord, record).write(
                {"audit_hash": _canonical_hash(payload)}
            )
        return records.with_context(dev_git_merge_record=False)

    def write(self, values):
        raise AccessError("Merge records are immutable.")

    def unlink(self):
        raise AccessError("Merge records are retained for audit.")

    def copy(self, default=None):
        raise AccessError("Merge records cannot be copied.")


class DevExecutionWorkspace(models.Model):
    _inherit = "dev.execution.workspace"

    merge_target_id = fields.Many2one("dev.git.merge.target", readonly=True)
    merge_request_work_item_id = fields.Many2one("dev.work.item", readonly=True)
    merge_requester_id = fields.Many2one("res.users", readonly=True)
    merge_requested_at = fields.Datetime(readonly=True)
    merge_pr_number = fields.Integer(readonly=True)
    merge_pr_url = fields.Char(readonly=True)
    merge_head_branch = fields.Char(readonly=True)
    merge_head_sha = fields.Char(readonly=True)
    merge_base_branch = fields.Char(readonly=True)
    merge_base_sha = fields.Char(readonly=True)
    merge_method = fields.Char(readonly=True)
    merge_checks_summary = fields.Text(readonly=True)
    merge_checks_digest = fields.Char(readonly=True)
    merge_pr_metadata_digest = fields.Char(readonly=True)
    merge_last_checked_at = fields.Datetime(readonly=True)
    merge_approval_id = fields.Many2one("dev.git.merge.approval", readonly=True)
    merge_record_id = fields.Many2one("dev.git.merge.record", readonly=True)
    merge_result_sha = fields.Char(readonly=True)
    merged_at = fields.Datetime(readonly=True)

    def _require_merge_manager(self):
        if not self.env.user.has_group("dev_session_hub.group_dev_hub_manager"):
            raise AccessError("Only a Dev Hub manager may authorize a merge.")

    def _prepare_merge_credential(self, target):
        broker = os.path.realpath(target.credential_broker_reference or "")
        if not broker.startswith("/srv/devhub/credentials/github/"):
            raise AccessError("Merge credential broker escaped the protected root.")
        try:
            result = subprocess.run(
                [broker],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
                check=False,
                env={
                    "PATH": "/usr/bin:/bin",
                    "HOME": "/nonexistent",
                    "GH_CONFIG_DIR": target.credential_profile_reference,
                    "DEVHUB_GITHUB_APP_ID": str(target.github_app_id),
                    "DEVHUB_GITHUB_INSTALLATION_ID": str(
                        target.github_installation_id
                    ),
                    "DEVHUB_GITHUB_REPOSITORY": target.github_repository,
                    "LANG": "C",
                },
            )
        except (OSError, subprocess.TimeoutExpired):
            raise UserError("Protected Merge App broker is unavailable.")
        if result.returncode or len(result.stdout) > 4096:
            raise UserError("Protected Merge App broker failed safely.")
        try:
            metadata = json.loads(result.stdout.decode())
            expires_at = fields.Datetime.to_datetime(
                str(metadata["expires_at"]).replace("T", " ").replace("Z", "")
            )
        except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
            raise UserError("Merge App broker returned invalid sanitized metadata.")
        if (
            metadata.get("credential_type") != "github_app_installation"
            or metadata.get("app_id") != target.github_app_id
            or metadata.get("installation_id") != target.github_installation_id
            or metadata.get("permissions") != MERGE_PERMISSIONS
            or metadata.get("repositories") != [target.github_repository]
            or expires_at <= fields.Datetime.now() + timedelta(minutes=5)
            or expires_at > fields.Datetime.now() + timedelta(hours=2)
            or any(key in metadata for key in ("token", "private_key", "authorization"))
        ):
            raise AccessError("Merge credential exceeds exact policy.")
        return expires_at

    def _run_merge_gh(self, target, args, input_payload=None, check=True):
        self.ensure_one()
        target.assert_merge_allowed()
        repo = re.escape(target.github_repository)
        endpoints = [arg for arg in args if arg.startswith(("repos/", "apps/", "installation/"))]
        if len(endpoints) != 1:
            raise AccessError("Merge GitHub operation escaped registered scope.")
        endpoint = endpoints[0]
        number = self.pr_number or self.merge_pr_number
        pull = "repos/%s/pulls/%s" % (target.github_repository, number)
        allowed_get = (
            endpoint == "repos/%s" % target.github_repository
            or endpoint == "apps/%s" % target.github_app_slug
            or endpoint == "installation/repositories?per_page=100"
            or endpoint == pull
            or endpoint == pull + "/merge"
            or bool(re.fullmatch(r"repos/%s/git/ref/heads/.+" % repo, endpoint))
            or bool(re.fullmatch(r"repos/%s/commits/[0-9a-f]{40}/check-runs\?filter=latest&per_page=100" % repo, endpoint))
            or bool(re.fullmatch(r"repos/%s/commits/[0-9a-f]{40}/status" % repo, endpoint))
            or bool(re.fullmatch(r"repos/%s/rules/branches/.+\?includes_parents=true&per_page=100" % repo, endpoint))
        )
        merge_args = ["-X", "PUT", pull + "/merge", "--input", "-"]
        if "-X" in args:
            if (
                args != merge_args
                or not isinstance(input_payload, dict)
                or set(input_payload)
                != {"sha", "merge_method", "commit_title", "commit_message"}
                or input_payload["merge_method"] != MERGE_METHOD
                or not SHA1_RE.fullmatch(input_payload["sha"] or "")
            ):
                raise AccessError("Only the exact approved squash merge is permitted.")
        elif not (
            (len(args) == 1 and allowed_get)
            or args == ["-i", "repos/%s" % target.github_repository]
        ) or input_payload is not None:
            raise AccessError("Merge GitHub operation escaped registered scope.")
        try:
            result = subprocess.run(
                ["gh", "api", *args],
                input=(
                    json.dumps(input_payload, sort_keys=True).encode()
                    if input_payload is not None
                    else None
                ),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=60,
                check=False,
                env={
                    "PATH": "/usr/bin:/bin",
                    "HOME": "/nonexistent",
                    "GH_CONFIG_DIR": target.credential_profile_reference,
                    "GH_PROMPT_DISABLED": "1",
                    "GIT_TERMINAL_PROMPT": "0",
                    "LANG": "C",
                },
            )
        except (OSError, subprocess.TimeoutExpired):
            raise UserError("GitHub Merge API identity is unavailable.")
        if check and result.returncode:
            raise UserError("GitHub Merge API operation failed safely.")
        return result

    def _merge_json(self, target, args):
        result = self._run_merge_gh(target, args)
        try:
            return json.loads(result.stdout.decode())
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise UserError("GitHub returned malformed Merge metadata.")

    def _assert_merge_identity(self, target):
        expires_at = self._prepare_merge_credential(target)
        repository = "repos/%s" % target.github_repository
        headers = self._run_merge_gh(target, ["-i", repository]).stdout.decode(
            errors="replace"
        )
        scopes = re.search(r"(?im)^x-oauth-scopes:[ \t]*(.*)$", headers)
        if scopes and scopes.group(1).strip():
            raise AccessError("Classic broad GitHub OAuth credentials are forbidden.")
        app = self._merge_json(target, ["apps/%s" % target.github_app_slug])
        permissions = {
            key: value
            for key, value in (app.get("permissions") or {}).items()
            if value not in (None, "none")
        }
        repositories = self._merge_json(
            target, ["installation/repositories?per_page=100"]
        )
        names = sorted(
            item.get("full_name")
            for item in repositories.get("repositories", [])
            if item.get("full_name")
        )
        if (
            app.get("id") != target.github_app_id
            or app.get("slug") != target.github_app_slug
            or permissions != MERGE_PERMISSIONS
            or repositories.get("total_count") != 1
            or names != [target.github_repository]
        ):
            raise AccessError("Merge App identity or access exceeds exact policy.")
        digest = _canonical_hash(
            {
                "app_id": target.github_app_id,
                "installation_id": target.github_installation_id,
                "repository": target.github_repository,
                "permissions": MERGE_PERMISSIONS,
            }
        )
        target.sudo().write(
            {
                "credential_expires_at": expires_at,
                "credential_validated_at": fields.Datetime.now(),
                "credential_validation_digest": digest,
            }
        )
        return True

    def _merge_preflight(self, target):
        self.ensure_one()
        self._require_merge_manager()
        if self.state not in ("pr_created_reviewed", "merge_approved"):
            raise AccessError("Merge requires a reviewed created PR.")
        self._assert_no_worker_lease()
        self._assert_plan_unchanged()
        self.environment_id._assert_dev_hub_safe(self.project_id)
        if (
            not self.pr_record_id
            or self.pr_record_id.result_state
            not in ("created", "reconciled_existing")
            or self.pr_number <= 0
        ):
            raise AccessError("Merge requires one verified PR creation record.")
        if (
            self.merge_target_id != target
            or self.merge_requester_id != target.requester_user_id
            or not self.merge_requested_at
        ):
            raise AccessError(
                "A current request from the dedicated Merge service user is required."
            )
        target.assert_merge_allowed()
        self._assert_merge_identity(target)
        metadata = self._merge_json(
            target,
            ["repos/%s/pulls/%s" % (target.github_repository, self.pr_number)],
        )
        expected_url = "https://github.com/%s/pull/%s" % (
            target.github_repository,
            self.pr_number,
        )
        if (
            metadata.get("html_url") != expected_url
            or metadata.get("state") != "open"
            or metadata.get("merged") is not False
            or metadata.get("draft") is not False
            or metadata.get("auto_merge") is not None
            or metadata.get("head", {}).get("ref") != self.pr_record_id.source_branch
            or metadata.get("head", {}).get("sha") != self.pr_record_id.source_sha
            or metadata.get("base", {}).get("ref") != "staging"
            or metadata.get("head", {}).get("repo", {}).get("full_name")
            != target.github_repository
            or metadata.get("base", {}).get("repo", {}).get("full_name")
            != target.github_repository
            or metadata.get("mergeable") is not True
            or metadata.get("mergeable_state") not in ("clean", "unstable")
        ):
            raise AccessError("PR is not eligible for the exact approved merge.")
        head_sha = metadata["head"]["sha"]
        base_ref = self._merge_json(
            target,
            [
                "repos/%s/git/ref/heads/%s"
                % (target.github_repository, quote("staging", safe=""))
            ],
        )
        base_sha = base_ref.get("object", {}).get("sha")
        if not SHA1_RE.fullmatch(base_sha or ""):
            raise UserError("GitHub returned an invalid staging base SHA.")
        rules = self._merge_json(
            target,
            [
                "repos/%s/rules/branches/%s?includes_parents=true&per_page=100"
                % (target.github_repository, quote("staging", safe=""))
            ],
        )
        if not isinstance(rules, list):
            raise UserError("Repository merge rules could not be determined.")
        unsupported = {
            item.get("type")
            for item in rules
            if item.get("type")
            not in (None, "required_status_checks", "pull_request", "non_fast_forward")
        }
        if unsupported:
            raise AccessError("Repository merge rules include unsupported blockers.")
        checks = self._merge_json(
            target,
            [
                "repos/%s/commits/%s/check-runs?filter=latest&per_page=100"
                % (target.github_repository, head_sha)
            ],
        )
        runs = checks.get("check_runs") if isinstance(checks, dict) else None
        if not isinstance(runs, list) or checks.get("total_count") != len(runs):
            raise UserError("Required check runs could not be determined exactly.")
        required = [
            run
            for run in runs
            if run.get("name") == target.required_check_name
            and run.get("app", {}).get("id") == target.required_check_app_id
        ]
        if (
            len(required) != 1
            or required[0].get("status") != "completed"
            or required[0].get("conclusion") != "success"
            or any(
                run.get("status") != "completed"
                or run.get("conclusion") not in SAFE_CHECK_CONCLUSIONS
                for run in runs
            )
        ):
            raise AccessError("Required CI/check status is not successful.")
        status = self._merge_json(
            target,
            [
                "repos/%s/commits/%s/status"
                % (target.github_repository, head_sha)
            ],
        )
        statuses = status.get("statuses") if isinstance(status, dict) else None
        if not isinstance(statuses, list) or any(
            item.get("state") != "success" for item in statuses
        ):
            raise AccessError("Required commit status is pending or failed.")
        check_payload = [
            {
                "name": run.get("name"),
                "app_id": run.get("app", {}).get("id"),
                "status": run.get("status"),
                "conclusion": run.get("conclusion"),
            }
            for run in runs
        ]
        pr_payload = {
            "repository": target.github_repository,
            "number": self.pr_number,
            "url": expected_url,
            "head_branch": metadata["head"]["ref"],
            "head_sha": head_sha,
            "base_branch": metadata["base"]["ref"],
            "base_sha": base_sha,
            "draft": metadata["draft"],
            "mergeable": metadata["mergeable"],
            "mergeable_state": metadata["mergeable_state"],
        }
        return {
            **pr_payload,
            "pr_metadata_digest": _canonical_hash(pr_payload),
            "checks_digest": _canonical_hash(check_payload),
            "checks_summary": json.dumps(check_payload, sort_keys=True),
        }

    def action_request_merge_review(self):
        self.ensure_one()
        if self.state != "pr_created_reviewed":
            raise AccessError("Merge review may be requested only for a reviewed PR.")
        targets = self.repository_id.merge_target_ids.filtered(
            lambda item: item.active and item.approved and item.non_production
        )
        if len(targets) != 1:
            raise UserError("Exactly one approved Merge target is required.")
        target = targets
        target.assert_merge_allowed()
        if self.env.user != target.requester_user_id:
            raise AccessError(
                "Only the configured dedicated Merge service user may request review."
            )
        if (
            not self.pr_record_id
            or self.pr_record_id.result_state
            not in ("created", "reconciled_existing")
        ):
            raise AccessError("Merge review requires one verified PR record.")
        request_work = self.merge_request_work_item_id or self.work_item_id
        self.sudo()._internal_write(
            {
                "merge_target_id": target.id,
                "merge_request_work_item_id": request_work.id,
                "merge_requester_id": self.env.user.id,
                "merge_requested_at": fields.Datetime.now(),
            }
        )
        self._event(
            "merge_requested",
            "Dedicated service user requested human Merge review",
        )
        return self._form_action()

    def action_review_merge_eligibility(self):
        self.ensure_one()
        target = self.merge_target_id
        snapshot = self._merge_preflight(target)
        self.sudo()._internal_write(
            {
                "merge_pr_number": snapshot["number"],
                "merge_pr_url": snapshot["url"],
                "merge_head_branch": snapshot["head_branch"],
                "merge_head_sha": snapshot["head_sha"],
                "merge_base_branch": snapshot["base_branch"],
                "merge_base_sha": snapshot["base_sha"],
                "merge_method": MERGE_METHOD,
                "merge_checks_summary": snapshot["checks_summary"],
                "merge_checks_digest": snapshot["checks_digest"],
                "merge_pr_metadata_digest": snapshot["pr_metadata_digest"],
                "merge_last_checked_at": fields.Datetime.now(),
            }
        )
        self._event("merge_reviewed", "Human reviewed exact merge eligibility")
        return self._form_action()

    def action_open_merge_approval(self):
        self.ensure_one()
        self.action_review_merge_eligibility()
        return {
            "type": "ir.actions.act_window",
            "name": "Approve Exact Squash Merge",
            "res_model": "dev.git.merge.approval.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_workspace_id": self.id,
                "default_target_id": self.merge_target_id.id,
            },
        }

    def create_merge_approval(self, target):
        self.ensure_one()
        if self.state != "pr_created_reviewed":
            raise AccessError("Fresh Merge approval requires PR Created Reviewed state.")
        snapshot = self._merge_preflight(target)
        requester = target.requester_user_id
        if requester == self.env.user:
            raise AccessError("Merge requester cannot approve the same merge.")
        idempotency_key = _canonical_hash(
            {
                "repository": target.github_repository,
                "pr_number": self.pr_number,
                "head_sha": snapshot["head_sha"],
                "base_sha": snapshot["base_sha"],
                "method": MERGE_METHOD,
            }
        )
        if self.env["dev.git.merge.record"].sudo().search_count(
            [("idempotency_key", "=", idempotency_key)]
        ):
            raise AccessError("This exact merge has already reached a terminal result.")
        request_work = self.merge_request_work_item_id or self.work_item_id
        approval = self.env["dev.git.merge.approval"].sudo().with_context(
            dev_git_merge_approval=True
        ).create(
            {
                "work_item_id": self.work_item_id.id,
                "merge_request_work_item_id": request_work.id,
                "workspace_id": self.id,
                "pr_record_id": self.pr_record_id.id,
                "target_id": target.id,
                "repository_id": self.repository_id.id,
                "github_repository": target.github_repository,
                "pr_number": self.pr_number,
                "pr_url_reference": snapshot["url"],
                "requester_id": requester.id,
                "approver_id": self.env.user.id,
                "requested_at": self.merge_requested_at,
                "head_branch": snapshot["head_branch"],
                "head_sha": snapshot["head_sha"],
                "base_branch": snapshot["base_branch"],
                "base_sha": snapshot["base_sha"],
                "merge_method": MERGE_METHOD,
                "pr_metadata_digest": snapshot["pr_metadata_digest"],
                "checks_digest": snapshot["checks_digest"],
                "checks_summary": snapshot["checks_summary"],
                "github_app_id": target.github_app_id,
                "github_installation_id": target.github_installation_id,
                "credential_validation_digest": target.credential_validation_digest,
                "plan_id": self.plan_id.id,
                "plan_hash": self.approved_plan_hash,
                "policy_hash": self.policy_hash,
                "execution_contract_hash": self.execution_contract_hash,
                "approved_at": fields.Datetime.now(),
                "idempotency_key": idempotency_key,
                "binding_hash": "pending",
            }
        )
        self.sudo()._internal_write(
            {"state": "merge_approved", "merge_approval_id": approval.id}
        )
        self._event("merge_approved", "Distinct Administrator approved exact squash merge")
        return approval

    def _assert_merge_approval_current(self, approval):
        self.ensure_one()
        if self.state != "merge_approved" or self.merge_approval_id != approval:
            raise AccessError("A current immutable Merge approval is required.")
        if approval.event_ids:
            raise AccessError("Merge approval was already consumed or invalidated.")
        approval.assert_integrity()
        if approval.requester_id == approval.approver_id:
            raise AccessError("Self-approved merges are forbidden.")
        snapshot = self._merge_preflight(approval.target_id)
        expected = {
            "repository": (snapshot["repository"], approval.github_repository),
            "PR": (snapshot["number"], approval.pr_number),
            "head branch": (snapshot["head_branch"], approval.head_branch),
            "head SHA": (snapshot["head_sha"], approval.head_sha),
            "base branch": (snapshot["base_branch"], approval.base_branch),
            "base SHA": (snapshot["base_sha"], approval.base_sha),
            "PR metadata": (
                snapshot["pr_metadata_digest"],
                approval.pr_metadata_digest,
            ),
            "checks": (snapshot["checks_digest"], approval.checks_digest),
            "Plan": (self.plan_id.id, approval.plan_id.id),
            "Plan hash": (self.approved_plan_hash, approval.plan_hash),
            "policy": (self.policy_hash, approval.policy_hash),
            "contract": (
                self.execution_contract_hash,
                approval.execution_contract_hash,
            ),
            "credential": (
                approval.target_id.credential_validation_digest,
                approval.credential_validation_digest,
            ),
        }
        drift = [name for name, values in expected.items() if values[0] != values[1]]
        if drift:
            raise AccessError(
                "Merge approval is stale; fresh review required (%s)."
                % ", ".join(drift)
            )
        return True

    def action_open_merge_execution(self):
        self.ensure_one()
        self._assert_merge_approval_current(self.merge_approval_id)
        return {
            "type": "ir.actions.act_window",
            "name": "Final Irreversible Merge Confirmation",
            "res_model": "dev.git.merge.execution.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_workspace_id": self.id,
                "default_approval_id": self.merge_approval_id.id,
            },
        }

    def _record_merge_result(self, approval, result_state, merge_sha=False):
        now = fields.Datetime.now()
        messages = {
            "merged": "Exact squash merge verified remotely.",
            "reconciled_success": "Merge delivery reconciled and verified remotely.",
            "merge_failed_review": "PR remains open after failed merge; human review required.",
            "uncertain_remote_state": "Merge state is uncertain; retry blocked.",
        }
        correlation = _canonical_hash(
            {
                "idempotency_key": approval.idempotency_key,
                "approved_at": fields.Datetime.to_string(approval.approved_at),
            }
        )
        record = self.env["dev.git.merge.record"].sudo().with_context(
            dev_git_merge_record=True
        ).create(
            {
                "work_item_id": self.work_item_id.id,
                "merge_request_work_item_id": approval.merge_request_work_item_id.id,
                "workspace_id": self.id,
                "approval_id": approval.id,
                "github_repository": approval.github_repository,
                "pr_number": approval.pr_number,
                "pr_url_reference": approval.pr_url_reference,
                "requester_id": approval.requester_id.id,
                "approver_id": approval.approver_id.id,
                "approved_head_sha": approval.head_sha,
                "base_branch": approval.base_branch,
                "approved_base_sha": approval.base_sha,
                "merge_method": approval.merge_method,
                "result_state": result_state,
                "merge_sha": merge_sha,
                "remote_result": messages[result_state],
                "requested_at": approval.requested_at,
                "approved_at": approval.approved_at,
                "merged_at": now,
                "idempotency_key": approval.idempotency_key,
                "api_correlation_reference": correlation,
                "audit_hash": "pending",
            }
        )
        event = "consumed" if result_state == "merged" else result_state
        self.env["dev.git.merge.approval.event"].sudo().with_context(
            dev_git_merge_event=True
        ).create(
            {
                "approval_id": approval.id,
                "event_type": event,
                "actor_id": self.env.user.id,
                "summary": messages[result_state],
                "payload_json": json.dumps(
                    {"result": result_state, "merge_sha": merge_sha or ""},
                    sort_keys=True,
                ),
            }
        )
        state = (
            "merged_reviewed"
            if result_state in ("merged", "reconciled_success")
            else "merge_failed_review"
            if result_state == "merge_failed_review"
            else "merge_uncertain_state"
        )
        self.sudo()._internal_write(
            {
                "state": state,
                "merge_record_id": record.id,
                "merge_result_sha": merge_sha,
                "merged_at": now,
            }
        )
        self._event("merge_%s" % result_state, messages[result_state])
        return record

    def _reconcile_merge(self, approval):
        try:
            metadata = self._merge_json(
                approval.target_id,
                [
                    "repos/%s/pulls/%s"
                    % (approval.github_repository, approval.pr_number)
                ],
            )
        except Exception:
            return self._record_merge_result(
                approval, "uncertain_remote_state"
            )
        merge_sha = metadata.get("merge_commit_sha")
        if (
            metadata.get("merged") is True
            and metadata.get("state") == "closed"
            and SHA1_RE.fullmatch(merge_sha or "")
            and metadata.get("head", {}).get("sha") == approval.head_sha
            and metadata.get("base", {}).get("ref") == approval.base_branch
        ):
            return self._record_merge_result(
                approval, "reconciled_success", merge_sha
            )
        if (
            metadata.get("merged") is False
            and metadata.get("state") == "open"
            and metadata.get("head", {}).get("sha") == approval.head_sha
        ):
            return self._record_merge_result(approval, "merge_failed_review")
        return self._record_merge_result(approval, "uncertain_remote_state")

    def execute_approved_merge(self, approval):
        self.ensure_one()
        self.env.cr.execute(
            "SELECT id FROM dev_execution_workspace WHERE id = %s FOR UPDATE NOWAIT",
            [self.id],
        )
        self._assert_merge_approval_current(approval)
        if self.env["dev.git.merge.record"].sudo().search_count(
            [("idempotency_key", "=", approval.idempotency_key)]
        ):
            raise AccessError("Duplicate or replayed merge execution is denied.")
        payload = {
            "sha": approval.head_sha,
            "merge_method": MERGE_METHOD,
            "commit_title": "[DW-%s] %s"
            % (
                approval.merge_request_work_item_id.id,
                approval.merge_request_work_item_id.name,
            ),
            "commit_message": "Human-approved squash merge of PR #%s."
            % approval.pr_number,
        }
        result = self._run_merge_gh(
            approval.target_id,
            [
                "-X",
                "PUT",
                "repos/%s/pulls/%s/merge"
                % (approval.github_repository, approval.pr_number),
                "--input",
                "-",
            ],
            input_payload=payload,
            check=False,
        )
        if result.returncode:
            return self._reconcile_merge(approval)
        try:
            response = json.loads(result.stdout.decode())
            merge_sha = response["sha"]
            if response.get("merged") is not True or not SHA1_RE.fullmatch(merge_sha):
                raise ValueError
            metadata = self._merge_json(
                approval.target_id,
                [
                    "repos/%s/pulls/%s"
                    % (approval.github_repository, approval.pr_number)
                ],
            )
            base = self._merge_json(
                approval.target_id,
                [
                    "repos/%s/git/ref/heads/%s"
                    % (
                        approval.github_repository,
                        quote(approval.base_branch, safe=""),
                    )
                ],
            )
            if (
                metadata.get("merged") is not True
                or metadata.get("state") != "closed"
                or metadata.get("merge_commit_sha") != merge_sha
                or metadata.get("head", {}).get("sha") != approval.head_sha
                or base.get("object", {}).get("sha") != merge_sha
            ):
                raise ValueError
        except (
            KeyError,
            TypeError,
            ValueError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            UserError,
        ):
            return self._reconcile_merge(approval)
        return self._record_merge_result(approval, "merged", merge_sha)

    def action_reject_merge(self):
        self.ensure_one()
        self._require_merge_manager()
        if self.state not in ("pr_created_reviewed", "merge_approved"):
            raise AccessError("Only a pending Merge proposal may be rejected.")
        if self.merge_approval_id and not self.merge_approval_id.event_ids:
            self.env["dev.git.merge.approval.event"].sudo().with_context(
                dev_git_merge_event=True
            ).create(
                {
                    "approval_id": self.merge_approval_id.id,
                    "event_type": "rejected",
                    "actor_id": self.env.user.id,
                    "summary": "Human rejected Merge proposal.",
                }
            )
        self.sudo()._internal_write(
            {"state": "pr_created_reviewed", "merge_approval_id": False}
        )
        self._event("merge_rejected", "Human rejected Merge proposal")
        return self._form_action()
