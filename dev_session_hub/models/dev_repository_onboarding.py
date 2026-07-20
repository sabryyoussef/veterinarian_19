# -*- coding: utf-8 -*-
import hashlib
import json
import os
import re
import subprocess
from urllib.parse import urlparse

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from .dev_git_commit import _canonical_hash
from .dev_github_credentials import GITHUB_REPO_RE


FORBIDDEN_NAME_RE = re.compile(
    r"(^\.env($|\.)|\.pem$|\.dump$|\.sql$|id_rsa|filestore|backup|attachments?)",
    re.IGNORECASE,
)
REMOTE_URL_RE = re.compile(
    r"^(?:git@github\.com:|https://github\.com/)(?P<owner>[^/]+)/(?P<repo>[^/.]+?)(?:\.git)?$"
)


def _run_git(path, args):
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_NOSYSTEM": "1",
        "HOME": "/nonexistent",
    }
    completed = subprocess.run(
        ["git", "-C", path, *args],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    if completed.returncode != 0:
        raise UserError(
            "Read-only git discovery failed: %s"
            % ((completed.stderr or completed.stdout or "unknown").strip()[:500])
        )
    return completed.stdout


def _parse_github_remote(url):
    url = (url or "").strip()
    match = REMOTE_URL_RE.match(url)
    if match:
        return "github", match.group("owner"), match.group("repo")
    parsed = urlparse(url)
    if parsed.hostname == "github.com" and parsed.path:
        parts = parsed.path.strip("/").removesuffix(".git").split("/")
        if len(parts) >= 2:
            return "github", parts[0], parts[1]
    return False, False, False


class DevRepositoryDiscovery(models.Model):
    _name = "dev.repository.discovery"
    _description = "Repository Discovery Scan"
    _order = "id desc"

    name = fields.Char(required=True, default="Discovery")
    project_id = fields.Many2one("dev.project", required=True, ondelete="restrict")
    local_path = fields.Char(required=True)
    selected_remote_name = fields.Char()
    git_dir_found = fields.Boolean(readonly=True)
    remotes_json = fields.Text(readonly=True)
    provider = fields.Char(readonly=True)
    owner = fields.Char(readonly=True)
    repo_name = fields.Char(readonly=True)
    remote_name = fields.Char(readonly=True)
    remote_count = fields.Integer(readonly=True)
    history_compatible = fields.Boolean(readonly=True)
    current_branch = fields.Char(readonly=True)
    default_branch = fields.Char(readonly=True)
    staging_branch = fields.Char(readonly=True)
    production_branch = fields.Char(readonly=True)
    secret_scan_summary = fields.Text(readonly=True)
    restricted_paths_summary = fields.Text(readonly=True)
    requires_bootstrap = fields.Boolean(readonly=True)
    scan_digest = fields.Char(readonly=True)
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("scanned", "Scanned"),
            ("ambiguous", "Ambiguous"),
            ("failed_closed", "Failed Closed"),
        ],
        default="draft",
        required=True,
        readonly=True,
    )
    scanned_at = fields.Datetime(readonly=True)

    def action_scan(self):
        self.ensure_one()
        path = os.path.realpath(self.local_path or "")
        if not path.startswith("/") or path != os.path.realpath(path):
            raise ValidationError("local_path must be a canonical absolute path.")
        if not os.path.isdir(path):
            self.write(
                {
                    "state": "failed_closed",
                    "git_dir_found": False,
                    "secret_scan_summary": "Path is not a directory.",
                    "scanned_at": fields.Datetime.now(),
                }
            )
            return True

        git_dir = os.path.join(path, ".git")
        git_dir_found = os.path.exists(git_dir)
        if not git_dir_found:
            restricted = self._scan_restricted(path)
            payload = {
                "git_dir_found": False,
                "requires_bootstrap": True,
                "remote_count": 0,
                "remotes_json": "[]",
                "secret_scan_summary": restricted["summary"],
                "restricted_paths_summary": restricted["paths"],
                "history_compatible": False,
                "state": "scanned",
                "scanned_at": fields.Datetime.now(),
            }
            payload["scan_digest"] = _canonical_hash(payload)
            self.write(payload)
            return True

        try:
            remotes_raw = _run_git(path, ["remote", "-v"])
        except UserError as exc:
            self.write(
                {
                    "state": "failed_closed",
                    "git_dir_found": True,
                    "secret_scan_summary": str(exc),
                    "scanned_at": fields.Datetime.now(),
                }
            )
            return True

        remotes = {}
        for line in remotes_raw.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[-1] == "(fetch)":
                remotes[parts[0]] = parts[1]
        remote_count = len(remotes)
        selected = (self.selected_remote_name or "").strip()
        # Resolve branch/refs after remotes so multi-remote ambiguity wins over
        # empty-repo HEAD failures (unborn HEAD still has remotes).
        branch = ""
        refs = ""
        try:
            branch = _run_git(path, ["rev-parse", "--abbrev-ref", "HEAD"]).strip()
            refs = _run_git(path, ["branch", "-a"])
        except UserError:
            if remote_count <= 1:
                self.write(
                    {
                        "state": "failed_closed",
                        "git_dir_found": True,
                        "remote_count": remote_count,
                        "remotes_json": json.dumps(remotes, sort_keys=True),
                        "secret_scan_summary": "Unable to resolve HEAD/branches.",
                        "scanned_at": fields.Datetime.now(),
                    }
                )
                return True
        if remote_count == 0:
            restricted = self._scan_restricted(path)
            payload = {
                "git_dir_found": True,
                "requires_bootstrap": True,
                "remote_count": 0,
                "remotes_json": "[]",
                "current_branch": branch,
                "secret_scan_summary": restricted["summary"],
                "restricted_paths_summary": restricted["paths"],
                "history_compatible": False,
                "state": "scanned",
                "scanned_at": fields.Datetime.now(),
            }
            payload["scan_digest"] = _canonical_hash(payload)
            self.write(payload)
            return True
        if remote_count > 1 and not selected:
            self.write(
                {
                    "git_dir_found": True,
                    "remote_count": remote_count,
                    "remotes_json": json.dumps(remotes, sort_keys=True),
                    "current_branch": branch,
                    "state": "ambiguous",
                    "requires_bootstrap": False,
                    "secret_scan_summary": "Multiple remotes; select remote_name before bind.",
                    "scanned_at": fields.Datetime.now(),
                }
            )
            return True
        if selected and selected not in remotes:
            raise UserError("selected_remote_name is not present in discovered remotes.")
        remote_name = selected or next(iter(remotes))
        provider, owner, repo_name = _parse_github_remote(remotes[remote_name])
        if not provider:
            self.write(
                {
                    "git_dir_found": True,
                    "remote_count": remote_count,
                    "remotes_json": json.dumps(remotes, sort_keys=True),
                    "remote_name": remote_name,
                    "state": "failed_closed",
                    "secret_scan_summary": "Remote is not a parseable GitHub URL.",
                    "scanned_at": fields.Datetime.now(),
                }
            )
            return True

        branches = {line.strip().lstrip("* ").split()[-1] for line in refs.splitlines() if line.strip()}
        staging = "staging" if any(b.endswith("staging") for b in branches) else ""
        production = ""
        for candidate in ("production", "main", "master"):
            if any(b.endswith(candidate) for b in branches):
                production = candidate
                break
        default_branch = production or branch
        restricted = self._scan_restricted(path)
        history_compatible = bool(owner and repo_name)
        payload = {
            "git_dir_found": True,
            "requires_bootstrap": False,
            "remote_count": remote_count,
            "remotes_json": json.dumps(remotes, sort_keys=True),
            "provider": provider,
            "owner": owner,
            "repo_name": repo_name,
            "remote_name": remote_name,
            "current_branch": branch,
            "default_branch": default_branch,
            "staging_branch": staging,
            "production_branch": production,
            "history_compatible": history_compatible,
            "secret_scan_summary": restricted["summary"],
            "restricted_paths_summary": restricted["paths"],
            "state": "scanned",
            "scanned_at": fields.Datetime.now(),
        }
        payload["scan_digest"] = _canonical_hash(payload)
        self.write(payload)
        return True

    def _scan_restricted(self, path):
        hits = []
        for root, dirnames, filenames in os.walk(path):
            dirnames[:] = [d for d in dirnames if d not in {".git", "node_modules", "__pycache__"}]
            rel_root = os.path.relpath(root, path)
            for name in dirnames + filenames:
                rel = name if rel_root == "." else os.path.join(rel_root, name)
                if FORBIDDEN_NAME_RE.search(name) or FORBIDDEN_NAME_RE.search(rel):
                    hits.append(rel)
            if len(hits) >= 50:
                break
        summary = (
            "Restricted or sensitive path names detected."
            if hits
            else "No restricted filenames detected in shallow scan."
        )
        return {"summary": summary, "paths": "\n".join(hits[:50])}


class DevRepositoryBindApproval(models.Model):
    _name = "dev.repository.bind.approval"
    _description = "Immutable Human Repository Bind Approval"
    _order = "approved_at desc, id desc"

    discovery_id = fields.Many2one(
        "dev.repository.discovery", required=True, readonly=True, ondelete="restrict"
    )
    project_id = fields.Many2one("dev.project", required=True, readonly=True, ondelete="restrict")
    local_path = fields.Char(required=True, readonly=True)
    github_repository = fields.Char(required=True, readonly=True)
    remote_name = fields.Char(required=True, readonly=True)
    installation_id = fields.Many2one(
        "dev.github.app.installation", required=True, readonly=True, ondelete="restrict"
    )
    allowlist_id = fields.Many2one(
        "dev.github.repository.allowlist", required=True, readonly=True, ondelete="restrict"
    )
    requester_id = fields.Many2one("res.users", required=True, readonly=True, ondelete="restrict")
    approver_id = fields.Many2one("res.users", required=True, readonly=True, ondelete="restrict")
    scan_digest = fields.Char(required=True, readonly=True)
    binding_hash = fields.Char(required=True, readonly=True, copy=False)
    approved_at = fields.Datetime(required=True, readonly=True)
    event_ids = fields.One2many("dev.repository.bind.approval.event", "approval_id")

    def _binding(self):
        self.ensure_one()
        return {
            "discovery_id": self.discovery_id.id,
            "project_id": self.project_id.id,
            "local_path": self.local_path,
            "github_repository": self.github_repository,
            "remote_name": self.remote_name,
            "installation_id": self.installation_id.id,
            "allowlist_id": self.allowlist_id.id,
            "scan_digest": self.scan_digest,
            "requester_id": self.requester_id.id,
            "approver_id": self.approver_id.id,
        }

    def assert_integrity(self):
        self.ensure_one()
        if self.binding_hash != _canonical_hash(self._binding()):
            raise AccessError("Bind approval binding hash integrity check failed.")
        return True

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("dev_repository_bind_approval"):
            raise AccessError("Bind approvals may only be created through the guarded flow.")
        records = super().create(vals_list)
        for record in records:
            record.with_context(dev_repository_bind_approval_hash=True).write(
                {"binding_hash": _canonical_hash(record._binding())}
            )
        return records.with_context(
            dev_repository_bind_approval=False,
            dev_repository_bind_approval_hash=False,
        )

    def write(self, vals):
        if self.env.context.get("dev_repository_bind_approval_hash"):
            return super().write(vals)
        raise AccessError("Bind approvals are immutable.")

    def unlink(self):
        raise AccessError("Bind approvals are immutable.")


class DevRepositoryBindApprovalEvent(models.Model):
    _name = "dev.repository.bind.approval.event"
    _description = "Repository Bind Approval Event"
    _order = "id desc"

    approval_id = fields.Many2one(
        "dev.repository.bind.approval", required=True, readonly=True, ondelete="restrict"
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
        if not self.env.context.get("dev_repository_bind_event"):
            raise AccessError("Bind events may only be created through the guarded flow.")
        return super().create(vals_list)

    def write(self, vals):
        raise AccessError("Bind events are immutable.")

    def unlink(self):
        raise AccessError("Bind events are immutable.")


class DevRepositoryBindRecord(models.Model):
    _name = "dev.repository.bind.record"
    _description = "Terminal Repository Bind Record"
    _order = "id desc"

    approval_id = fields.Many2one(
        "dev.repository.bind.approval", required=True, readonly=True, ondelete="restrict"
    )
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
        [
            ("bound", "Bound"),
            ("denied", "Denied"),
            ("failed_closed", "Failed Closed"),
        ],
        required=True,
        readonly=True,
    )
    audit_hash = fields.Char(required=True, readonly=True, copy=False)
    bound_at = fields.Datetime(required=True, readonly=True, default=fields.Datetime.now)

    def _payload(self):
        self.ensure_one()
        return {
            "approval_id": self.approval_id.id,
            "repository_id": self.repository_id.id,
            "github_repository": self.github_repository,
            "local_path": self.local_path,
            "origin_url_hash": self.origin_url_hash,
            "allowlist_id": self.allowlist_id.id,
            "result_state": self.result_state,
        }

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("dev_repository_bind_record"):
            raise AccessError("Bind records may only be created through the guarded flow.")
        records = super().create(vals_list)
        for record in records:
            record.with_context(dev_repository_bind_record_hash=True).write(
                {"audit_hash": _canonical_hash(record._payload())}
            )
        return records

    def write(self, vals):
        if self.env.context.get("dev_repository_bind_record_hash"):
            return super().write(vals)
        raise AccessError("Bind records are immutable.")

    def unlink(self):
        raise AccessError("Bind records are immutable.")


class DevRepositoryBootstrapApproval(models.Model):
    _name = "dev.repository.bootstrap.approval"
    _description = "Immutable Human Repository Bootstrap Approval"
    _order = "approved_at desc, id desc"

    discovery_id = fields.Many2one(
        "dev.repository.discovery", required=True, readonly=True, ondelete="restrict"
    )
    project_id = fields.Many2one("dev.project", required=True, readonly=True, ondelete="restrict")
    local_path = fields.Char(required=True, readonly=True)
    proposed_github_repository = fields.Char(required=True, readonly=True)
    secret_scan_digest = fields.Char(required=True, readonly=True)
    ownership_confirmed = fields.Boolean(required=True, readonly=True)
    requester_id = fields.Many2one("res.users", required=True, readonly=True, ondelete="restrict")
    approver_id = fields.Many2one("res.users", required=True, readonly=True, ondelete="restrict")
    binding_hash = fields.Char(required=True, readonly=True, copy=False)
    approved_at = fields.Datetime(required=True, readonly=True)

    def _binding(self):
        self.ensure_one()
        return {
            "discovery_id": self.discovery_id.id,
            "project_id": self.project_id.id,
            "local_path": self.local_path,
            "proposed_github_repository": self.proposed_github_repository,
            "secret_scan_digest": self.secret_scan_digest,
            "ownership_confirmed": self.ownership_confirmed,
            "requester_id": self.requester_id.id,
            "approver_id": self.approver_id.id,
        }

    def assert_no_preapproval_upload(self):
        self.ensure_one()
        if not self.ownership_confirmed:
            raise AccessError("Bootstrap requires explicit ownership confirmation.")
        if self.discovery_id.requires_bootstrap is not True:
            raise AccessError("Bootstrap approval requires a bootstrap-eligible discovery.")
        return True

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("dev_repository_bootstrap_approval"):
            raise AccessError("Bootstrap approvals may only be created through the guarded flow.")
        records = super().create(vals_list)
        for record in records:
            record.with_context(dev_repository_bootstrap_hash=True).write(
                {"binding_hash": _canonical_hash(record._binding())}
            )
        return records.with_context(
            dev_repository_bootstrap_approval=False,
            dev_repository_bootstrap_hash=False,
        )

    def write(self, vals):
        if self.env.context.get("dev_repository_bootstrap_hash"):
            return super().write(vals)
        raise AccessError("Bootstrap approvals are immutable.")

    def unlink(self):
        raise AccessError("Bootstrap approvals are immutable.")


class DevRepositoryBootstrapApprovalEvent(models.Model):
    _name = "dev.repository.bootstrap.approval.event"
    _description = "Repository Bootstrap Approval Event"
    _order = "id desc"

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
    note = fields.Char(readonly=True)
    created_at = fields.Datetime(required=True, readonly=True, default=fields.Datetime.now)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("dev_repository_bootstrap_event"):
            raise AccessError("Bootstrap events may only be created through the guarded flow.")
        return super().create(vals_list)

    def write(self, vals):
        raise AccessError("Bootstrap events are immutable.")

    def unlink(self):
        raise AccessError("Bootstrap events are immutable.")


class DevRepositoryBootstrapRecord(models.Model):
    _name = "dev.repository.bootstrap.record"
    _description = "Terminal Repository Bootstrap Record"
    _order = "id desc"

    approval_id = fields.Many2one(
        "dev.repository.bootstrap.approval",
        required=True,
        readonly=True,
        ondelete="restrict",
    )
    result_state = fields.Selection(
        [
            ("approved_pending_push", "Approved — Pending Push Gate"),
            ("denied", "Denied"),
            ("failed_closed", "Failed Closed"),
        ],
        required=True,
        readonly=True,
    )
    code_uploaded = fields.Boolean(required=True, readonly=True, default=False)
    audit_hash = fields.Char(required=True, readonly=True, copy=False)
    recorded_at = fields.Datetime(required=True, readonly=True, default=fields.Datetime.now)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("dev_repository_bootstrap_record"):
            raise AccessError("Bootstrap records may only be created through the guarded flow.")
        for vals in vals_list:
            if vals.get("code_uploaded"):
                raise AccessError(
                    "Bootstrap must never record code upload before the push gate."
                )
            if vals.get("result_state") == "approved_pending_push" and vals.get(
                "code_uploaded"
            ):
                raise AccessError("Bootstrap pending push cannot claim upload.")
        records = super().create(vals_list)
        for record in records:
            payload = {
                "approval_id": record.approval_id.id,
                "result_state": record.result_state,
                "code_uploaded": record.code_uploaded,
            }
            record.with_context(dev_repository_bootstrap_record_hash=True).write(
                {"audit_hash": _canonical_hash(payload)}
            )
        return records

    def write(self, vals):
        if self.env.context.get("dev_repository_bootstrap_record_hash"):
            return super().write(vals)
        raise AccessError("Bootstrap records are immutable.")

    def unlink(self):
        raise AccessError("Bootstrap records are immutable.")


class DevRepository(models.Model):
    _inherit = "dev.repository"

    github_owner = fields.Char(readonly=True)
    github_repo_name = fields.Char(readonly=True)
    github_repository = fields.Char(readonly=True, index=True)
    bound_allowlist_id = fields.Many2one(
        "dev.github.repository.allowlist", readonly=True, ondelete="restrict"
    )
    origin_locked = fields.Boolean(default=True, required=True)
    bind_record_id = fields.Many2one(
        "dev.repository.bind.record", readonly=True, ondelete="restrict"
    )

    def assert_origin_immutable(self, proposed_remote_url=None):
        self.ensure_one()
        if not self.origin_locked:
            raise AccessError("Origin lock must remain enabled for bound repositories.")
        if proposed_remote_url is not None:
            provider, owner, repo = _parse_github_remote(proposed_remote_url)
            expected = self.github_repository or ""
            candidate = "%s/%s" % (owner, repo) if provider else ""
            if not expected or candidate != expected:
                raise AccessError(
                    "Agents cannot change origin to another repository."
                )
        return True


class DevProjectBindService(models.Model):
    _inherit = "dev.project"

    def _require_bind_manager(self):
        if not self.env.user.has_group("dev_session_hub.group_dev_hub_manager"):
            raise AccessError("Repository bind requires Dev Hub Manager.")

    def create_repository_bind_approval(self, discovery, installation, requester):
        self._require_bind_manager()
        discovery.ensure_one()
        installation.ensure_one()
        if discovery.state != "scanned" or discovery.requires_bootstrap:
            raise UserError("Bind requires a scanned non-bootstrap discovery.")
        if discovery.project_id != self:
            raise UserError("Discovery project mismatch.")
        github_repository = "%s/%s" % (discovery.owner, discovery.repo_name)
        if not GITHUB_REPO_RE.fullmatch(github_repository):
            raise ValidationError("Discovered repository identity is invalid.")
        allowlist = installation.assert_repository_authorized(github_repository)
        if requester == self.env.user:
            raise AccessError("Bind requester and approver must be distinct.")
        return (
            self.env["dev.repository.bind.approval"]
            .sudo()
            .with_context(
                dev_repository_bind_approval=True,
                dev_repository_bind_approval_hash=True,
            )
            .create(
                {
                    "discovery_id": discovery.id,
                    "project_id": self.id,
                    "local_path": discovery.local_path,
                    "github_repository": github_repository,
                    "remote_name": discovery.remote_name,
                    "installation_id": installation.id,
                    "allowlist_id": allowlist.id,
                    "requester_id": requester.id,
                    "approver_id": self.env.user.id,
                    "scan_digest": discovery.scan_digest,
                    "binding_hash": "pending",
                    "approved_at": fields.Datetime.now(),
                }
            )
        )

    def execute_repository_bind(self, approval):
        self._require_bind_manager()
        approval.ensure_one()
        approval.assert_integrity()
        if approval.event_ids:
            raise AccessError("Bind approval was already consumed.")
        if approval.approver_id != self.env.user:
            raise AccessError("Only the bind approver may execute the bind.")
        remotes = json.loads(approval.discovery_id.remotes_json or "{}")
        origin_url = remotes.get(approval.remote_name) or ""
        origin_url_hash = hashlib.sha256(origin_url.encode("utf-8")).hexdigest()
        repository = self.env["dev.repository"].search(
            [
                ("project_id", "=", self.id),
                ("working_directory", "=", approval.local_path),
            ],
            limit=1,
        )
        if not repository:
            repository = self.env["dev.repository"].create(
                {
                    "name": approval.github_repository,
                    "project_id": self.id,
                    "git_remote": origin_url or approval.github_repository,
                    "canonical_remote_path": approval.local_path,
                    "working_directory": approval.local_path,
                    "default_branch": approval.discovery_id.default_branch or "main",
                    "github_owner": approval.github_repository.split("/")[0],
                    "github_repo_name": approval.github_repository.split("/")[1],
                    "github_repository": approval.github_repository,
                    "bound_allowlist_id": approval.allowlist_id.id,
                    "origin_locked": True,
                }
            )
        else:
            repository.write(
                {
                    "github_owner": approval.github_repository.split("/")[0],
                    "github_repo_name": approval.github_repository.split("/")[1],
                    "github_repository": approval.github_repository,
                    "bound_allowlist_id": approval.allowlist_id.id,
                    "origin_locked": True,
                }
            )
        repository.assert_origin_immutable(origin_url or None)
        record = (
            self.env["dev.repository.bind.record"]
            .sudo()
            .with_context(dev_repository_bind_record=True)
            .create(
                {
                    "approval_id": approval.id,
                    "repository_id": repository.id,
                    "github_repository": approval.github_repository,
                    "local_path": approval.local_path,
                    "origin_url_hash": origin_url_hash,
                    "allowlist_id": approval.allowlist_id.id,
                    "result_state": "bound",
                    "audit_hash": "pending",
                }
            )
        )
        repository.write({"bind_record_id": record.id})
        self.env["dev.repository.bind.approval.event"].sudo().with_context(
            dev_repository_bind_event=True
        ).create(
            {
                "approval_id": approval.id,
                "event_type": "consumed",
                "note": "Repository bound to immutable identity.",
            }
        )
        return record

    def create_repository_bootstrap_approval(self, discovery, proposed_repo, requester):
        self._require_bind_manager()
        discovery.ensure_one()
        if not discovery.requires_bootstrap or discovery.state != "scanned":
            raise UserError("Bootstrap requires a scanned bootstrap-eligible discovery.")
        if not GITHUB_REPO_RE.fullmatch(proposed_repo or ""):
            raise ValidationError("proposed_github_repository must be owner/name.")
        if requester == self.env.user:
            raise AccessError("Bootstrap requester and approver must be distinct.")
        return (
            self.env["dev.repository.bootstrap.approval"]
            .sudo()
            .with_context(
                dev_repository_bootstrap_approval=True,
                dev_repository_bootstrap_hash=True,
            )
            .create(
                {
                    "discovery_id": discovery.id,
                    "project_id": self.id,
                    "local_path": discovery.local_path,
                    "proposed_github_repository": proposed_repo,
                    "secret_scan_digest": discovery.scan_digest or _canonical_hash(
                        {"path": discovery.local_path}
                    ),
                    "ownership_confirmed": True,
                    "requester_id": requester.id,
                    "approver_id": self.env.user.id,
                    "binding_hash": "pending",
                    "approved_at": fields.Datetime.now(),
                }
            )
        )

    def execute_repository_bootstrap(self, approval):
        self._require_bind_manager()
        approval.ensure_one()
        approval.assert_no_preapproval_upload()
        if approval.binding_hash != _canonical_hash(approval._binding()):
            raise AccessError("Bootstrap approval integrity check failed.")
        record = (
            self.env["dev.repository.bootstrap.record"]
            .sudo()
            .with_context(dev_repository_bootstrap_record=True)
            .create(
                {
                    "approval_id": approval.id,
                    "result_state": "approved_pending_push",
                    "code_uploaded": False,
                    "audit_hash": "pending",
                }
            )
        )
        self.env["dev.repository.bootstrap.approval.event"].sudo().with_context(
            dev_repository_bootstrap_event=True
        ).create(
            {
                "approval_id": approval.id,
                "event_type": "consumed",
                "note": "Bootstrap approved; push gate required before any upload.",
            }
        )
        return record
