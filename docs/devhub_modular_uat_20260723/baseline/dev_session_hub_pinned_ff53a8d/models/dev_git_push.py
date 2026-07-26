# -*- coding: utf-8 -*-
import hashlib
import json
import os
import re
import subprocess
from urllib.parse import urlsplit

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from .dev_execution import BRANCH_RE, SHA1_RE
from .dev_git_commit import _canonical_hash


REMOTE_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
REMOTE_HOST_RE = re.compile(r"^[A-Za-z0-9.-]{1,253}$")
SSH_USER_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
SCP_REMOTE_RE = re.compile(
    r"^(?P<user>[a-z_][a-z0-9_-]{0,31})@"
    r"(?P<host>[A-Za-z0-9.-]{1,253}):"
    r"(?P<path>[A-Za-z0-9._~/-]+)$"
)
PROTECTED_EXACT = {"main", "master", "production", "prod"}
PROTECTED_PREFIXES = ("release/", "production/", "prod/")


def _assert_clean_remote_path(path):
    if (
        not path
        or path in ("/", ".")
        or "\\" in path
        or any(character.isspace() or ord(character) < 32 for character in path)
        or ".." in path.split("/")
    ):
        raise ValidationError("Git remote repository path is invalid.")


def _validate_network_remote_url(protocol, url, allowed_ssh_user="git"):
    """Return the exact safe reference or fail without silently sanitizing it."""
    if not isinstance(url, str) or not url or url != url.strip():
        raise ValidationError("Git remote URL is malformed.")
    if any(ord(character) < 32 for character in url):
        raise ValidationError("Git remote URL contains control characters.")
    if protocol == "ssh" and "://" not in url:
        match = SCP_REMOTE_RE.fullmatch(url)
        if not match:
            raise ValidationError("SCP-style SSH remote is malformed.")
        if match.group("user") != allowed_ssh_user:
            raise ValidationError("SSH remote user is outside registered policy.")
        if not REMOTE_HOST_RE.fullmatch(match.group("host")):
            raise ValidationError("SSH remote host is invalid.")
        _assert_clean_remote_path(match.group("path"))
        return url
    try:
        parsed = urlsplit(url)
        parsed_port = parsed.port
    except (TypeError, ValueError):
        raise ValidationError("Git remote URL is malformed.")
    if parsed.scheme != protocol or not parsed.netloc or not parsed.hostname:
        raise ValidationError("Git remote protocol or host is invalid.")
    if not REMOTE_HOST_RE.fullmatch(parsed.hostname):
        raise ValidationError("Git remote host is invalid.")
    if parsed.query or parsed.fragment or "?" in url or "#" in url:
        raise ValidationError("Git remote URL query strings and fragments are forbidden.")
    if protocol == "https":
        if parsed.username is not None or parsed.password is not None or "@" in parsed.netloc:
            raise ValidationError("HTTPS remote userinfo and credentials are forbidden.")
    elif protocol == "ssh":
        if (
            parsed.username != allowed_ssh_user
            or parsed.password is not None
            or not SSH_USER_RE.fullmatch(parsed.username or "")
        ):
            raise ValidationError("SSH remote user is outside registered policy.")
    else:
        raise ValidationError("Unsupported network Git remote protocol.")
    if parsed_port is not None and not (1 <= parsed_port <= 65535):
        raise ValidationError("Git remote port is invalid.")
    _assert_clean_remote_path(parsed.path)
    return url


class DevGitRemote(models.Model):
    _name = "dev.git.remote"
    _description = "Registered Allowlisted Git Push Remote"
    _order = "repository_id, name"

    name = fields.Char(required=True, index=True)
    repository_id = fields.Many2one(
        "dev.repository", required=True, ondelete="restrict", index=True
    )
    remote_url = fields.Char(required=True)
    protocol = fields.Selection(
        [("file", "Local Test File"), ("ssh", "SSH"), ("https", "HTTPS")],
        required=True,
    )
    approved = fields.Boolean(default=False, required=True)
    non_production = fields.Boolean(default=True, required=True)
    allowed_branch_prefix = fields.Char(default="devhub/", required=True)
    protected_branch_patterns = fields.Text(
        default="main\nmaster\nproduction\nrelease/*"
    )
    allowed_ssh_user = fields.Char(default="git", required=True)
    credential_profile_reference = fields.Char()
    active = fields.Boolean(default=True)

    _name_repository_unique = models.Constraint(
        "unique(repository_id, name)", "Git remote name must be unique per repository."
    )

    @api.constrains(
        "name",
        "remote_url",
        "protocol",
        "approved",
        "repository_id",
        "allowed_branch_prefix",
        "allowed_ssh_user",
        "credential_profile_reference",
    )
    def _check_remote_policy(self):
        for record in self:
            if not REMOTE_NAME_RE.fullmatch(record.name or ""):
                raise ValidationError("Git remote name is invalid.")
            url = record.remote_url or ""
            if record.protocol == "file":
                root = os.path.realpath(record.repository_id.approved_push_root or "")
                target = os.path.realpath(url)
                if not root or not os.path.isabs(url):
                    raise ValidationError("File remotes require an approved absolute root.")
                try:
                    inside = os.path.commonpath((root, target)) == root
                except ValueError:
                    inside = False
                if not inside or target == root:
                    raise ValidationError("File remote escapes the approved push root.")
            else:
                if not SSH_USER_RE.fullmatch(record.allowed_ssh_user or ""):
                    raise ValidationError("Registered SSH user policy is invalid.")
                _validate_network_remote_url(
                    record.protocol, url, record.allowed_ssh_user
                )
                if record.protocol == "ssh":
                    profile = os.path.realpath(
                        record.credential_profile_reference or ""
                    )
                    if (
                        not re.fullmatch(r"/[A-Za-z0-9._/-]+", profile)
                        or not profile.startswith(
                            "/srv/devhub/credentials/github/"
                        )
                    ):
                        raise ValidationError(
                            "SSH Push requires a protected credential profile."
                        )
            if not (record.allowed_branch_prefix or "").startswith("devhub/"):
                raise ValidationError("Push branch policy must remain under devhub/.")

    def assert_push_allowed(self, branch):
        self.ensure_one()
        self._check_remote_policy()
        if not self.active or not self.approved or not self.non_production:
            raise AccessError("Git remote is not approved for non-production Push.")
        if not BRANCH_RE.fullmatch(branch or ""):
            raise AccessError("Only a dedicated Dev Hub branch may be pushed.")
        lowered = branch.casefold()
        protected = {
            line.strip().casefold()
            for line in (self.protected_branch_patterns or "").splitlines()
            if line.strip() and not line.strip().endswith("/*")
        }
        prefixes = tuple(
            line.strip()[:-1].casefold()
            for line in (self.protected_branch_patterns or "").splitlines()
            if line.strip().endswith("/*")
        )
        if (
            lowered in PROTECTED_EXACT
            or lowered in protected
            or lowered.startswith(PROTECTED_PREFIXES + prefixes)
            or not branch.startswith(self.allowed_branch_prefix)
        ):
            raise AccessError("Protected or non-Dev-Hub target branches cannot be pushed.")
        return True


class DevRepository(models.Model):
    _inherit = "dev.repository"

    approved_push_root = fields.Char()
    approved_push_remote_ids = fields.One2many(
        "dev.git.remote", "repository_id", readonly=True
    )


class DevGitPushApproval(models.Model):
    _name = "dev.git.push.approval"
    _description = "Immutable Human Git Push Approval"
    _order = "approved_at desc, id desc"

    work_item_id = fields.Many2one(
        "dev.work.item", required=True, readonly=True, ondelete="restrict", index=True
    )
    workspace_id = fields.Many2one(
        "dev.execution.workspace",
        required=True,
        readonly=True,
        ondelete="restrict",
        index=True,
    )
    repository_id = fields.Many2one(
        "dev.repository", required=True, readonly=True, ondelete="restrict"
    )
    local_branch = fields.Char(required=True, readonly=True)
    local_head = fields.Char(required=True, readonly=True)
    commit_sha = fields.Char(required=True, readonly=True)
    remote_id = fields.Many2one(
        "dev.git.remote", required=True, readonly=True, ondelete="restrict"
    )
    remote_name = fields.Char(required=True, readonly=True)
    remote_url_reference = fields.Char(required=True, readonly=True)
    remote_branch = fields.Char(required=True, readonly=True)
    remote_head_before = fields.Char(readonly=True)
    remote_heads_json = fields.Text(required=True, readonly=True)
    remote_heads_digest = fields.Char(required=True, readonly=True)
    remote_tags_json = fields.Text(required=True, readonly=True)
    remote_tags_digest = fields.Char(required=True, readonly=True)
    policy_hash = fields.Char(required=True, readonly=True)
    execution_contract_hash = fields.Char(required=True, readonly=True)
    approver_id = fields.Many2one(
        "res.users", required=True, readonly=True, ondelete="restrict"
    )
    approved_at = fields.Datetime(required=True, readonly=True)
    push_mode = fields.Selection(
        [("normal", "Normal Non-Force Push")], required=True, readonly=True
    )
    binding_hash = fields.Char(required=True, readonly=True, copy=False, index=True)
    event_ids = fields.One2many(
        "dev.git.push.approval.event", "approval_id", readonly=True
    )
    approval_state = fields.Char(compute="_compute_state")

    @api.depends("event_ids.event_type")
    def _compute_state(self):
        for record in self:
            record.approval_state = (
                record.event_ids.sorted(lambda item: item.id, reverse=True)[:1].event_type
                if record.event_ids
                else "approved"
            )

    def _binding(self):
        self.ensure_one()
        return {
            name: self[name].id
            if self._fields[name].type == "many2one"
            else fields.Datetime.to_string(self[name])
            if self._fields[name].type == "datetime"
            else self[name] or ""
            for name in (
                "work_item_id",
                "workspace_id",
                "repository_id",
                "local_branch",
                "local_head",
                "commit_sha",
                "remote_id",
                "remote_name",
                "remote_url_reference",
                "remote_branch",
                "remote_head_before",
                "remote_heads_digest",
                "remote_tags_digest",
                "policy_hash",
                "execution_contract_hash",
                "approver_id",
                "approved_at",
                "push_mode",
            )
        }

    def assert_integrity(self):
        for record in self:
            if record.binding_hash != _canonical_hash(record._binding()):
                raise AccessError("Push approval integrity validation failed.")
        return True

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("dev_git_push_approval"):
            raise AccessError("Push approvals require guarded human review.")
        records = super().create(vals_list)
        for record in records:
            super(DevGitPushApproval, record).write(
                {"binding_hash": _canonical_hash(record._binding())}
            )
        return records

    def write(self, values):
        raise AccessError("Git Push approvals are immutable.")

    def unlink(self):
        raise AccessError("Git Push approvals are retained for audit.")


class DevGitPushApprovalEvent(models.Model):
    _name = "dev.git.push.approval.event"
    _description = "Immutable Git Push Approval Event"

    approval_id = fields.Many2one(
        "dev.git.push.approval", required=True, readonly=True, ondelete="restrict"
    )
    event_type = fields.Selection(
        [
            ("rejected", "Rejected"),
            ("superseded", "Superseded"),
            ("consumed", "Consumed"),
            ("reconciled_success", "Reconciled Success"),
            ("reconciled_failure", "Reconciled Failure"),
            ("uncertain_remote_state", "Uncertain Remote State"),
        ],
        required=True,
        readonly=True,
    )
    occurred_at = fields.Datetime(default=fields.Datetime.now, required=True, readonly=True)
    actor_id = fields.Many2one(
        "res.users", default=lambda self: self.env.user, required=True, readonly=True
    )
    summary = fields.Char(required=True, readonly=True)
    payload_json = fields.Text(readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("dev_git_push_event"):
            raise AccessError("Push approval events require a guarded action.")
        return super().create(vals_list)

    def write(self, values):
        raise AccessError("Push approval events are immutable.")

    def unlink(self):
        raise AccessError("Push approval events are retained for audit.")


class DevGitPushRecord(models.Model):
    _name = "dev.git.push.record"
    _description = "Immutable Reviewed Git Push Record"

    work_item_id = fields.Many2one("dev.work.item", required=True, readonly=True)
    workspace_id = fields.Many2one("dev.execution.workspace", required=True, readonly=True)
    approval_id = fields.Many2one("dev.git.push.approval", required=True, readonly=True)
    remote_id = fields.Many2one("dev.git.remote", required=True, readonly=True)
    local_branch = fields.Char(required=True, readonly=True)
    remote_branch = fields.Char(required=True, readonly=True)
    commit_sha = fields.Char(required=True, readonly=True)
    remote_head_before = fields.Char(readonly=True)
    remote_head_after = fields.Char(readonly=True)
    approver_id = fields.Many2one("res.users", required=True, readonly=True)
    pushed_at = fields.Datetime(required=True, readonly=True)
    result = fields.Char(required=True, readonly=True)
    verification_result = fields.Char(required=True, readonly=True)
    reconciliation_state = fields.Selection(
        [
            ("pushed", "Pushed"),
            ("reconciled_success", "Reconciled Success"),
            ("push_failed_review", "Push Failed — Review Required"),
            ("uncertain_remote_state", "Uncertain Remote State"),
        ],
        required=True,
        readonly=True,
    )
    approved_pre_refs_digest = fields.Char(required=True, readonly=True)
    expected_remote_head = fields.Char(required=True, readonly=True)
    observed_post_refs_digest = fields.Char(readonly=True)
    reconciled_at = fields.Datetime(required=True, readonly=True)
    reconciliation_result = fields.Text(required=True, readonly=True)
    audit_hash = fields.Char(required=True, readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("dev_git_push_record"):
            raise AccessError("Push records require guarded execution.")
        for vals in vals_list:
            vals.setdefault("audit_hash", "pending")
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
                    "remote_id",
                    "local_branch",
                    "remote_branch",
                    "commit_sha",
                    "remote_head_before",
                    "remote_head_after",
                    "approver_id",
                    "pushed_at",
                    "result",
                    "verification_result",
                    "reconciliation_state",
                    "approved_pre_refs_digest",
                    "expected_remote_head",
                    "observed_post_refs_digest",
                    "reconciled_at",
                    "reconciliation_result",
                )
            }
            super(DevGitPushRecord, record).write({"audit_hash": _canonical_hash(payload)})
        return records

    def write(self, values):
        raise AccessError("Git Push records are immutable.")

    def unlink(self):
        raise AccessError("Git Push records are retained for audit.")


class DevExecutionWorkspace(models.Model):
    _inherit = "dev.execution.workspace"

    push_remote_id = fields.Many2one("dev.git.remote", readonly=True)
    push_remote_branch = fields.Char(readonly=True)
    push_remote_head = fields.Char(readonly=True)
    push_ahead_count = fields.Integer(readonly=True)
    push_behind_count = fields.Integer(readonly=True)
    last_remote_check_at = fields.Datetime(readonly=True)
    push_approval_id = fields.Many2one("dev.git.push.approval", readonly=True)
    push_record_id = fields.Many2one("dev.git.push.record", readonly=True)
    pushed_at = fields.Datetime(readonly=True)

    def _require_push_manager(self):
        if not self.env.user.has_group("dev_session_hub.group_dev_hub_manager"):
            raise AccessError("Only a Dev Hub manager may authorize Git Push.")

    def _assert_canonical_push_args(self, args):
        self.ensure_one()
        if not args or args[0] != "push":
            return True
        for argument in args[1:]:
            lowered = argument.casefold()
            if (
                argument == "-f"
                or lowered.startswith("--force")
                or lowered == "--force-if-includes"
                or argument.startswith("+")
            ):
                raise AccessError("Every force-Push syntax is forbidden.")
        if len(args) != 4 or args[1] != "--porcelain":
            raise AccessError("Only the internally constructed exact Push is permitted.")
        if not REMOTE_NAME_RE.fullmatch(args[2]):
            raise AccessError("Push remote name is invalid.")
        match = re.fullmatch(
            r"refs/heads/(?P<source>[^:]+):refs/heads/(?P<target>[^:]+)",
            args[3],
        )
        if (
            not match
            or not BRANCH_RE.fullmatch(match.group("source"))
            or not BRANCH_RE.fullmatch(match.group("target"))
        ):
            raise AccessError("Push refspec must be one normal explicit branch mapping.")
        return True

    def _run_push_git(self, args, check=True):
        self.ensure_one()
        self._assert_canonical_push_args(args)
        environment = {
            "PATH": "/usr/bin:/bin",
            "HOME": "/nonexistent",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
            "LANG": "C",
        }
        remotes = self.env["dev.git.remote"].search(
            [("repository_id", "=", self.repository_id.id), ("active", "=", True)]
        )
        selected = remotes.filtered(lambda remote: remote.name in args)
        if len(selected) > 1:
            raise AccessError("Git operation may reference only one registered remote.")
        if selected and selected.protocol == "ssh":
            selected.assert_push_allowed(self.execution_branch)
            environment["GIT_SSH_COMMAND"] = "/usr/bin/ssh -F %s" % os.path.realpath(
                selected.credential_profile_reference
            )
        result = subprocess.run(
            [
                "git",
                "-c",
                "safe.directory=%s" % os.path.realpath(self.worktree_path),
                "-C",
                self.worktree_path,
                *args,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=90,
            check=False,
            env=environment,
        )
        if check and result.returncode:
            raise UserError(
                "Git Push operation failed safely: %s"
                % result.stderr.decode("utf-8", "replace")[:1000]
            )
        return result

    def _remote_snapshot(self, remote):
        self.ensure_one()
        output = self._run_push_git(
            ["ls-remote", "--heads", "--tags", remote.name]
        ).stdout.decode("utf-8", "strict")
        heads, tags = {}, {}
        for line in output.splitlines():
            parts = line.split("\t")
            if len(parts) != 2 or not SHA1_RE.fullmatch(parts[0]):
                raise UserError("Remote returned malformed reference data.")
            ref = parts[1]
            if ref.startswith("refs/heads/"):
                heads[ref[11:]] = parts[0]
            elif ref.startswith("refs/tags/"):
                tags[ref[10:]] = parts[0]
            else:
                raise UserError("Remote returned an unexpected reference namespace.")
        return {
            "heads": heads,
            "tags": tags,
            "heads_json": json.dumps(heads, sort_keys=True),
            "tags_json": json.dumps(tags, sort_keys=True),
            "heads_digest": _canonical_hash(heads),
            "tags_digest": _canonical_hash(tags),
            "target_head": heads.get(self.execution_branch),
        }

    def _assert_push_base(self, remote):
        self.ensure_one()
        self._require_push_manager()
        if self.state not in ("committed_reviewed", "push_approved"):
            raise AccessError("Push requires a committed reviewed workspace.")
        self._assert_no_worker_lease()
        self._assert_worker_identity(require_effective=True)
        self._assert_plan_unchanged()
        self.environment_id._assert_dev_hub_safe(self.project_id)
        self._validate_physical()
        if self.dirty_summary != "changed=0":
            raise AccessError("Dirty worktrees cannot be pushed.")
        if not self.commit_record_id or self.current_head != self.committed_sha:
            raise AccessError("Reviewed commit identity no longer matches local HEAD.")
        if self.execution_branch != self.commit_record_id.branch:
            raise AccessError("Local branch changed after commit review.")
        if remote.repository_id != self.repository_id:
            raise AccessError("Push remote is not registered for this repository.")
        remote.assert_push_allowed(self.execution_branch)
        configured = (
            self._run_push_git(["remote", "get-url", remote.name])
            .stdout.decode()
            .strip()
        )
        if configured != remote.remote_url:
            raise AccessError("Configured Git remote differs from the registered remote.")
        return True

    def action_review_push_target(self):
        self.ensure_one()
        remotes = self.repository_id.approved_push_remote_ids.filtered(
            lambda item: item.active and item.approved and item.non_production
        )
        if len(remotes) != 1:
            raise UserError("Exactly one approved non-production Push remote is required.")
        remote = remotes
        self._assert_push_base(remote)
        self._run_push_git(["fetch", "--no-tags", "--prune", remote.name])
        snapshot = self._remote_snapshot(remote)
        remote_head = snapshot["target_head"]
        ahead = 1
        behind = 0
        if remote_head:
            ancestor = self._run_push_git(
                ["merge-base", "--is-ancestor", remote_head, self.current_head],
                check=False,
            )
            if ancestor.returncode:
                raise AccessError("Remote target is not a fast-forward ancestor.")
            ahead = int(
                self._run_push_git(
                    ["rev-list", "--count", "%s..%s" % (remote_head, self.current_head)]
                ).stdout.decode()
            )
        self.sudo()._internal_write(
            {
                "push_remote_id": remote.id,
                "push_remote_branch": self.execution_branch,
                "push_remote_head": remote_head,
                "push_ahead_count": ahead,
                "push_behind_count": behind,
                "last_remote_check_at": fields.Datetime.now(),
            }
        )
        self._event("push_reviewed", "Human reviewed exact registered Push target")
        return self._form_action()

    def action_open_push_approval(self):
        self.ensure_one()
        self.action_review_push_target()
        return {
            "type": "ir.actions.act_window",
            "name": "Approve Git Push",
            "res_model": "dev.git.push.approval.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_workspace_id": self.id,
                "default_remote_id": self.push_remote_id.id,
            },
        }

    def create_push_approval(self, remote):
        self.ensure_one()
        if self.state != "committed_reviewed":
            raise AccessError("Fresh Push approval requires Committed Reviewed state.")
        self._assert_push_base(remote)
        self._run_push_git(["fetch", "--no-tags", "--prune", remote.name])
        snapshot = self._remote_snapshot(remote)
        if snapshot["target_head"]:
            if self._run_push_git(
                ["merge-base", "--is-ancestor", snapshot["target_head"], self.current_head],
                check=False,
            ).returncode:
                raise AccessError("Non-fast-forward Push is forbidden.")
        approval = self.env["dev.git.push.approval"].sudo().with_context(
            dev_git_push_approval=True
        ).create(
            {
                "work_item_id": self.work_item_id.id,
                "workspace_id": self.id,
                "repository_id": self.repository_id.id,
                "local_branch": self.execution_branch,
                "local_head": self.current_head,
                "commit_sha": self.committed_sha,
                "remote_id": remote.id,
                "remote_name": remote.name,
                "remote_url_reference": remote.remote_url,
                "remote_branch": self.execution_branch,
                "remote_head_before": snapshot["target_head"],
                "remote_heads_json": snapshot["heads_json"],
                "remote_heads_digest": snapshot["heads_digest"],
                "remote_tags_json": snapshot["tags_json"],
                "remote_tags_digest": snapshot["tags_digest"],
                "policy_hash": self.policy_hash,
                "execution_contract_hash": self.execution_contract_hash,
                "approver_id": self.env.user.id,
                "approved_at": fields.Datetime.now(),
                "push_mode": "normal",
                "binding_hash": "pending",
            }
        )
        self.sudo()._internal_write(
            {"state": "push_approved", "push_approval_id": approval.id}
        )
        self._event(
            "push_approved",
            "Human approved one exact normal non-force Push",
            {"approval_id": approval.id},
        )
        return approval

    def _assert_push_approval_current(self, approval):
        self.ensure_one()
        if not approval or approval.event_ids:
            raise AccessError("A current immutable Push approval is required.")
        approval.assert_integrity()
        self._assert_push_base(approval.remote_id)
        expected = {
            "local branch": (self.execution_branch, approval.local_branch),
            "local HEAD": (self.current_head, approval.local_head),
            "commit SHA": (self.committed_sha, approval.commit_sha),
            "remote": (approval.remote_id.name, approval.remote_name),
            "remote URL": (approval.remote_id.remote_url, approval.remote_url_reference),
            "remote branch": (self.execution_branch, approval.remote_branch),
            "policy hash": (self.policy_hash, approval.policy_hash),
            "contract hash": (
                self.execution_contract_hash,
                approval.execution_contract_hash,
            ),
        }
        mismatch = [name for name, pair in expected.items() if pair[0] != pair[1]]
        if mismatch:
            raise AccessError(
                "Push approval is stale; fresh review required (%s)."
                % ", ".join(mismatch)
            )
        return True

    def action_open_push_execution(self):
        self.ensure_one()
        self._assert_push_approval_current(self.push_approval_id)
        return {
            "type": "ir.actions.act_window",
            "name": "Confirm Approved Git Push",
            "res_model": "dev.git.push.execution.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_workspace_id": self.id,
                "default_approval_id": self.push_approval_id.id,
            },
        }

    def _record_push_reconciliation(
        self, approval, before, after, reconciliation_state, main_before
    ):
        self.ensure_one()
        reconciled_at = fields.Datetime.now()
        observed_head = after["target_head"] if after else False
        observed_digest = after["heads_digest"] if after else False
        expected = approval.commit_sha
        if reconciliation_state == "uncertain_remote_state":
            result = "uncertain_remote_state"
            explanation = (
                "Expected remote HEAD %s; remote state could not be determined. "
                "No retry is permitted without human reconciliation." % expected
            )
            event_type = "uncertain_remote_state"
        else:
            result = "push_failed_review"
            explanation = (
                "Expected remote HEAD %s; observed %s. Push was not delivered "
                "as approved and requires human review."
                % (expected, observed_head or "absent")
            )
            event_type = "reconciled_failure"
        local_unchanged = True
        main_unchanged = True
        try:
            self._validate_physical()
            local_unchanged = (
                self.current_head == approval.commit_sha
                and self.dirty_summary == "changed=0"
            )
            main_unchanged = self._main_snapshot(self.repository_id) == main_before
        except Exception:
            local_unchanged = False
            main_unchanged = False
        explanation += " Local unchanged=%s; main unchanged=%s." % (
            local_unchanged,
            main_unchanged,
        )
        record = self.env["dev.git.push.record"].sudo().with_context(
            dev_git_push_record=True
        ).create(
            {
                "work_item_id": self.work_item_id.id,
                "workspace_id": self.id,
                "approval_id": approval.id,
                "remote_id": approval.remote_id.id,
                "local_branch": approval.local_branch,
                "remote_branch": approval.remote_branch,
                "commit_sha": approval.commit_sha,
                "remote_head_before": approval.remote_head_before,
                "remote_head_after": observed_head,
                "approver_id": approval.approver_id.id,
                "pushed_at": reconciled_at,
                "result": result,
                "verification_result": explanation,
                "reconciliation_state": reconciliation_state,
                "approved_pre_refs_digest": approval.remote_heads_digest,
                "expected_remote_head": expected,
                "observed_post_refs_digest": observed_digest,
                "reconciled_at": reconciled_at,
                "reconciliation_result": explanation,
            }
        )
        self.env["dev.git.push.approval.event"].sudo().with_context(
            dev_git_push_event=True
        ).create(
            {
                "approval_id": approval.id,
                "event_type": event_type,
                "actor_id": self.env.user.id,
                "summary": explanation[:240],
                "payload_json": json.dumps(
                    {
                        "approved_pre_refs_digest": approval.remote_heads_digest,
                        "expected_remote_head": expected,
                        "observed_post_refs_digest": observed_digest,
                        "observed_remote_head": observed_head,
                        "reconciled_at": fields.Datetime.to_string(reconciled_at),
                        "reconciliation_state": reconciliation_state,
                    },
                    sort_keys=True,
                ),
            }
        )
        self.sudo()._internal_write(
            {
                "state": reconciliation_state,
                "push_record_id": record.id,
                "push_approval_id": False,
                "push_remote_head": observed_head,
                "last_remote_check_at": reconciled_at,
            }
        )
        self._event(
            event_type,
            explanation[:240],
            {"push_record_id": record.id},
        )
        return record

    def action_review_failed_push(self):
        self.ensure_one()
        self._require_push_manager()
        if self.state not in ("push_failed_review", "uncertain_remote_state"):
            raise AccessError("Only a failed or uncertain Push may be reconciled.")
        self._assert_no_worker_lease()
        self._assert_worker_identity(require_effective=True)
        self._assert_plan_unchanged()
        self.environment_id._assert_dev_hub_safe(self.project_id)
        self._validate_physical()
        failed_record = self.push_record_id
        approval = failed_record.approval_id
        if (
            not failed_record
            or not approval
            or self.current_head != approval.commit_sha
            or self.dirty_summary != "changed=0"
        ):
            raise AccessError("Local reviewed commit changed after the Push attempt.")
        remote = approval.remote_id
        remote.assert_push_allowed(approval.remote_branch)
        configured = (
            self._run_push_git(["remote", "get-url", remote.name])
            .stdout.decode()
            .strip()
        )
        if configured != approval.remote_url_reference:
            raise AccessError("Registered remote changed after the Push attempt.")
        self._run_push_git(["fetch", "--no-tags", "--prune", remote.name])
        snapshot = self._remote_snapshot(remote)
        expected_heads = json.loads(approval.remote_heads_json)
        expected_heads[approval.remote_branch] = approval.commit_sha
        exact = (
            snapshot["heads"] == expected_heads
            and snapshot["tags"] == json.loads(approval.remote_tags_json)
            and snapshot["target_head"] == approval.commit_sha
        )
        reconciled_at = fields.Datetime.now()
        event_type = "reconciled_success" if exact else "reconciled_failure"
        explanation = (
            "Human reconciliation verified the exact approved remote state."
            if exact
            else "Human reconciliation verified that the exact approved remote state is absent."
        )
        self.env["dev.git.push.approval.event"].sudo().with_context(
            dev_git_push_event=True
        ).create(
            {
                "approval_id": approval.id,
                "event_type": event_type,
                "actor_id": self.env.user.id,
                "summary": explanation,
                "payload_json": json.dumps(
                    {
                        "expected_remote_head": approval.commit_sha,
                        "observed_remote_head": snapshot["target_head"],
                        "observed_post_refs_digest": snapshot["heads_digest"],
                        "reconciled_at": fields.Datetime.to_string(reconciled_at),
                    },
                    sort_keys=True,
                ),
            }
        )
        if exact:
            record = self.env["dev.git.push.record"].sudo().with_context(
                dev_git_push_record=True
            ).create(
                {
                    "work_item_id": self.work_item_id.id,
                    "workspace_id": self.id,
                    "approval_id": approval.id,
                    "remote_id": remote.id,
                    "local_branch": approval.local_branch,
                    "remote_branch": approval.remote_branch,
                    "commit_sha": approval.commit_sha,
                    "remote_head_before": approval.remote_head_before,
                    "remote_head_after": snapshot["target_head"],
                    "approver_id": approval.approver_id.id,
                    "pushed_at": reconciled_at,
                    "result": "reconciled_success",
                    "verification_result": explanation,
                    "reconciliation_state": "reconciled_success",
                    "approved_pre_refs_digest": approval.remote_heads_digest,
                    "expected_remote_head": approval.commit_sha,
                    "observed_post_refs_digest": snapshot["heads_digest"],
                    "reconciled_at": reconciled_at,
                    "reconciliation_result": explanation,
                }
            )
            values = {
                "state": "pushed_reviewed",
                "push_record_id": record.id,
                "pushed_at": reconciled_at,
            }
        else:
            values = {
                "state": "committed_reviewed",
                "push_approval_id": False,
            }
        values.update(
            {
                "push_remote_head": snapshot["target_head"],
                "last_remote_check_at": reconciled_at,
            }
        )
        self.sudo()._internal_write(values)
        self._event(event_type, explanation, {"failed_record_id": failed_record.id})
        return self._form_action()

    def execute_approved_push(self, approval):
        self.ensure_one()
        self.env.cr.execute(
            "SELECT id FROM dev_execution_workspace WHERE id = %s FOR UPDATE NOWAIT",
            [self.id],
        )
        self._assert_push_approval_current(approval)
        remote = approval.remote_id
        main_before = self._main_snapshot(self.repository_id)
        self._run_push_git(["fetch", "--no-tags", "--prune", remote.name])
        before = self._remote_snapshot(remote)
        if (
            before["heads_digest"] != approval.remote_heads_digest
            or before["tags_digest"] != approval.remote_tags_digest
            or (before["target_head"] or False)
            != (approval.remote_head_before or False)
        ):
            raise AccessError("Remote changed after approval; fresh Push review is required.")
        if before["target_head"] and self._run_push_git(
            ["merge-base", "--is-ancestor", before["target_head"], self.current_head],
            check=False,
        ).returncode:
            raise AccessError("Non-fast-forward Push is forbidden.")
        refspec = "refs/heads/%s:refs/heads/%s" % (
            approval.local_branch,
            approval.remote_branch,
        )
        push_result = self._run_push_git(
            ["push", "--porcelain", remote.name, refspec], check=False
        )
        try:
            after = self._remote_snapshot(remote)
        except Exception:
            after = None
        expected_heads = json.loads(approval.remote_heads_json)
        expected_heads[approval.remote_branch] = approval.commit_sha
        reconciled_exact = (
            bool(after)
            and after["heads"] == expected_heads
            and after["tags"] == json.loads(approval.remote_tags_json)
            and after["target_head"] == approval.commit_sha
        )
        if push_result.returncode and not reconciled_exact:
            return self._record_push_reconciliation(
                approval,
                before,
                after,
                "push_failed_review" if after else "uncertain_remote_state",
                main_before,
            )
        if not after:
            return self._record_push_reconciliation(
                approval,
                before,
                False,
                "uncertain_remote_state",
                main_before,
            )
        if (
            after["heads"] != expected_heads
            or after["tags"] != json.loads(approval.remote_tags_json)
            or after["target_head"] != approval.commit_sha
        ):
            return self._record_push_reconciliation(
                approval,
                before,
                after,
                "push_failed_review",
                main_before,
            )
        self._validate_physical()
        if self.current_head != approval.commit_sha or self.dirty_summary != "changed=0":
            raise UserError("Local workspace changed during Push.")
        if self._main_snapshot(self.repository_id) != main_before:
            raise UserError("Main worktree changed during Push; reconciliation required.")
        pushed_at = fields.Datetime.now()
        record = self.env["dev.git.push.record"].sudo().with_context(
            dev_git_push_record=True
        ).create(
            {
                "work_item_id": self.work_item_id.id,
                "workspace_id": self.id,
                "approval_id": approval.id,
                "remote_id": remote.id,
                "local_branch": approval.local_branch,
                "remote_branch": approval.remote_branch,
                "commit_sha": approval.commit_sha,
                "remote_head_before": approval.remote_head_before,
                "remote_head_after": after["target_head"],
                "approver_id": approval.approver_id.id,
                "pushed_at": pushed_at,
                "result": "success",
                "verification_result": "exact branch updated; other heads/tags unchanged",
                "reconciliation_state": (
                    "reconciled_success" if push_result.returncode else "pushed"
                ),
                "approved_pre_refs_digest": approval.remote_heads_digest,
                "expected_remote_head": approval.commit_sha,
                "observed_post_refs_digest": after["heads_digest"],
                "reconciled_at": pushed_at,
                "reconciliation_result": (
                    "Push subprocess reported failure, but exact expected remote "
                    "state was independently verified."
                    if push_result.returncode
                    else "Push succeeded and exact expected remote state was verified."
                ),
            }
        )
        self.env["dev.git.push.approval.event"].sudo().with_context(
            dev_git_push_event=True
        ).create(
            {
                "approval_id": approval.id,
                "event_type": (
                    "reconciled_success" if push_result.returncode else "consumed"
                ),
                "actor_id": self.env.user.id,
                "summary": "Exact Push approval consumed by one normal Push",
                "payload_json": json.dumps({"commit_sha": approval.commit_sha}),
            }
        )
        self.sudo()._internal_write(
            {
                "state": "pushed_reviewed",
                "push_record_id": record.id,
                "pushed_at": pushed_at,
                "push_remote_head": after["target_head"],
                "last_remote_check_at": pushed_at,
            }
        )
        self._event(
            "push_verified",
            "One human-approved branch Push verified; no PR created",
            {"push_record_id": record.id, "commit_sha": approval.commit_sha},
        )
        return record
