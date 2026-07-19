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

from .dev_execution import BRANCH_RE, SHA1_RE
from .dev_git_commit import _canonical_hash


GITHUB_REPOSITORY_RE = re.compile(
    r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$"
)
GITHUB_APP_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,98}[a-z0-9])?$")
REQUIRED_APP_PERMISSIONS = {
    "contents": "read",
    "metadata": "read",
    "pull_requests": "write",
}
TARGET_BRANCH_RE = re.compile(
    r"^(?![./])(?!.*(?:\.\.|//|@\{|\\))[A-Za-z0-9._/-]{1,200}(?<![./])$"
)
SECRET_TEXT_RE = re.compile(
    r"(?i)(access[_-]?token|api[_-]?key|password|authorization|bearer)"
    r"\s*[:=]\s*\S+"
)
FORBIDDEN_TARGETS = {"main", "master", "production", "prod"}
FORBIDDEN_TARGET_PREFIXES = ("release/", "production/", "prod/")


def _safe_pr_text(value, label, limit):
    text = (value or "").replace("\x00", "").strip()
    if not text or len(text) > limit:
        raise ValidationError("%s is missing or exceeds its safe limit." % label)
    if SECRET_TEXT_RE.search(text):
        raise ValidationError("%s contains credential-like content." % label)
    return text


class DevGitPullRequestTarget(models.Model):
    _name = "dev.git.pr.target"
    _description = "Registered Pull Request Target"
    _order = "repository_id, github_repository, target_branch"

    name = fields.Char(required=True)
    repository_id = fields.Many2one(
        "dev.repository", required=True, ondelete="restrict", index=True
    )
    source_remote_id = fields.Many2one(
        "dev.git.remote", required=True, ondelete="restrict"
    )
    target_repository_id = fields.Many2one(
        "dev.repository", required=True, ondelete="restrict"
    )
    github_repository = fields.Char(required=True)
    target_branch = fields.Char(required=True)
    allowed_target_branches = fields.Text(default="develop\ntest\nstaging", required=True)
    credential_profile_reference = fields.Char(required=True)
    credential_broker_reference = fields.Char(required=True)
    credential_type = fields.Selection(
        [
            ("github_app", "GitHub App Installation"),
            ("fine_grained_pat", "Fine-Grained Personal Access Token"),
        ],
        default="github_app",
        required=True,
    )
    github_app_slug = fields.Char()
    github_app_id = fields.Integer()
    github_installation_id = fields.Integer()
    credential_owner_reference = fields.Char(required=True, default="github-app")
    credential_repository_restriction = fields.Char(required=True)
    credential_permission_summary = fields.Text(
        required=True,
        default="contents:read\nmetadata:read\npull_requests:write",
    )
    credential_expires_at = fields.Datetime(readonly=True)
    credential_validated_at = fields.Datetime(readonly=True)
    credential_validation_digest = fields.Char(readonly=True)
    approved = fields.Boolean(default=False, required=True)
    non_production = fields.Boolean(default=True, required=True)
    active = fields.Boolean(default=True)

    _target_unique = models.Constraint(
        "unique(repository_id, source_remote_id, github_repository, target_branch)",
        "PR target registration must be unique.",
    )

    @api.constrains(
        "repository_id",
        "source_remote_id",
        "target_repository_id",
        "github_repository",
        "target_branch",
        "allowed_target_branches",
        "credential_profile_reference",
        "credential_broker_reference",
        "credential_type",
        "github_app_slug",
        "github_app_id",
        "github_installation_id",
        "credential_repository_restriction",
        "credential_permission_summary",
    )
    def _check_target_policy(self):
        for record in self:
            if record.source_remote_id.repository_id != record.repository_id:
                raise ValidationError("PR source remote belongs to another repository.")
            if not GITHUB_REPOSITORY_RE.fullmatch(record.github_repository or ""):
                raise ValidationError("GitHub repository reference must be owner/name.")
            if record.target_repository_id != record.repository_id:
                raise ValidationError(
                    "Cross-repository PRs are not enabled in this controlled phase."
                )
            record._assert_target_branch()
            profile = record.credential_profile_reference or ""
            broker = record.credential_broker_reference or ""
            if (
                not os.path.isabs(profile)
                or any(marker in profile.casefold() for marker in ("token=", "secret=", "\n"))
            ):
                raise ValidationError(
                    "GitHub credential profile must be a protected path reference."
                )
            if (
                not os.path.isabs(broker)
                or not os.path.realpath(broker).startswith(
                    "/srv/devhub/credentials/github/"
                )
                or any(marker in broker.casefold() for marker in ("token=", "secret=", "\n"))
            ):
                raise ValidationError(
                    "GitHub App broker must be a protected executable reference."
                )
            if record.credential_repository_restriction != record.github_repository:
                raise ValidationError(
                    "GitHub credential must be restricted to the registered repository."
                )
            expected_summary = "\n".join(
                "%s:%s" % item for item in sorted(REQUIRED_APP_PERMISSIONS.items())
            )
            if record.credential_permission_summary.strip() != expected_summary:
                raise ValidationError(
                    "GitHub credential permission declaration is not least-privileged."
                )
            if record.credential_type == "github_app":
                if (
                    not GITHUB_APP_SLUG_RE.fullmatch(record.github_app_slug or "")
                    or record.github_app_id <= 0
                    or record.github_installation_id <= 0
                ):
                    raise ValidationError(
                        "GitHub App slug, App ID, and installation ID are required."
                    )

    def _assert_target_branch(self):
        self.ensure_one()
        branch = self.target_branch or ""
        allowed = {
            line.strip()
            for line in (self.allowed_target_branches or "").splitlines()
            if line.strip()
        }
        lowered = branch.casefold()
        if (
            not TARGET_BRANCH_RE.fullmatch(branch)
            or branch not in allowed
            or lowered in FORBIDDEN_TARGETS
            or lowered.startswith(FORBIDDEN_TARGET_PREFIXES)
        ):
            raise AccessError("PR target branch is not an approved integration branch.")
        return True

    def assert_pr_allowed(self, source_branch):
        self.ensure_one()
        self._check_target_policy()
        if not self.active or not self.approved or not self.non_production:
            raise AccessError("PR target is not approved for controlled non-production use.")
        self.source_remote_id.assert_push_allowed(source_branch)
        if not source_branch.startswith("devhub/"):
            raise AccessError("PR source must be a dedicated Dev Hub branch.")
        remote_url = self.source_remote_id.remote_url
        repository_path = self.github_repository + ".git"
        if not (
            remote_url.endswith("/" + repository_path)
            or remote_url.endswith(":" + repository_path)
        ):
            raise AccessError("Registered source remote does not match GitHub repository.")
        return True


class DevRepository(models.Model):
    _inherit = "dev.repository"

    pr_target_ids = fields.One2many(
        "dev.git.pr.target", "repository_id", readonly=True
    )


class DevGitPullRequestApproval(models.Model):
    _name = "dev.git.pr.approval"
    _description = "Immutable Human Pull Request Approval"
    _order = "approved_at desc, id desc"

    work_item_id = fields.Many2one("dev.work.item", required=True, readonly=True)
    workspace_id = fields.Many2one(
        "dev.execution.workspace", required=True, readonly=True
    )
    repository_id = fields.Many2one("dev.repository", required=True, readonly=True)
    source_remote_id = fields.Many2one("dev.git.remote", required=True, readonly=True)
    source_branch = fields.Char(required=True, readonly=True)
    source_commit_sha = fields.Char(required=True, readonly=True)
    target_repository_id = fields.Many2one(
        "dev.repository", required=True, readonly=True
    )
    target_id = fields.Many2one("dev.git.pr.target", required=True, readonly=True)
    github_repository = fields.Char(required=True, readonly=True)
    target_branch = fields.Char(required=True, readonly=True)
    credential_type = fields.Char(required=True, readonly=True)
    credential_owner_reference = fields.Char(required=True, readonly=True)
    github_app_id = fields.Integer(required=True, readonly=True)
    github_installation_id = fields.Integer(required=True, readonly=True)
    credential_validation_digest = fields.Char(required=True, readonly=True)
    pr_title = fields.Char(required=True, readonly=True)
    pr_title_hash = fields.Char(required=True, readonly=True)
    pr_body = fields.Text(required=True, readonly=True)
    pr_body_digest = fields.Char(required=True, readonly=True)
    plan_id = fields.Many2one("dev.work.plan", required=True, readonly=True)
    plan_hash = fields.Char(required=True, readonly=True)
    policy_hash = fields.Char(required=True, readonly=True)
    execution_contract_hash = fields.Char(required=True, readonly=True)
    approver_id = fields.Many2one("res.users", required=True, readonly=True)
    approved_at = fields.Datetime(required=True, readonly=True)
    idempotency_key = fields.Char(required=True, readonly=True, index=True)
    binding_hash = fields.Char(required=True, readonly=True, copy=False)
    event_ids = fields.One2many(
        "dev.git.pr.approval.event", "approval_id", readonly=True
    )
    approval_state = fields.Char(compute="_compute_state")

    @api.depends("event_ids.event_type")
    def _compute_state(self):
        for record in self:
            record.approval_state = (
                record.event_ids.sorted(lambda event: event.id, reverse=True)[:1].event_type
                if record.event_ids
                else "approved"
            )

    def _binding(self):
        self.ensure_one()
        names = (
            "work_item_id",
            "workspace_id",
            "repository_id",
            "source_remote_id",
            "source_branch",
            "source_commit_sha",
            "target_repository_id",
            "target_id",
            "github_repository",
            "target_branch",
            "credential_type",
            "credential_owner_reference",
            "github_app_id",
            "github_installation_id",
            "credential_validation_digest",
            "pr_title",
            "pr_title_hash",
            "pr_body_digest",
            "plan_id",
            "plan_hash",
            "policy_hash",
            "execution_contract_hash",
            "approver_id",
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
                raise AccessError("PR approval integrity validation failed.")
        return True

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("dev_git_pr_approval"):
            raise AccessError("PR approvals require guarded human review.")
        records = super().create(vals_list)
        for record in records:
            super(DevGitPullRequestApproval, record).write(
                {"binding_hash": _canonical_hash(record._binding())}
            )
        return records.with_context(dev_git_pr_approval=False)

    def write(self, values):
        raise AccessError("PR approvals are immutable.")

    def unlink(self):
        raise AccessError("PR approvals are retained for audit.")


class DevGitPullRequestApprovalEvent(models.Model):
    _name = "dev.git.pr.approval.event"
    _description = "Immutable Pull Request Approval Event"

    approval_id = fields.Many2one(
        "dev.git.pr.approval", required=True, readonly=True
    )
    event_type = fields.Selection(
        [
            ("consumed", "Consumed"),
            ("reconciled_existing", "Reconciled Existing"),
            ("creation_failed_review", "Creation Failed — Review Required"),
            ("uncertain_remote_state", "Uncertain Remote State"),
            ("rejected", "Rejected"),
        ],
        required=True,
        readonly=True,
    )
    occurred_at = fields.Datetime(default=fields.Datetime.now, required=True, readonly=True)
    actor_id = fields.Many2one("res.users", required=True, readonly=True)
    summary = fields.Char(required=True, readonly=True)
    payload_json = fields.Text(readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("dev_git_pr_event"):
            raise AccessError("PR approval events require a guarded action.")
        return super().create(vals_list).with_context(dev_git_pr_event=False)

    def write(self, values):
        raise AccessError("PR approval events are immutable.")

    def unlink(self):
        raise AccessError("PR approval events are retained for audit.")


class DevGitPullRequestRecord(models.Model):
    _name = "dev.git.pr.record"
    _description = "Immutable Pull Request Creation Record"
    _order = "created_at desc, id desc"

    work_item_id = fields.Many2one("dev.work.item", required=True, readonly=True)
    workspace_id = fields.Many2one(
        "dev.execution.workspace", required=True, readonly=True
    )
    approval_id = fields.Many2one(
        "dev.git.pr.approval", required=True, readonly=True
    )
    target_id = fields.Many2one("dev.git.pr.target", required=True, readonly=True)
    github_repository = fields.Char(required=True, readonly=True)
    source_branch = fields.Char(required=True, readonly=True)
    source_sha = fields.Char(required=True, readonly=True)
    target_branch = fields.Char(required=True, readonly=True)
    credential_type = fields.Char(required=True, readonly=True)
    credential_owner_reference = fields.Char(required=True, readonly=True)
    github_app_id = fields.Integer(required=True, readonly=True)
    github_installation_id = fields.Integer(required=True, readonly=True)
    credential_validation_digest = fields.Char(required=True, readonly=True)
    pr_title = fields.Char(required=True, readonly=True)
    pr_body_digest = fields.Char(required=True, readonly=True)
    pr_number = fields.Integer(readonly=True)
    pr_url_reference = fields.Char(readonly=True)
    approver_id = fields.Many2one("res.users", required=True, readonly=True)
    created_at = fields.Datetime(required=True, readonly=True)
    result_state = fields.Selection(
        [
            ("created", "Created"),
            ("reconciled_existing", "Reconciled Existing"),
            ("creation_failed_review", "Creation Failed — Review Required"),
            ("uncertain_remote_state", "Uncertain Remote State"),
        ],
        required=True,
        readonly=True,
    )
    verification_result = fields.Text(required=True, readonly=True)
    idempotency_key = fields.Char(required=True, readonly=True, index=True)
    api_correlation_reference = fields.Char(required=True, readonly=True)
    audit_hash = fields.Char(required=True, readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("dev_git_pr_record"):
            raise AccessError("PR records require guarded creation.")
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
                    "workspace_id",
                    "approval_id",
                    "target_id",
                    "github_repository",
                    "source_branch",
                    "source_sha",
                    "target_branch",
                    "credential_type",
                    "credential_owner_reference",
                    "github_app_id",
                    "github_installation_id",
                    "credential_validation_digest",
                    "pr_title",
                    "pr_body_digest",
                    "pr_number",
                    "pr_url_reference",
                    "approver_id",
                    "created_at",
                    "result_state",
                    "verification_result",
                    "idempotency_key",
                    "api_correlation_reference",
                )
            }
            super(DevGitPullRequestRecord, record).write(
                {"audit_hash": _canonical_hash(payload)}
            )
        return records.with_context(dev_git_pr_record=False)

    def write(self, values):
        raise AccessError("PR records are immutable.")

    def unlink(self):
        raise AccessError("PR records are retained for audit.")


class DevExecutionWorkspace(models.Model):
    _inherit = "dev.execution.workspace"

    pr_target_id = fields.Many2one("dev.git.pr.target", readonly=True)
    pr_source_branch = fields.Char(readonly=True)
    pr_source_sha = fields.Char(readonly=True)
    pr_target_branch = fields.Char(readonly=True)
    pr_commit_list = fields.Text(readonly=True)
    pr_title_preview = fields.Char(readonly=True)
    pr_body_preview = fields.Text(readonly=True)
    pr_body_digest = fields.Char(readonly=True)
    pr_last_checked_at = fields.Datetime(readonly=True)
    pr_approval_id = fields.Many2one("dev.git.pr.approval", readonly=True)
    pr_record_id = fields.Many2one("dev.git.pr.record", readonly=True)
    pr_number = fields.Integer(readonly=True)
    pr_url_reference = fields.Char(readonly=True)
    pr_created_at = fields.Datetime(readonly=True)

    def _require_pr_manager(self):
        if not self.env.user.has_group("dev_session_hub.group_dev_hub_manager"):
            raise AccessError("Only a Dev Hub manager may authorize PR creation.")

    def _run_gh(self, target, args, input_payload=None, check=True):
        self.ensure_one()
        if not target or target.repository_id != self.repository_id:
            raise AccessError("GitHub operation requires a registered PR target.")
        endpoints = [
            argument
            for argument in args
            if argument.startswith(("repos/", "apps/", "installation/"))
        ]
        if len(endpoints) != 1:
            raise AccessError("GitHub operation escaped the registered PR API scope.")
        endpoint = endpoints[0]
        pulls_root = "repos/%s/pulls" % target.github_repository
        ref_root = "repos/%s/git/ref/heads/" % target.github_repository
        repository_root = "repos/%s" % target.github_repository
        app_endpoint = "apps/%s" % target.github_app_slug
        installation_repositories = "installation/repositories?per_page=100"
        get_allowed = (
            endpoint == repository_root
            or endpoint == pulls_root
            or endpoint.startswith(pulls_root + "?")
            or bool(re.fullmatch(re.escape(pulls_root) + r"/[1-9][0-9]*", endpoint))
            or endpoint.startswith(ref_root)
            or endpoint == app_endpoint
            or endpoint == installation_repositories
        )
        if "-X" in args:
            if (
                args
                != ["-X", "POST", pulls_root, "--input", "-"]
                or not isinstance(input_payload, dict)
                or set(input_payload)
                != {
                    "title",
                    "head",
                    "base",
                    "body",
                    "draft",
                    "maintainer_can_modify",
                }
                or input_payload["draft"] is not False
                or input_payload["maintainer_can_modify"] is not False
            ):
                raise AccessError("Only one exact open-PR API request is permitted.")
        elif (
            not (
                (len(args) == 1 and get_allowed)
                or args == ["-i", repository_root]
            )
            or input_payload is not None
        ):
            raise AccessError("GitHub operation escaped the registered PR API scope.")
        command = ["gh", "api", *args]
        try:
            result = subprocess.run(
                command,
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
            raise UserError("GitHub PR service identity is unavailable.")
        if check and result.returncode:
            raise UserError("GitHub PR API operation failed safely.")
        return result

    def _prepare_github_app_credential(self, target):
        self.ensure_one()
        broker = os.path.realpath(target.credential_broker_reference or "")
        if not broker.startswith("/srv/devhub/credentials/github/"):
            raise AccessError("GitHub App broker escaped the protected credential root.")
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
            raise UserError("Protected GitHub App credential broker is unavailable.")
        if result.returncode or len(result.stdout) > 4096:
            raise UserError("Protected GitHub App credential broker failed safely.")
        try:
            metadata = json.loads(result.stdout.decode("utf-8"))
            expires_at = fields.Datetime.to_datetime(
                str(metadata["expires_at"]).replace("T", " ").replace("Z", "")
            )
        except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
            raise UserError("GitHub App broker returned invalid sanitized metadata.")
        permissions = metadata.get("permissions")
        repositories = metadata.get("repositories")
        now = fields.Datetime.now()
        if (
            metadata.get("credential_type") != "github_app_installation"
            or metadata.get("app_id") != target.github_app_id
            or metadata.get("installation_id") != target.github_installation_id
            or permissions != REQUIRED_APP_PERMISSIONS
            or repositories != [target.github_repository]
            or expires_at <= now + timedelta(minutes=5)
            or expires_at > now + timedelta(hours=2)
            or any(
                forbidden in metadata
                for forbidden in ("token", "private_key", "authorization")
            )
        ):
            raise AccessError(
                "GitHub App broker metadata exceeds the exact credential policy."
            )
        return expires_at

    def _assert_scoped_github_identity(self, target):
        self.ensure_one()
        if target.credential_type != "github_app":
            raise AccessError(
                "Fine-grained PAT permissions and all-repository reach cannot be "
                "introspected exactly; this controlled gate requires a GitHub App."
            )
        expires_at = self._prepare_github_app_credential(target)
        endpoint = "repos/%s" % target.github_repository
        result = self._run_gh(target, ["-i", endpoint])
        header_text = re.split(
            r"\r?\n\r?\n",
            result.stdout.decode("utf-8", errors="replace"),
            maxsplit=1,
        )[0]
        oauth_match = re.search(
            r"(?im)^x-oauth-scopes:[ \t]*(?P<scopes>[^\r\n]*)$", header_text
        )
        if oauth_match and oauth_match.group("scopes").strip():
            raise AccessError(
                "Classic broad GitHub OAuth scopes are forbidden."
            )
        now = fields.Datetime.now()
        app_metadata = self._github_json(
            target, ["apps/%s" % target.github_app_slug]
        )
        permissions = {
            name: level
            for name, level in (app_metadata.get("permissions") or {}).items()
            if level not in (None, "none")
        }
        if (
            app_metadata.get("id") != target.github_app_id
            or app_metadata.get("slug") != target.github_app_slug
            or permissions != REQUIRED_APP_PERMISSIONS
        ):
            raise AccessError(
                "GitHub App identity or repository permissions exceed approved policy."
            )
        repositories = self._github_json(
            target, ["installation/repositories?per_page=100"]
        )
        repository_names = sorted(
            item.get("full_name")
            for item in repositories.get("repositories", [])
            if item.get("full_name")
        )
        if (
            repositories.get("total_count") != 1
            or repository_names != [target.github_repository]
        ):
            raise AccessError(
                "GitHub App installation must access exactly one approved repository."
            )
        digest = _canonical_hash(
            {
                "credential_type": target.credential_type,
                "app_slug": target.github_app_slug,
                "app_id": target.github_app_id,
                "installation_id": target.github_installation_id,
                "owner": target.credential_owner_reference,
                "repository": target.github_repository,
                "permissions": REQUIRED_APP_PERMISSIONS,
            }
        )
        target.sudo().write(
            {
                "credential_expires_at": expires_at,
                "credential_validated_at": now,
                "credential_validation_digest": digest,
            }
        )
        return True

    def _github_json(self, target, args):
        result = self._run_gh(target, args)
        try:
            return json.loads(result.stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise UserError("GitHub returned malformed PR metadata.")

    def _matching_open_prs(self, target, approval=None):
        self.ensure_one()
        source_branch = approval.source_branch if approval else self.execution_branch
        target_branch = approval.target_branch if approval else target.target_branch
        source_owner = target.github_repository.split("/", 1)[0]
        endpoint = (
            "repos/%s/pulls?state=open&head=%s&base=%s"
            % (
                target.github_repository,
                quote("%s:%s" % (source_owner, source_branch), safe=""),
                quote(target_branch, safe=""),
            )
        )
        result = self._github_json(target, [endpoint])
        if not isinstance(result, list):
            raise UserError("GitHub duplicate-PR lookup returned invalid metadata.")
        return result

    def _existing_pr_message(self, target, metadata):
        self.ensure_one()
        try:
            number = int(metadata["number"])
        except (KeyError, TypeError, ValueError):
            raise UserError("GitHub reported an invalid existing PR reference.")
        expected_url = "https://github.com/%s/pull/%s" % (
            target.github_repository,
            number,
        )
        if metadata.get("html_url") != expected_url:
            raise UserError("GitHub reported an invalid existing PR reference.")
        return "Matching open PR already exists: #%s %s" % (number, expected_url)

    def _assert_pr_base(self, target):
        self.ensure_one()
        self._require_pr_manager()
        if self.state not in ("pushed_reviewed", "pr_approved"):
            raise AccessError("PR creation requires a Pushed Reviewed workspace.")
        self._assert_no_worker_lease()
        self._assert_worker_identity(require_effective=True)
        self._assert_plan_unchanged()
        self.environment_id._assert_dev_hub_safe(self.project_id)
        self._validate_physical()
        if self.dirty_summary != "changed=0":
            raise AccessError("Dirty worktrees cannot create PRs.")
        if (
            not self.push_record_id
            or self.push_record_id.result not in ("success", "reconciled_success")
            or self.push_record_id.commit_sha != self.committed_sha
            or self.current_head != self.committed_sha
        ):
            raise AccessError("PR source does not match a verified reviewed Push.")
        target.assert_pr_allowed(self.execution_branch)
        self._assert_scoped_github_identity(target)
        if self.push_record_id.remote_id != target.source_remote_id:
            raise AccessError("PR source remote differs from the verified Push remote.")
        snapshot = self._remote_snapshot(target.source_remote_id)
        if snapshot["target_head"] != self.committed_sha:
            raise AccessError("Remote PR source HEAD differs from reviewed commit.")
        self._github_json(
            target,
            [
                "repos/%s/git/ref/heads/%s"
                % (target.github_repository, quote(target.target_branch, safe=""))
            ],
        )
        return True

    def _default_pr_title(self):
        self.ensure_one()
        return _safe_pr_text(
            "[DW-%s] %s" % (self.work_item_id.id, self.work_item_id.name),
            "PR title",
            200,
        )

    def _default_pr_body(self):
        self.ensure_one()
        report = self.work_item_id.completion_report_ids.sorted(
            lambda item: item.id, reverse=True
        )[:1]
        parts = [
            "## Work Item",
            self.work_item_id.op_reference or "DW-%s" % self.work_item_id.id,
            "",
            "## Approved Plan",
            "Revision %s" % self.plan_revision,
            "",
            "## Implementation",
            (report.implemented_summary if report else self.review_handoff or "")[:2000],
            "",
            "## Changed Files",
            (self.commit_record_id.committed_files_summary or "")[:2000],
            "",
            "## Tests",
            (self.review_tests_summary or "")[:2000],
            "",
            "## Known Limitations",
            (report.known_limitations if report else "None recorded.")[:1000],
            "",
            "Created through a human-approved Dev Hub PR gate. No merge or deployment performed.",
        ]
        return _safe_pr_text("\n".join(parts), "PR body", 10000)

    def action_review_pr_proposal(self):
        self.ensure_one()
        targets = self.repository_id.pr_target_ids.filtered(
            lambda target: target.active and target.approved and target.non_production
        )
        if len(targets) != 1:
            raise UserError("Exactly one approved non-production PR target is required.")
        target = targets
        self._assert_pr_base(target)
        existing = self._matching_open_prs(target)
        if existing:
            raise AccessError(
                self._existing_pr_message(target, existing[0])
                + ". Duplicate creation denied."
            )
        title = self._default_pr_title()
        body = self._default_pr_body()
        commit_message = self.commit_record_id.approval_id.commit_message.splitlines()[0]
        self.sudo()._internal_write(
            {
                "pr_target_id": target.id,
                "pr_source_branch": self.execution_branch,
                "pr_source_sha": self.committed_sha,
                "pr_target_branch": target.target_branch,
                "pr_commit_list": "%s %s" % (self.committed_sha, commit_message),
                "pr_title_preview": title,
                "pr_body_preview": body,
                "pr_body_digest": hashlib.sha256(body.encode()).hexdigest(),
                "pr_last_checked_at": fields.Datetime.now(),
            }
        )
        self._event("pr_reviewed", "Human reviewed exact PR source and target")
        return self._form_action()

    def action_open_pr_approval(self):
        self.ensure_one()
        self.action_review_pr_proposal()
        return {
            "type": "ir.actions.act_window",
            "name": "Approve Pull Request Creation",
            "res_model": "dev.git.pr.approval.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_workspace_id": self.id,
                "default_target_id": self.pr_target_id.id,
                "default_pr_title": self.pr_title_preview,
                "default_pr_body": self.pr_body_preview,
            },
        }

    def create_pr_approval(self, target, title, body):
        self.ensure_one()
        if self.state != "pushed_reviewed":
            raise AccessError("Fresh PR approval requires Pushed Reviewed state.")
        self._assert_pr_base(target)
        existing = self._matching_open_prs(target)
        if existing:
            raise AccessError(
                self._existing_pr_message(target, existing[0])
                + ". Duplicate creation denied."
            )
        title = _safe_pr_text(title, "PR title", 200)
        body = _safe_pr_text(body, "PR body", 10000)
        title_hash = hashlib.sha256(title.encode()).hexdigest()
        body_digest = hashlib.sha256(body.encode()).hexdigest()
        idempotency_key = _canonical_hash(
            {
                "repository": target.github_repository,
                "source": self.execution_branch,
                "target": target.target_branch,
                "work_item_id": self.work_item_id.id,
            }
        )
        approval = self.env["dev.git.pr.approval"].sudo().with_context(
            dev_git_pr_approval=True
        ).create(
            {
                "work_item_id": self.work_item_id.id,
                "workspace_id": self.id,
                "repository_id": self.repository_id.id,
                "source_remote_id": target.source_remote_id.id,
                "source_branch": self.execution_branch,
                "source_commit_sha": self.committed_sha,
                "target_repository_id": target.target_repository_id.id,
                "target_id": target.id,
                "github_repository": target.github_repository,
                "target_branch": target.target_branch,
                "credential_type": target.credential_type,
                "credential_owner_reference": target.credential_owner_reference,
                "github_app_id": target.github_app_id,
                "github_installation_id": target.github_installation_id,
                "credential_validation_digest": (
                    target.credential_validation_digest
                ),
                "pr_title": title,
                "pr_title_hash": title_hash,
                "pr_body": body,
                "pr_body_digest": body_digest,
                "plan_id": self.plan_id.id,
                "plan_hash": self.approved_plan_hash,
                "policy_hash": self.policy_hash,
                "execution_contract_hash": self.execution_contract_hash,
                "approver_id": self.env.user.id,
                "approved_at": fields.Datetime.now(),
                "idempotency_key": idempotency_key,
                "binding_hash": "pending",
            }
        )
        self.sudo()._internal_write(
            {
                "state": "pr_approved",
                "pr_approval_id": approval.id,
                "pr_title_preview": title,
                "pr_body_preview": body,
                "pr_body_digest": body_digest,
            }
        )
        self._event("pr_approved", "Human approved exact PR creation")
        return approval

    def _assert_pr_approval_current(self, approval):
        self.ensure_one()
        if self.state != "pr_approved" or self.pr_approval_id != approval:
            raise AccessError("A current immutable PR approval is required.")
        if approval.event_ids:
            raise AccessError("PR approval has already been consumed or invalidated.")
        approval.assert_integrity()
        self._assert_pr_base(approval.target_id)
        expected = {
            "source branch": (self.execution_branch, approval.source_branch),
            "source SHA": (self.committed_sha, approval.source_commit_sha),
            "target branch": (approval.target_id.target_branch, approval.target_branch),
            "credential type": (
                approval.target_id.credential_type,
                approval.credential_type,
            ),
            "credential owner": (
                approval.target_id.credential_owner_reference,
                approval.credential_owner_reference,
            ),
            "GitHub App ID": (
                approval.target_id.github_app_id,
                approval.github_app_id,
            ),
            "GitHub installation ID": (
                approval.target_id.github_installation_id,
                approval.github_installation_id,
            ),
            "credential validation": (
                approval.target_id.credential_validation_digest,
                approval.credential_validation_digest,
            ),
            "repository": (
                approval.target_id.github_repository,
                approval.github_repository,
            ),
            "PR title": (self.pr_title_preview, approval.pr_title),
            "PR title hash": (
                hashlib.sha256((self.pr_title_preview or "").encode()).hexdigest(),
                approval.pr_title_hash,
            ),
            "PR body digest": (
                hashlib.sha256((self.pr_body_preview or "").encode()).hexdigest(),
                approval.pr_body_digest,
            ),
            "Plan": (self.plan_id.id, approval.plan_id.id),
            "Plan hash": (self.approved_plan_hash, approval.plan_hash),
            "policy hash": (self.policy_hash, approval.policy_hash),
            "contract hash": (
                self.execution_contract_hash,
                approval.execution_contract_hash,
            ),
        }
        mismatch = [name for name, values in expected.items() if values[0] != values[1]]
        if mismatch:
            raise AccessError(
                "PR approval is stale; fresh review required (%s)."
                % ", ".join(mismatch)
            )
        return True

    def action_open_pr_execution(self):
        self.ensure_one()
        self._assert_pr_approval_current(self.pr_approval_id)
        return {
            "type": "ir.actions.act_window",
            "name": "Confirm Pull Request Creation",
            "res_model": "dev.git.pr.execution.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_workspace_id": self.id,
                "default_approval_id": self.pr_approval_id.id,
            },
        }

    def _verified_pr_values(self, approval, metadata):
        required = ("number", "html_url", "state", "title", "head", "base", "merged")
        if not isinstance(metadata, dict) or any(key not in metadata for key in required):
            raise UserError("GitHub PR verification returned incomplete metadata.")
        expected_url = "https://github.com/%s/pull/%s" % (
            approval.github_repository,
            metadata["number"],
        )
        if (
            metadata["html_url"] != expected_url
            or metadata["state"] != "open"
            or metadata["merged"] is not False
            or metadata.get("auto_merge") is not None
            or metadata["title"] != approval.pr_title
            or metadata["head"].get("ref") != approval.source_branch
            or metadata["head"].get("sha") != approval.source_commit_sha
            or metadata["base"].get("ref") != approval.target_branch
        ):
            raise UserError("Created PR does not match the immutable approval.")
        return {
            "number": int(metadata["number"]),
            "url": expected_url,
        }

    def _record_pr_result(self, approval, result_state, metadata=None):
        self.ensure_one()
        created_at = fields.Datetime.now()
        verified = self._verified_pr_values(approval, metadata) if metadata else {
            "number": 0,
            "url": False,
        }
        verification = {
            "created": "Open PR verified; not merged; auto-merge disabled.",
            "reconciled_existing": "Existing matching open PR verified after API uncertainty.",
            "creation_failed_review": "No matching PR found after failed creation request.",
            "uncertain_remote_state": "GitHub state could not be reconciled; retry blocked.",
        }[result_state]
        correlation = _canonical_hash(
            {
                "idempotency_key": approval.idempotency_key,
                "approved_at": fields.Datetime.to_string(approval.approved_at),
            }
        )
        record = self.env["dev.git.pr.record"].sudo().with_context(
            dev_git_pr_record=True
        ).create(
            {
                "work_item_id": self.work_item_id.id,
                "workspace_id": self.id,
                "approval_id": approval.id,
                "target_id": approval.target_id.id,
                "github_repository": approval.github_repository,
                "source_branch": approval.source_branch,
                "source_sha": approval.source_commit_sha,
                "target_branch": approval.target_branch,
                "credential_type": approval.credential_type,
                "credential_owner_reference": approval.credential_owner_reference,
                "github_app_id": approval.github_app_id,
                "github_installation_id": approval.github_installation_id,
                "credential_validation_digest": (
                    approval.credential_validation_digest
                ),
                "pr_title": approval.pr_title,
                "pr_body_digest": approval.pr_body_digest,
                "pr_number": verified["number"],
                "pr_url_reference": verified["url"],
                "approver_id": approval.approver_id.id,
                "created_at": created_at,
                "result_state": result_state,
                "verification_result": verification,
                "idempotency_key": approval.idempotency_key,
                "api_correlation_reference": correlation,
                "audit_hash": "pending",
            }
        )
        event_type = (
            "consumed" if result_state == "created" else result_state
        )
        self.env["dev.git.pr.approval.event"].sudo().with_context(
            dev_git_pr_event=True
        ).create(
            {
                "approval_id": approval.id,
                "event_type": event_type,
                "actor_id": self.env.user.id,
                "summary": verification,
                "payload_json": json.dumps(
                    {
                        "pr_number": verified["number"],
                        "result_state": result_state,
                        "api_correlation_reference": correlation,
                    },
                    sort_keys=True,
                ),
            }
        )
        if result_state in ("created", "reconciled_existing"):
            state = "pr_created_reviewed"
        elif result_state == "creation_failed_review":
            state = "pr_creation_failed_review"
        else:
            state = "pr_uncertain_state"
        self.sudo()._internal_write(
            {
                "state": state,
                "pr_record_id": record.id,
                "pr_number": verified["number"],
                "pr_url_reference": verified["url"],
                "pr_created_at": created_at,
            }
        )
        self._event(
            "pr_%s" % result_state,
            verification,
            {"pr_record_id": record.id, "pr_number": verified["number"]},
        )
        return record

    def execute_approved_pr(self, approval):
        self.ensure_one()
        self.env.cr.execute(
            "SELECT id FROM dev_execution_workspace WHERE id = %s FOR UPDATE NOWAIT",
            [self.id],
        )
        self._assert_pr_approval_current(approval)
        target = approval.target_id
        existing = self._matching_open_prs(target, approval)
        if existing:
            raise AccessError(
                self._existing_pr_message(target, existing[0])
                + ". Duplicate creation denied."
            )
        payload = {
            "title": approval.pr_title,
            "head": approval.source_branch,
            "base": approval.target_branch,
            "body": approval.pr_body,
            "draft": False,
            "maintainer_can_modify": False,
        }
        result = self._run_gh(
            target,
            ["-X", "POST", "repos/%s/pulls" % approval.github_repository, "--input", "-"],
            input_payload=payload,
            check=False,
        )
        metadata = None
        if result.returncode == 0:
            try:
                created = json.loads(result.stdout.decode("utf-8"))
                number = int(created["number"])
                metadata = self._github_json(
                    target,
                    ["repos/%s/pulls/%s" % (approval.github_repository, number)],
                )
            except (
                KeyError,
                ValueError,
                UnicodeDecodeError,
                json.JSONDecodeError,
                UserError,
            ):
                metadata = None
        if metadata is not None:
            try:
                return self._record_pr_result(approval, "created", metadata)
            except UserError:
                metadata = None
        try:
            matches = self._matching_open_prs(target, approval)
        except Exception:
            return self._record_pr_result(approval, "uncertain_remote_state")
        exact = [
            item
            for item in matches
            if item.get("head", {}).get("sha") == approval.source_commit_sha
            and item.get("title") == approval.pr_title
        ]
        if len(exact) == 1:
            try:
                metadata = self._github_json(
                    target,
                    [
                        "repos/%s/pulls/%s"
                        % (approval.github_repository, exact[0]["number"])
                    ],
                )
                return self._record_pr_result(
                    approval, "reconciled_existing", metadata
                )
            except UserError:
                return self._record_pr_result(approval, "uncertain_remote_state")
        return self._record_pr_result(approval, "creation_failed_review")

    def action_reject_pr_proposal(self):
        self.ensure_one()
        self._require_pr_manager()
        if self.state not in ("pushed_reviewed", "pr_approved"):
            raise AccessError("Only a pending PR proposal may be rejected.")
        if self.pr_approval_id and not self.pr_approval_id.event_ids:
            self.env["dev.git.pr.approval.event"].sudo().with_context(
                dev_git_pr_event=True
            ).create(
                {
                    "approval_id": self.pr_approval_id.id,
                    "event_type": "rejected",
                    "actor_id": self.env.user.id,
                    "summary": "Human rejected PR proposal and returned it for changes.",
                }
            )
        self.sudo()._internal_write(
            {
                "state": "pushed_reviewed",
                "pr_approval_id": False,
                "pr_title_preview": False,
                "pr_body_preview": False,
                "pr_body_digest": False,
            }
        )
        self._event("pr_rejected", "Human rejected PR proposal")
        return self._form_action()
