# -*- coding: utf-8 -*-
import hashlib
import json
import os
import re
import subprocess

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from .dev_execution import FORBIDDEN_ROOTS
from .dev_git_commit import _canonical_hash


FORBIDDEN_NAME_MARKERS = (
    ".env",
    ".pem",
    "filestore",
    ".dump",
    "backup",
    ".sql",
    "id_rsa",
    "id_ed25519",
    "id_dsa",
    "-----begin",
)
SKIP_DIR_NAMES = {".git", "node_modules", "__pycache__"}
SCAN_FILE_LIMIT = 20000
GITHUB_HTTPS_RE = re.compile(
    r"^https://[^/]+/(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$"
)
GITHUB_SSH_RE = re.compile(
    r"^[\w.-]+@[^:]+:(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$"
)


def _parse_remotes(raw):
    remotes = {}
    for line in raw.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            remotes.setdefault(parts[0], parts[1])
    return remotes


def _parse_github_remote(url):
    match = GITHUB_HTTPS_RE.match(url or "") or GITHUB_SSH_RE.match(url or "")
    if not match:
        return "unknown", "", ""
    return "github", match.group("owner"), match.group("repo")


def _scan_forbidden_paths(root):
    findings = []
    scanned = 0
    for current, dirs, files in os.walk(root, topdown=True):
        dirs[:] = [name for name in dirs if name not in SKIP_DIR_NAMES]
        for name in files:
            scanned += 1
            if scanned > SCAN_FILE_LIMIT:
                findings.append("scan truncated at %s files" % SCAN_FILE_LIMIT)
                return findings
            lowered = name.casefold()
            if any(marker in lowered for marker in FORBIDDEN_NAME_MARKERS):
                relative = os.path.relpath(os.path.join(current, name), root)
                findings.append(relative)
    return findings


class DevRepositoryDiscovery(models.Model):
    _name = "dev.repository.discovery"
    _description = "Read-Only Local Repository Discovery Scan"
    _order = "scanned_at desc, id desc"

    project_id = fields.Many2one(
        "dev.project", required=True, ondelete="cascade", index=True
    )
    local_path = fields.Char(required=True)
    selected_remote_name = fields.Char(
        help="Required human disambiguation input when multiple remotes are found."
    )
    git_dir_found = fields.Boolean(readonly=True)
    remotes_json = fields.Text(readonly=True)
    provider = fields.Char(readonly=True)
    owner = fields.Char(readonly=True)
    repo_name = fields.Char(readonly=True)
    remote_name = fields.Char(readonly=True)
    remote_count = fields.Integer(readonly=True)
    history_compatible = fields.Boolean(readonly=True)
    current_branch = fields.Char(readonly=True)
    default_branch = fields.Char()
    staging_branch = fields.Char(default="staging")
    production_branch = fields.Char(default="main")
    secret_scan_summary = fields.Text(readonly=True)
    restricted_paths_summary = fields.Text(readonly=True)
    requires_bootstrap = fields.Boolean(readonly=True)
    scan_digest = fields.Char(readonly=True)
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("scanned", "Scanned"),
            ("ambiguous", "Ambiguous — Human Selection Required"),
            ("failed_closed", "Failed Closed"),
        ],
        default="draft",
        required=True,
        readonly=True,
    )
    scanned_at = fields.Datetime(readonly=True)
    github_repository = fields.Char(compute="_compute_github_repository", store=True)
    bind_approval_ids = fields.One2many(
        "dev.repository.bind.approval", "discovery_id", readonly=True
    )
    bootstrap_approval_ids = fields.One2many(
        "dev.repository.bootstrap.approval", "discovery_id", readonly=True
    )

    @api.depends("owner", "repo_name")
    def _compute_github_repository(self):
        for record in self:
            record.github_repository = (
                "%s/%s" % (record.owner, record.repo_name)
                if record.owner and record.repo_name
                else False
            )

    def unlink(self):
        raise AccessError("Repository discovery scans are retained for audit.")

    def _internal_write(self, values):
        return super(DevRepositoryDiscovery, self).write(values)

    @api.model
    def _git(self, args, cwd, check=True):
        allowed = {"remote", "branch", "log", "rev-parse", "symbolic-ref"}
        if not args or args[0] not in allowed:
            raise AccessError("Only read-only Git discovery commands are permitted.")
        command = ["git", "-c", "safe.directory=%s" % cwd, "-C", cwd, *args]
        environment = {
            "PATH": "/usr/bin:/bin",
            "HOME": "/nonexistent",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
            "LANG": "C",
        }
        try:
            result = subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
                check=False,
                env=environment,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise UserError("Discovery Git command failed safely: %s" % exc)
        if check and result.returncode:
            raise UserError(
                "Discovery Git command failed safely: %s"
                % result.stderr.decode("utf-8", "replace")[:500]
            )
        return result

    def _fail_closed(self, reason):
        self.ensure_one()
        self._internal_write(
            {
                "state": "failed_closed",
                "secret_scan_summary": reason,
                "scanned_at": fields.Datetime.now(),
            }
        )
        raise UserError("Discovery failed closed: %s" % reason)

    def action_scan(self):
        self.ensure_one()
        if self.state not in ("draft", "ambiguous", "failed_closed"):
            raise UserError(
                "Only a Draft, Ambiguous, or Failed-Closed discovery can be rescanned."
            )
        path = os.path.realpath(self.local_path or "")
        if not self.local_path or not os.path.isabs(self.local_path) or not path:
            raise ValidationError("Discovery local path must be a canonical absolute path.")
        if any(
            path == root or path.startswith(root + os.sep) for root in FORBIDDEN_ROOTS
        ):
            raise ValidationError("Discovery path cannot use a sensitive root.")
        if not os.path.isdir(path):
            return self._fail_closed("Local path does not exist or is not a directory.")
        git_dir = os.path.join(path, ".git")
        if not os.path.isdir(git_dir) and not os.path.isfile(git_dir):
            return self._fail_closed("No .git directory was found at the local path.")
        remote_result = self._git(["remote", "-v"], cwd=path, check=False)
        if remote_result.returncode:
            return self._fail_closed("Unable to read Git remotes.")
        remotes = _parse_remotes(remote_result.stdout.decode("utf-8", "replace"))
        if not remotes:
            return self._fail_closed("No Git remotes are configured for this repository.")
        remote_names = sorted(remotes)
        if len(remote_names) > 1 and self.selected_remote_name not in remote_names:
            self._internal_write(
                {
                    "state": "ambiguous",
                    "git_dir_found": True,
                    "remote_count": len(remote_names),
                    "remotes_json": json.dumps(remotes, sort_keys=True),
                    "scanned_at": fields.Datetime.now(),
                }
            )
            raise UserError(
                "Multiple remotes were found (%s). Set selected_remote_name to exactly "
                "one and rescan; no remote is chosen automatically."
                % ", ".join(remote_names)
            )
        remote_name = self.selected_remote_name or remote_names[0]
        if remote_name not in remotes:
            return self._fail_closed(
                "The selected remote is not present in this repository."
            )
        remote_url = remotes[remote_name]
        provider, owner, repo_name = _parse_github_remote(remote_url)
        if provider != "github" or not owner or not repo_name:
            return self._fail_closed(
                "The remote URL could not be resolved to an exact owner/name."
            )
        branch_result = self._git(["branch", "--show-current"], cwd=path, check=False)
        current_branch = (
            branch_result.stdout.decode().strip() if not branch_result.returncode else ""
        )
        history_result = self._git(["log", "-1", "--format=%H"], cwd=path, check=False)
        history_compatible = history_result.returncode == 0
        findings = _scan_forbidden_paths(path)
        if findings:
            self._internal_write(
                {
                    "git_dir_found": True,
                    "remotes_json": json.dumps(remotes, sort_keys=True),
                    "provider": provider,
                    "owner": owner,
                    "repo_name": repo_name,
                    "remote_name": remote_name,
                    "remote_count": len(remote_names),
                    "restricted_paths_summary": "\n".join(findings[:200]),
                }
            )
            return self._fail_closed(
                "Forbidden filename markers were found (%s entries); onboarding is blocked."
                % len(findings)
            )
        payload = {
            "local_path": path,
            "provider": provider,
            "owner": owner,
            "repo_name": repo_name,
            "remote_name": remote_name,
            "remote_url": remote_url,
            "current_branch": current_branch,
            "history_compatible": history_compatible,
        }
        self._internal_write(
            {
                "git_dir_found": True,
                "remotes_json": json.dumps(remotes, sort_keys=True),
                "provider": provider,
                "owner": owner,
                "repo_name": repo_name,
                "remote_name": remote_name,
                "remote_count": len(remote_names),
                "history_compatible": history_compatible,
                "current_branch": current_branch,
                "default_branch": self.default_branch or current_branch or "main",
                "secret_scan_summary": "No forbidden filename markers found.",
                "restricted_paths_summary": "",
                "requires_bootstrap": not history_compatible,
                "scan_digest": _canonical_hash(payload),
                "state": "scanned",
                "scanned_at": fields.Datetime.now(),
            }
        )
        return True

    def _remote_url(self):
        self.ensure_one()
        remotes = json.loads(self.remotes_json or "{}")
        return remotes.get(self.remote_name, "")

    def _assert_fresh_scan(self):
        self.ensure_one()
        if self.state != "scanned":
            raise UserError("An immutable approval requires a fresh Scanned discovery.")
        payload = {
            "local_path": os.path.realpath(self.local_path or ""),
            "provider": self.provider,
            "owner": self.owner,
            "repo_name": self.repo_name,
            "remote_name": self.remote_name,
            "remote_url": self._remote_url(),
            "current_branch": self.current_branch,
            "history_compatible": self.history_compatible,
        }
        if self.scan_digest != _canonical_hash(payload):
            raise AccessError("The discovery scan drifted; a fresh scan is required.")

    def create_bind_approval(self, allowlist):
        self.ensure_one()
        self._assert_fresh_scan()
        if self.requires_bootstrap:
            raise UserError(
                "This discovery requires a bootstrap approval, not a direct bind."
            )
        if allowlist.github_repository != self.github_repository:
            raise AccessError(
                "The allowlist entry must authorize this exact discovered repository."
            )
        allowlist.assert_authorized()
        if self.env["dev.repository.bind.record"].sudo().search_count(
            [("local_path", "=", self.local_path), ("result_state", "=", "bound")]
        ):
            raise AccessError("This local path is already bound to a repository.")
        requester = self.env.user
        approval = (
            self.env["dev.repository.bind.approval"]
            .sudo()
            .with_context(dev_repo_bind_approval=True)
            .create(
                {
                    "discovery_id": self.id,
                    "project_id": self.project_id.id,
                    "local_path": self.local_path,
                    "github_repository": self.github_repository,
                    "remote_name": self.remote_name,
                    "installation_id": allowlist.installation_id.id,
                    "allowlist_id": allowlist.id,
                    "requester_id": requester.id,
                    "approver_id": self.env.user.id,
                    "scan_digest": self.scan_digest,
                    "approved_at": fields.Datetime.now(),
                    "binding_hash": "pending",
                }
            )
        )
        return approval

    def execute_approved_bind(self, approval):
        self.ensure_one()
        approval.ensure_one()
        if approval.discovery_id != self:
            raise AccessError("The approval does not belong to this discovery.")
        approval.assert_integrity()
        if approval.event_ids:
            raise AccessError("This bind approval was already consumed.")
        self._assert_fresh_scan()
        if approval.scan_digest != self.scan_digest:
            raise AccessError("The discovery drifted after approval; a fresh review is required.")
        origin_hash = hashlib.sha256((self._remote_url() or "").encode()).hexdigest()
        repository = (
            self.env["dev.repository"]
            .sudo()
            .search([("working_directory", "=", self.local_path)], limit=1)
        )
        vals = {
            "name": self.github_repository,
            "project_id": self.project_id.id,
            "git_remote": self._remote_url(),
            "canonical_remote_path": self.local_path,
            "working_directory": self.local_path,
            "default_branch": self.default_branch or self.current_branch or "main",
            "github_owner": self.owner,
            "github_repo_name": self.repo_name,
            "bound_allowlist_id": approval.allowlist_id.id,
            "origin_locked": True,
        }
        if repository:
            repository.sudo().with_context(dev_repo_bind_internal=True).write(vals)
        else:
            repository = (
                self.env["dev.repository"]
                .sudo()
                .with_context(dev_repo_bind_internal=True)
                .create(vals)
            )
        record = (
            self.env["dev.repository.bind.record"]
            .sudo()
            .with_context(dev_repo_bind_record=True)
            .create(
                {
                    "repository_id": repository.id,
                    "github_repository": self.github_repository,
                    "local_path": self.local_path,
                    "origin_url_hash": origin_hash,
                    "allowlist_id": approval.allowlist_id.id,
                    "result_state": "bound",
                    "audit_hash": "pending",
                }
            )
        )
        repository.sudo().with_context(dev_repo_bind_internal=True).write(
            {"bind_record_id": record.id}
        )
        self.env["dev.repository.bind.approval.event"].sudo().with_context(
            dev_repo_bind_event=True
        ).create(
            {
                "approval_id": approval.id,
                "event_type": "consumed",
                "actor_id": self.env.user.id,
                "summary": "Discovery-approved bind executed; repository origin locked",
            }
        )
        return record

    def create_bootstrap_approval(self, allowlist):
        self.ensure_one()
        self._assert_fresh_scan()
        if not self.requires_bootstrap:
            raise UserError(
                "Bootstrap approval requires a discovery flagged for bootstrap."
            )
        if allowlist.github_repository != self.github_repository:
            raise AccessError(
                "The allowlist entry must authorize this exact discovered repository."
            )
        allowlist.assert_authorized()
        requester = self.env.user
        approval = (
            self.env["dev.repository.bootstrap.approval"]
            .sudo()
            .with_context(dev_repo_bootstrap_approval=True)
            .create(
                {
                    "discovery_id": self.id,
                    "project_id": self.project_id.id,
                    "local_path": self.local_path,
                    "github_repository": self.github_repository,
                    "remote_name": self.remote_name,
                    "installation_id": allowlist.installation_id.id,
                    "allowlist_id": allowlist.id,
                    "requester_id": requester.id,
                    "approver_id": self.env.user.id,
                    "scan_digest": self.scan_digest,
                    "approved_at": fields.Datetime.now(),
                    "binding_hash": "pending",
                }
            )
        )
        return approval

    def execute_approved_bootstrap(self, approval):
        self.ensure_one()
        approval.ensure_one()
        if approval.discovery_id != self:
            raise AccessError("The approval does not belong to this discovery.")
        approval.assert_integrity()
        if approval.event_ids:
            raise AccessError("This bootstrap approval was already consumed.")
        self._assert_fresh_scan()
        if approval.scan_digest != self.scan_digest:
            raise AccessError("The discovery drifted after approval; a fresh review is required.")
        record = (
            self.env["dev.repository.bootstrap.record"]
            .sudo()
            .with_context(dev_repo_bootstrap_record=True)
            .create(
                {
                    "approval_id": approval.id,
                    "discovery_id": self.id,
                    "github_repository": self.github_repository,
                    "local_path": self.local_path,
                    "result_state": "approved_pending_push",
                    "code_uploaded": False,
                    "audit_hash": "pending",
                }
            )
        )
        record.assert_no_preapproval_upload()
        self.env["dev.repository.bootstrap.approval.event"].sudo().with_context(
            dev_repo_bootstrap_event=True
        ).create(
            {
                "approval_id": approval.id,
                "event_type": "consumed",
                "actor_id": self.env.user.id,
                "summary": (
                    "Bootstrap approved; no code was uploaded. The initial push "
                    "still requires the existing separate push approval gate."
                ),
            }
        )
        return record


class DevRepositoryBindApproval(models.Model):
    _name = "dev.repository.bind.approval"
    _description = "Immutable Human Repository Bind Approval"
    _order = "approved_at desc, id desc"

    discovery_id = fields.Many2one(
        "dev.repository.discovery", required=True, readonly=True, ondelete="restrict"
    )
    project_id = fields.Many2one(
        "dev.project", required=True, readonly=True, ondelete="restrict"
    )
    local_path = fields.Char(required=True, readonly=True)
    github_repository = fields.Char(required=True, readonly=True)
    remote_name = fields.Char(required=True, readonly=True)
    installation_id = fields.Many2one(
        "dev.github.app.installation", required=True, readonly=True, ondelete="restrict"
    )
    allowlist_id = fields.Many2one(
        "dev.github.repository.allowlist", required=True, readonly=True, ondelete="restrict"
    )
    requester_id = fields.Many2one(
        "res.users", required=True, readonly=True, ondelete="restrict"
    )
    approver_id = fields.Many2one(
        "res.users", required=True, readonly=True, ondelete="restrict"
    )
    scan_digest = fields.Char(readonly=True)
    plan_hash = fields.Char(readonly=True)
    policy_hash = fields.Char(readonly=True)
    approved_at = fields.Datetime(required=True, readonly=True)
    binding_hash = fields.Char(required=True, readonly=True, copy=False)
    event_ids = fields.One2many(
        "dev.repository.bind.approval.event", "approval_id", readonly=True
    )

    def _binding(self):
        self.ensure_one()
        names = (
            "discovery_id",
            "project_id",
            "local_path",
            "github_repository",
            "remote_name",
            "installation_id",
            "allowlist_id",
            "requester_id",
            "approver_id",
            "scan_digest",
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
                raise AccessError("Bind approval integrity validation failed.")
        return True

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("dev_repo_bind_approval"):
            raise AccessError("Bind approvals require the guarded human review flow.")
        records = super().create(vals_list)
        for record in records:
            super(DevRepositoryBindApproval, record).write(
                {"binding_hash": _canonical_hash(record._binding())}
            )
        return records.with_context(dev_repo_bind_approval=False)

    def write(self, values):
        raise AccessError("Bind approvals are immutable.")

    def unlink(self):
        raise AccessError("Bind approvals are retained for audit.")


class DevRepositoryBindApprovalEvent(models.Model):
    _name = "dev.repository.bind.approval.event"
    _description = "Immutable Bind Approval Event"
    _order = "occurred_at desc, id desc"

    approval_id = fields.Many2one(
        "dev.repository.bind.approval", required=True, readonly=True, ondelete="restrict"
    )
    event_type = fields.Selection(
        [("consumed", "Consumed"), ("rejected", "Rejected")],
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
        if not self.env.context.get("dev_repo_bind_event"):
            raise AccessError("Bind approval events require a guarded action.")
        return super().create(vals_list)

    def write(self, values):
        raise AccessError("Bind approval events are immutable.")

    def unlink(self):
        raise AccessError("Bind approval events are retained for audit.")


class DevRepositoryBindRecord(models.Model):
    _name = "dev.repository.bind.record"
    _description = "Terminal Immutable Repository Bind Record"
    _order = "create_date desc, id desc"

    repository_id = fields.Many2one(
        "dev.repository", required=True, readonly=True, ondelete="restrict"
    )
    github_repository = fields.Char(required=True, readonly=True)
    local_path = fields.Char(required=True, readonly=True)
    origin_url_hash = fields.Char(required=True, readonly=True)
    allowlist_id = fields.Many2one(
        "dev.github.repository.allowlist", required=True, readonly=True, ondelete="restrict"
    )
    result_state = fields.Selection(
        [("bound", "Bound"), ("denied", "Denied"), ("failed_closed", "Failed Closed")],
        required=True,
        readonly=True,
    )
    audit_hash = fields.Char(required=True, readonly=True, copy=False)

    def _audit_values(self):
        self.ensure_one()
        return {
            "repository_id": self.repository_id.id,
            "github_repository": self.github_repository,
            "local_path": self.local_path,
            "origin_url_hash": self.origin_url_hash,
            "allowlist_id": self.allowlist_id.id,
            "result_state": self.result_state,
        }

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("dev_repo_bind_record"):
            raise AccessError("Bind records require guarded creation.")
        records = super().create(vals_list)
        for record in records:
            super(DevRepositoryBindRecord, record).write(
                {"audit_hash": _canonical_hash(record._audit_values())}
            )
        return records

    def write(self, values):
        raise AccessError("Bind records are immutable.")

    def unlink(self):
        raise AccessError("Bind records are retained for audit.")


class DevRepositoryBootstrapApproval(models.Model):
    _name = "dev.repository.bootstrap.approval"
    _description = "Immutable Human Repository Bootstrap Approval"
    _order = "approved_at desc, id desc"

    discovery_id = fields.Many2one(
        "dev.repository.discovery", required=True, readonly=True, ondelete="restrict"
    )
    project_id = fields.Many2one(
        "dev.project", required=True, readonly=True, ondelete="restrict"
    )
    local_path = fields.Char(required=True, readonly=True)
    github_repository = fields.Char(required=True, readonly=True)
    remote_name = fields.Char(required=True, readonly=True)
    installation_id = fields.Many2one(
        "dev.github.app.installation", required=True, readonly=True, ondelete="restrict"
    )
    allowlist_id = fields.Many2one(
        "dev.github.repository.allowlist", required=True, readonly=True, ondelete="restrict"
    )
    requester_id = fields.Many2one(
        "res.users", required=True, readonly=True, ondelete="restrict"
    )
    approver_id = fields.Many2one(
        "res.users", required=True, readonly=True, ondelete="restrict"
    )
    scan_digest = fields.Char(readonly=True)
    approved_at = fields.Datetime(required=True, readonly=True)
    binding_hash = fields.Char(required=True, readonly=True, copy=False)
    event_ids = fields.One2many(
        "dev.repository.bootstrap.approval.event", "approval_id", readonly=True
    )

    def _binding(self):
        self.ensure_one()
        names = (
            "discovery_id",
            "project_id",
            "local_path",
            "github_repository",
            "remote_name",
            "installation_id",
            "allowlist_id",
            "requester_id",
            "approver_id",
            "scan_digest",
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
                raise AccessError("Bootstrap approval integrity validation failed.")
        return True

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("dev_repo_bootstrap_approval"):
            raise AccessError("Bootstrap approvals require the guarded human review flow.")
        records = super().create(vals_list)
        for record in records:
            super(DevRepositoryBootstrapApproval, record).write(
                {"binding_hash": _canonical_hash(record._binding())}
            )
        return records.with_context(dev_repo_bootstrap_approval=False)

    def write(self, values):
        raise AccessError("Bootstrap approvals are immutable.")

    def unlink(self):
        raise AccessError("Bootstrap approvals are retained for audit.")


class DevRepositoryBootstrapApprovalEvent(models.Model):
    _name = "dev.repository.bootstrap.approval.event"
    _description = "Immutable Bootstrap Approval Event"
    _order = "occurred_at desc, id desc"

    approval_id = fields.Many2one(
        "dev.repository.bootstrap.approval",
        required=True,
        readonly=True,
        ondelete="restrict",
    )
    event_type = fields.Selection(
        [("consumed", "Consumed"), ("rejected", "Rejected")],
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
        if not self.env.context.get("dev_repo_bootstrap_event"):
            raise AccessError("Bootstrap approval events require a guarded action.")
        return super().create(vals_list)

    def write(self, values):
        raise AccessError("Bootstrap approval events are immutable.")

    def unlink(self):
        raise AccessError("Bootstrap approval events are retained for audit.")


class DevRepositoryBootstrapRecord(models.Model):
    _name = "dev.repository.bootstrap.record"
    _description = "Terminal Immutable Repository Bootstrap Record"
    _order = "create_date desc, id desc"

    approval_id = fields.Many2one(
        "dev.repository.bootstrap.approval",
        required=True,
        readonly=True,
        ondelete="restrict",
    )
    discovery_id = fields.Many2one(
        "dev.repository.discovery", required=True, readonly=True, ondelete="restrict"
    )
    github_repository = fields.Char(required=True, readonly=True)
    local_path = fields.Char(required=True, readonly=True)
    result_state = fields.Selection(
        [
            ("approved_pending_push", "Approved — Pending Push"),
            ("denied", "Denied"),
            ("failed_closed", "Failed Closed"),
        ],
        required=True,
        readonly=True,
    )
    code_uploaded = fields.Boolean(default=False, required=True, readonly=True)
    audit_hash = fields.Char(required=True, readonly=True, copy=False)

    @api.constrains("code_uploaded")
    def _check_no_upload_claim(self):
        for record in self:
            if record.code_uploaded:
                raise ValidationError(
                    "A bootstrap record must never claim code was uploaded before "
                    "an approval; the initial push always requires the separate "
                    "push approval gate."
                )

    def assert_no_preapproval_upload(self):
        self.ensure_one()
        if self.code_uploaded or self.result_state not in ("approved_pending_push",):
            raise AccessError(
                "Bootstrap record incorrectly claims a pre-approval code upload."
            )
        return True

    def _audit_values(self):
        self.ensure_one()
        return {
            "approval_id": self.approval_id.id,
            "discovery_id": self.discovery_id.id,
            "github_repository": self.github_repository,
            "local_path": self.local_path,
            "result_state": self.result_state,
            "code_uploaded": self.code_uploaded,
        }

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("dev_repo_bootstrap_record"):
            raise AccessError("Bootstrap records require guarded creation.")
        for values in vals_list:
            if values.get("code_uploaded"):
                raise AccessError(
                    "Bootstrap records can never be created claiming a pre-approval upload."
                )
        records = super().create(vals_list)
        for record in records:
            super(DevRepositoryBootstrapRecord, record).write(
                {"audit_hash": _canonical_hash(record._audit_values())}
            )
        return records

    def write(self, values):
        raise AccessError("Bootstrap records are immutable.")

    def unlink(self):
        raise AccessError("Bootstrap records are retained for audit.")


class DevRepository(models.Model):
    _inherit = "dev.repository"

    github_owner = fields.Char(readonly=True)
    github_repo_name = fields.Char(readonly=True)
    github_repository = fields.Char(
        compute="_compute_github_repository", store=True, readonly=True
    )
    bound_allowlist_id = fields.Many2one(
        "dev.github.repository.allowlist", readonly=True, ondelete="restrict"
    )
    origin_locked = fields.Boolean(default=True, readonly=True)
    bind_record_id = fields.Many2one(
        "dev.repository.bind.record", readonly=True, ondelete="restrict"
    )

    @api.depends("github_owner", "github_repo_name")
    def _compute_github_repository(self):
        for record in self:
            record.github_repository = (
                "%s/%s" % (record.github_owner, record.github_repo_name)
                if record.github_owner and record.github_repo_name
                else False
            )

    def assert_origin_immutable(self):
        """Guard method: agents can never change a locked repository origin.

        Every git-remote-mutation code path must call this before attempting
        to change origin metadata. No such path currently exists in this
        module; this method documents and enforces the invariant regardless.
        """
        self.ensure_one()
        if self.origin_locked:
            raise AccessError(
                "Repository origin is locked; only a fresh bind approval may change it."
            )
        return True

    def write(self, values):
        protected = {
            "git_remote",
            "canonical_remote_path",
            "working_directory",
            "github_owner",
            "github_repo_name",
            "bound_allowlist_id",
            "bind_record_id",
        }
        if protected.intersection(values) and not self.env.context.get(
            "dev_repo_bind_internal"
        ):
            for record in self:
                record.assert_origin_immutable()
        return super().write(values)
