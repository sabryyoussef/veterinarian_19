# -*- coding: utf-8 -*-
import hashlib
import json
import os
import re
import socket
import subprocess
import uuid
from urllib.parse import quote

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


ACTIVE_STATES = ("started", "in_progress", "resumed")
TERMINAL_STATES = ("completed", "abandoned")
IMMUTABLE_SESSION_FIELDS = {
    "state",
    "git_branch_snapshot",
    "git_head_snapshot",
    "dirty_state_summary",
    "started_at",
    "paused_at",
    "resumed_at",
    "completed_at",
    "active_client_id",
    "manifest_revision",
    "manifest_json",
    "drift_warning",
}
TARGET_SESSION_FIELDS = {
    "user_id",
    "session_type",
    "execution_workspace_id",
    "project_id",
    "environment_id",
    "machine_id",
    "repository_id",
    "working_directory",
    "work_item_id",
    "task_link_id",
}
TRANSITIONS = {
    "draft": {"started", "abandoned"},
    "started": {"in_progress", "paused", "blocked", "abandoned"},
    "in_progress": {"paused", "completed", "blocked", "abandoned"},
    "paused": {"resumed", "blocked", "abandoned"},
    "resumed": {"in_progress", "paused", "completed", "blocked", "abandoned"},
    "blocked": {"resumed", "abandoned"},
    "completed": set(),
    "abandoned": set(),
}
SENSITIVE_TEXT = re.compile(
    r"(?i)(authorization\s*[\"']?\s*[:=]|bearer\s+[A-Za-z0-9._~+/-]+|"
    r"(?:password|passwd|pwd|token|secret|api[_-]?key|private[_-]?key)"
    r"\s*[\"']?\s*[:=]|"
    r"[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s@]+@|"
    r"-----BEGIN (?:OPENSSH |RSA |EC |DSA |ENCRYPTED )?PRIVATE KEY-----)"
)
SSH_ALIAS = re.compile(r"^[A-Za-z0-9._-]+$")
GIT_BRANCH = re.compile(r"^(?:DETACHED|[A-Za-z0-9._/-]{1,255})$")
GIT_HEAD = re.compile(r"^[0-9a-fA-F]{40,64}$")
MANIFEST_UNSAFE = re.compile(r"[^A-Za-z0-9 ._:/@#()+,\-]")
GIT_EXECUTABLE = "/usr/bin/git"
GIT_ENV = {
    "PATH": "/usr/bin:/bin",
    "HOME": "/nonexistent",
    "LANG": "C",
    "LC_ALL": "C",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_OPTIONAL_LOCKS": "0",
    "GIT_TERMINAL_PROMPT": "0",
}
GIT_SAFE_OPTIONS = (
    "-c",
    "core.fsmonitor=false",
    "-c",
    "core.hooksPath=/dev/null",
    "-c",
    "credential.helper=",
    "-c",
    "diff.external=",
    "-c",
    "core.pager=cat",
    "-c",
    "core.attributesFile=/dev/null",
    "-c",
    "protocol.file.allow=never",
    "--no-pager",
)


class DevSession(models.Model):
    _name = "dev.session"
    _description = "Development Session"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "write_date desc, id desc"

    name = fields.Char(required=True, default="New Development Session", tracking=True)
    user_id = fields.Many2one(
        "res.users",
        required=True,
        default=lambda self: self.env.user,
        ondelete="restrict",
        index=True,
        tracking=True,
    )
    client_id = fields.Many2one(
        "dev.client", required=True, ondelete="restrict", tracking=True
    )
    project_id = fields.Many2one(
        "dev.project", required=True, ondelete="restrict", index=True, tracking=True
    )
    environment_id = fields.Many2one(
        "dev.environment",
        required=True,
        ondelete="restrict",
        index=True,
        tracking=True,
    )
    machine_id = fields.Many2one(
        "dev.machine", required=True, ondelete="restrict", index=True, tracking=True
    )
    repository_id = fields.Many2one(
        "dev.repository",
        required=True,
        ondelete="restrict",
        index=True,
        tracking=True,
    )
    working_directory = fields.Char(required=True, tracking=True)
    git_branch_snapshot = fields.Char(readonly=True)
    git_head_snapshot = fields.Char(readonly=True)
    dirty_state_summary = fields.Char(readonly=True)
    task_link_id = fields.Many2one(
        "dev.task.link", ondelete="restrict", index=True, tracking=True
    )
    work_item_id = fields.Many2one(
        "dev.work.item",
        string="Work Item",
        ondelete="restrict",
        index=True,
        tracking=True,
        help="Canonical lifecycle identity. Legacy Task Link remains read-only fallback.",
    )
    session_type = fields.Selection(
        [
            ("manual_developer_session", "Manual Developer Session"),
            ("isolated_execution_workspace", "Isolated Execution Workspace"),
        ],
        default="manual_developer_session",
        required=True,
        tracking=True,
    )
    execution_workspace_id = fields.Many2one(
        "dev.execution.workspace",
        string="Execution Workspace",
        ondelete="restrict",
        index=True,
        tracking=True,
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("started", "Started"),
            ("in_progress", "In Progress"),
            ("paused", "Paused"),
            ("resumed", "Resumed"),
            ("completed", "Completed"),
            ("blocked", "Blocked"),
            ("abandoned", "Abandoned"),
        ],
        default="draft",
        required=True,
        index=True,
        readonly=True,
        tracking=True,
    )
    started_at = fields.Datetime(readonly=True)
    paused_at = fields.Datetime(readonly=True)
    resumed_at = fields.Datetime(readonly=True)
    completed_at = fields.Datetime(readonly=True)
    active_client_id = fields.Many2one("dev.client", readonly=True, ondelete="restrict")
    last_note = fields.Text(tracking=True)
    cursor_agent_thread_id = fields.Char(
        string="Cursor Agent Thread ID",
        help="Optional opaque identifier only; no transcript content.",
    )
    manifest_revision = fields.Char(readonly=True, copy=False)
    manifest_json = fields.Text(readonly=True, copy=False)
    drift_warning = fields.Text(readonly=True, copy=False)
    event_ids = fields.One2many("dev.session.event", "session_id", readonly=True)

    @api.onchange("project_id")
    def _onchange_project_id(self):
        if self.project_id:
            self.repository_id = self.project_id.default_repository_id
            self.environment_id = self.project_id.default_environment_id

    @api.onchange("environment_id")
    def _onchange_environment_id(self):
        if self.environment_id:
            self.machine_id = self.environment_id.machine_id

    @api.onchange("repository_id")
    def _onchange_repository_id(self):
        if self.repository_id:
            self.working_directory = self.repository_id.working_directory

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("state", "draft") != "draft":
                raise ValidationError("Sessions must be created in Draft state.")
            initial_work = (
                self.env["dev.work.item"].browse(vals.get("work_item_id")).exists()
                if vals.get("work_item_id")
                else self.env["dev.work.item"]
            )
            if (
                initial_work
                and initial_work.execution_workspace_id
                and not vals.get("execution_workspace_id")
                and "session_type" not in vals
            ):
                vals["execution_workspace_id"] = initial_work.execution_workspace_id.id
            workspace = (
                self.env["dev.execution.workspace"]
                .browse(vals.get("execution_workspace_id"))
                .exists()
                if vals.get("execution_workspace_id")
                else self.env["dev.execution.workspace"]
            )
            if vals.get("session_type") == "isolated_execution_workspace" and not workspace:
                raise ValidationError(
                    "An isolated execution session requires its canonical workspace."
                )
            if workspace:
                if workspace.state not in ("ready", "paused"):
                    raise ValidationError("The execution workspace is not ready for a session.")
                derived = {
                    "session_type": "isolated_execution_workspace",
                    "work_item_id": workspace.work_item_id.id,
                    "project_id": workspace.project_id.id,
                    "environment_id": workspace.environment_id.id,
                    "machine_id": workspace.machine_id.id,
                    "repository_id": workspace.repository_id.id,
                    "working_directory": workspace.worktree_path,
                }
                for name, value in derived.items():
                    if vals.get(name) not in (None, False, value):
                        raise ValidationError(
                            "Isolated session %s must be derived from its workspace." % name
                        )
                vals.update(derived)
            work_item = (
                self.env["dev.work.item"].browse(vals.get("work_item_id")).exists()
                if vals.get("work_item_id")
                else self.env["dev.work.item"]
            )
            if work_item:
                vals.setdefault("project_id", work_item.dev_project_id.id)
                if work_item.preferred_repository_id:
                    vals.setdefault(
                        "repository_id", work_item.preferred_repository_id.id
                    )
                if work_item.preferred_environment_id:
                    vals.setdefault(
                        "environment_id", work_item.preferred_environment_id.id
                    )
            project = (
                self.env["dev.project"].sudo().browse(vals.get("project_id")).exists()
            )
            self._check_project_authorization(project)
            if (
                vals.get("user_id", self.env.user.id) != self.env.user.id
                and not self._is_manager()
            ):
                raise AccessError("Dev Hub users can create only their own sessions.")
            if project:
                vals.setdefault("repository_id", project.default_repository_id.id)
                vals.setdefault("environment_id", project.default_environment_id.id)
            environment = (
                self.env["dev.environment"].browse(vals.get("environment_id")).exists()
            )
            if environment:
                vals.setdefault("machine_id", environment.machine_id.id)
            repository = (
                self.env["dev.repository"].browse(vals.get("repository_id")).exists()
            )
            if repository:
                supplied_path = vals.get("working_directory")
                expected_path = (
                    workspace.worktree_path if workspace else repository.working_directory
                )
                if supplied_path and supplied_path != expected_path:
                    raise ValidationError(
                        "Session working directory must use its exact canonical target."
                    )
                vals["working_directory"] = expected_path
            self._validate_safe_text(vals.get("last_note"), "Last note")
            self._validate_safe_text(
                vals.get("cursor_agent_thread_id"), "Cursor Agent thread ID"
            )
        return super().create(vals_list)

    def write(self, vals):
        if "execution_workspace_id" in vals:
            raise AccessError("A session cannot switch execution workspaces.")
        if IMMUTABLE_SESSION_FIELDS.intersection(vals):
            raise AccessError(
                "Lifecycle, snapshot, and manifest fields can only be changed "
                "through Dev Hub transition actions."
            )
        if TARGET_SESSION_FIELDS.intersection(vals) and any(
            record.state != "draft" for record in self
        ):
            raise AccessError("Development targets can only be changed in Draft state.")
        if "client_id" in vals and any(
            record.state not in ("draft", "paused", "blocked") for record in self
        ):
            raise AccessError(
                "The active development client can only change before start or while paused."
            )
        for record in self:
            project = (
                self.env["dev.project"]
                .sudo()
                .browse(vals.get("project_id", record.project_id.id))
                .exists()
            )
            record._check_project_authorization(project)
            if (
                "user_id" in vals
                and vals["user_id"] != self.env.user.id
                and not self._is_manager()
            ):
                raise AccessError("Dev Hub users cannot assign sessions to another user.")
            repository = (
                self.env["dev.repository"]
                .browse(vals.get("repository_id", record.repository_id.id))
                .exists()
            )
            if repository and {"repository_id", "working_directory"}.intersection(vals):
                expected_path = (
                    record.execution_workspace_id.worktree_path
                    if record.execution_workspace_id
                    else repository.working_directory
                )
                supplied_path = vals.get(
                    "working_directory", expected_path
                )
                if supplied_path != expected_path:
                    raise ValidationError(
                        "Session working directory must use its exact canonical target."
                    )
                vals["working_directory"] = expected_path
        self._validate_safe_text(vals.get("last_note"), "Last note")
        self._validate_safe_text(
            vals.get("cursor_agent_thread_id"), "Cursor Agent thread ID"
        )
        if "client_id" in vals:
            for record in self:
                if (
                    record.work_item_id
                    and record.state in ("paused", "blocked")
                    and vals["client_id"] != record.client_id.id
                ):
                    record._create_work_checkpoint("machine_switch")
        return super().write(vals)

    def _is_manager(self):
        return self.env.is_superuser() or self.env.user.has_group(
            "dev_session_hub.group_dev_hub_manager"
        )

    def _check_project_authorization(self, project):
        if self._is_manager():
            return
        if not project or (
            project.owner_id != self.env.user
            and self.env.user not in project.member_ids
        ):
            raise AccessError(
                "You must be an authorized project member to use this target."
            )

    @api.constrains(
        "project_id",
        "environment_id",
        "repository_id",
        "machine_id",
        "working_directory",
        "session_type",
        "execution_workspace_id",
        "work_item_id",
        "task_link_id",
    )
    def _check_registry_consistency(self):
        for record in self:
            if record.environment_id.project_id != record.project_id:
                raise ValidationError("Environment must belong to the selected project.")
            if record.repository_id.project_id != record.project_id:
                raise ValidationError("Repository must belong to the selected project.")
            if record.environment_id.machine_id != record.machine_id:
                raise ValidationError("Machine must match the selected environment.")
            if record.task_link_id and record.task_link_id.project_id != record.project_id:
                raise ValidationError("Task link must belong to the selected project.")
            if (
                record.work_item_id
                and record.work_item_id.dev_project_id != record.project_id
            ):
                raise ValidationError("Work Item must belong to the selected Dev Project.")
            if (
                record.execution_workspace_id
                and (
                    record.session_type != "isolated_execution_workspace"
                    or record.working_directory
                    != record.execution_workspace_id.worktree_path
                    or record.work_item_id != record.execution_workspace_id.work_item_id
                    or record.repository_id != record.execution_workspace_id.repository_id
                    or record.environment_id != record.execution_workspace_id.environment_id
                    or record.machine_id != record.execution_workspace_id.machine_id
                )
            ):
                raise ValidationError(
                    "An isolated session must derive all execution targets from its workspace."
                )
            if not record.execution_workspace_id and (
                record.session_type != "manual_developer_session"
                or not record.working_directory
                or record.working_directory != record.repository_id.working_directory
                or record.working_directory != record.repository_id.canonical_remote_path
            ):
                raise ValidationError(
                    "Manual sessions must exactly match both canonical repository paths."
                )

    @api.constrains("last_note", "cursor_agent_thread_id")
    def _check_safe_user_text(self):
        for record in self:
            self._validate_safe_text(record.last_note, "Last note")
            self._validate_safe_text(
                record.cursor_agent_thread_id, "Cursor Agent thread ID"
            )

    @staticmethod
    def _validate_safe_text(value, label):
        if not value:
            return
        if SENSITIVE_TEXT.search(value):
            raise ValidationError(
                "%s appears to contain credential material and cannot be stored." % label
            )
        if len(value) > 2000:
            raise ValidationError("%s is too long for the sanitized session log." % label)

    def _policy(self):
        self.ensure_one()
        exact = self.env["dev.policy"].search(
            [
                ("active", "=", True),
                ("project_id", "=", self.project_id.id),
                ("environment_id", "=", self.environment_id.id),
            ],
            limit=1,
        )
        if exact:
            return exact
        return self.env["dev.policy"].search(
            [
                ("active", "=", True),
                ("project_id", "=", self.project_id.id),
                ("environment_id", "=", False),
            ],
            limit=1,
        )

    def _validated_repository_path(self):
        self.ensure_one()
        session_path = os.path.realpath(self.working_directory or "")
        if self.execution_workspace_id:
            workspace = self.execution_workspace_id
            if session_path != os.path.realpath(workspace.worktree_path or ""):
                raise UserError(
                    "The isolated session path does not match its execution workspace."
                )
            workspace._validate_physical()
            return session_path
        registered_path = os.path.realpath(self.repository_id.working_directory or "")
        canonical_path = os.path.realpath(
            self.repository_id.canonical_remote_path or ""
        )
        if (
            not session_path
            or session_path != registered_path
            or session_path != canonical_path
        ):
            raise UserError(
                "The session path must exactly match both canonical repository paths."
            )
        if not os.path.isdir(session_path):
            raise UserError("The registered working directory does not exist.")
        return session_path

    def _validate_launch_context(self):
        self.ensure_one()
        self._check_registry_consistency()
        environment = self.environment_id
        machine = self.machine_id
        repository = self.repository_id
        if self.session_type == "isolated_execution_workspace":
            if not self.execution_workspace_id:
                raise UserError("Agent-related sessions require an isolated workspace.")
            self.execution_workspace_id._validate_physical()
        elif self.execution_workspace_id:
            raise UserError("Manual sessions cannot silently adopt an execution workspace.")
        self._check_project_authorization(self.project_id.sudo())
        environment._assert_dev_hub_safe(self.project_id)
        if (
            environment.is_production
            or environment.environment_type == "production"
            or environment.data_sensitivity
            in ("production", "restricted", "confidential")
        ):
            raise UserError("Production development sessions are disabled.")
        if machine.trust_zone != "trusted_dev":
            raise UserError("Launch requires a trusted development trust zone.")
        if not environment.active or not machine.active or not repository.active:
            raise UserError("The selected target is not active.")
        if (
            not machine.tailscale_destination_verified
            or not machine.tailscale_name
            or not machine.pinned_host_key_fingerprint
            or not machine.tailscale_verified_at
        ):
            raise UserError(
                "Launch requires a verified Tailscale destination and pinned SSH host key."
            )
        policy = self._policy()
        if not policy or not policy.launch_allowed or not policy.development_allowed:
            raise UserError("The environment policy does not allow development launch.")
        if policy.production_access_policy != "denied":
            raise UserError("MVP launch requires an explicit production-denied policy.")
        if policy.deploy_permission:
            raise UserError("MVP launch policies cannot grant deployment permission.")
        if not SSH_ALIAS.fullmatch(machine.ssh_alias or ""):
            raise UserError("The SSH alias is not allowlisted.")
        requested_path = self._validated_repository_path()
        allowed_paths = [
            os.path.realpath(line.strip())
            for line in (machine.allowed_path_prefixes or "").splitlines()
            if line.strip()
        ]
        if not requested_path or not any(
            os.path.commonpath([requested_path, allowed]) == allowed
            for allowed in allowed_paths
        ):
            raise UserError("The working directory is outside the machine allowlist.")
        local_hostname = socket.gethostname().split(".")[0]
        if machine.hostname.split(".")[0] != local_hostname:
            raise UserError(
                "The MVP can snapshot Git only on the local canonical target."
            )
        return requested_path, policy

    def _pin_enforced_launcher_available(self):
        """Fail closed until Stage B owns the complete SSH connection."""
        return False

    @staticmethod
    def _run_git(path, *args):
        try:
            result = subprocess.run(
                [GIT_EXECUTABLE, *GIT_SAFE_OPTIONS, *args],
                cwd=path,
                env=GIT_ENV,
                check=True,
                capture_output=True,
                text=True,
                timeout=8,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise UserError("Unable to read the registered Git worktree.") from exc
        return result.stdout.strip()

    def _capture_git_snapshot(self):
        self.ensure_one()
        path = self._validated_repository_path()
        top_level = os.path.realpath(self._run_git(path, "rev-parse", "--show-toplevel"))
        git_directory = os.path.realpath(
            self._run_git(path, "rev-parse", "--absolute-git-dir")
        )
        if top_level != path:
            raise UserError("The Git worktree root does not match the registry.")
        if self.execution_workspace_id:
            expected_common = os.path.realpath(
                self.repository_id.worker_git_common_dir or ""
            )
            actual_common = self._run_git(path, "rev-parse", "--git-common-dir")
            if not os.path.isabs(actual_common):
                actual_common = os.path.realpath(os.path.join(path, actual_common))
            else:
                actual_common = os.path.realpath(actual_common)
            metadata_root = os.path.join(expected_common, "worktrees") + os.sep
            if (
                not expected_common
                or actual_common != expected_common
                or not git_directory.startswith(metadata_root)
                or not os.path.isfile(os.path.join(path, ".git"))
                or os.path.islink(os.path.join(path, ".git"))
            ):
                raise UserError(
                    "The isolated worktree is not linked to its worker-owned Git metadata."
                )
            registered_remote = self.repository_id.git_remote or ""
            if registered_remote.startswith("file://") and os.path.realpath(
                registered_remote[7:]
            ) != expected_common:
                raise UserError("The isolated repository identity does not match.")
        else:
            expected_git_directory = os.path.join(path, ".git")
            remote_url = self._run_git(path, "remote", "get-url", "origin")
            if git_directory != expected_git_directory:
                raise UserError("The Git directory does not match the canonical repository.")
            if remote_url != self.repository_id.git_remote:
                raise UserError("The Git origin does not match the registered remote.")
        branch = self._run_git(path, "branch", "--show-current") or "DETACHED"
        head = self._run_git(path, "rev-parse", "--verify", "HEAD")
        if (
            self.execution_workspace_id
            and branch != self.execution_workspace_id.execution_branch
        ):
            raise UserError("The isolated session branch does not match its workspace.")
        if not GIT_BRANCH.fullmatch(branch):
            raise UserError("Git returned an unsafe branch identifier.")
        if not GIT_HEAD.fullmatch(head):
            raise UserError("Git returned an invalid HEAD identifier.")
        porcelain = self._run_git(
            path,
            "status",
            "--porcelain=v1",
            "--untracked-files=normal",
            "--ignore-submodules=all",
        )
        staged = unstaged = untracked = conflicts = 0
        touched_files = []
        for line in porcelain.splitlines():
            code = (line + "  ")[:2]
            relative_name = line[3:].strip()
            if relative_name and len(touched_files) < 100:
                relative_name = re.sub(r"[\x00-\x1f\x7f]", "", relative_name)
                if relative_name and not relative_name.startswith("/"):
                    touched_files.append(relative_name[:300])
            if code == "??":
                untracked += 1
                continue
            if code[0] not in (" ", "?"):
                staged += 1
            if code[1] not in (" ", "?"):
                unstaged += 1
            if "U" in code or code in {"AA", "DD"}:
                conflicts += 1
        digest = hashlib.sha256(porcelain.encode("utf-8")).hexdigest()[:12]
        dirty_summary = (
            "staged=%d; unstaged=%d; untracked=%d; conflicts=%d; digest=%s"
            % (staged, unstaged, untracked, conflicts, digest)
        )
        snapshot = {
            "branch": branch,
            "head": head,
            "dirty": dirty_summary,
            "staged": staged,
            "unstaged": unstaged,
            "untracked": untracked,
            "conflicts": conflicts,
            "dirty_digest": digest,
            "files_touched_summary": "\n".join(touched_files),
            "captured_at": fields.Datetime.now(),
        }
        try:
            ahead_behind = self._run_git(
                path, "rev-list", "--left-right", "--count", "@{upstream}...HEAD"
            ).split()
            if len(ahead_behind) == 2:
                snapshot["behind"] = int(ahead_behind[0])
                snapshot["ahead"] = int(ahead_behind[1])
        except (UserError, ValueError):
            snapshot.update(ahead=None, behind=None)
        return snapshot

    def _capture_git_snapshot_best_effort(self):
        try:
            return self._capture_git_snapshot()
        except (UserError, OSError, subprocess.SubprocessError):
            return {
                "error": "Git snapshot unavailable",
                "captured_at": fields.Datetime.now(),
            }

    def _lock_transition(self):
        self.ensure_one()
        self.env.cr.execute(
            "SELECT id FROM dev_session WHERE id = %s FOR UPDATE", [self.id]
        )
        self.invalidate_recordset()
        try:
            stat_result = os.stat(self.working_directory)
            lock_material = "inode:%s:%s" % (
                stat_result.st_dev,
                stat_result.st_ino,
            )
        except OSError:
            # Terminal transitions must remain possible after target removal.
            lock_material = "missing:%s" % os.path.realpath(
                self.working_directory or ""
            )
        lock_key = int.from_bytes(
            hashlib.sha256(lock_material.encode("utf-8")).digest()[:8],
            "big",
            signed=True,
        )
        self.env.cr.execute("SELECT pg_advisory_xact_lock(%s)", [lock_key])

    def _check_concurrency(self):
        self.ensure_one()
        try:
            current_stat = os.stat(self.working_directory)
            current_identity = ("inode", current_stat.st_dev, current_stat.st_ino)
        except OSError:
            current_identity = (
                "missing",
                os.path.realpath(self.working_directory or ""),
            )
        candidates = self.sudo().search(
            [("id", "!=", self.id), ("state", "in", list(ACTIVE_STATES))]
        )
        conflict = self.env["dev.session"]
        for candidate in candidates:
            try:
                candidate_stat = os.stat(candidate.working_directory)
                candidate_identity = (
                    "inode",
                    candidate_stat.st_dev,
                    candidate_stat.st_ino,
                )
            except OSError:
                candidate_identity = (
                    "missing",
                    os.path.realpath(candidate.working_directory or ""),
                )
            if candidate_identity == current_identity:
                conflict = candidate
                break
        if conflict:
            raise UserError(
                "Worktree concurrency warning: another development session is already "
                "active on this registered worktree."
            )

    def _drift_message(self, current):
        self.ensure_one()
        differences = []
        if self.git_branch_snapshot and self.git_branch_snapshot != current["branch"]:
            differences.append(
                "branch saved=%s current=%s"
                % (self.git_branch_snapshot, current["branch"])
            )
        if self.git_head_snapshot and self.git_head_snapshot != current["head"]:
            differences.append(
                "HEAD saved=%s current=%s"
                % (self.git_head_snapshot[:12], current["head"][:12])
            )
        if self.dirty_state_summary and self.dirty_state_summary != current["dirty"]:
            differences.append("dirty-state summary changed")
        return "; ".join(differences)

    def _append_event(self, old_state, new_state, snapshot, reason):
        self.ensure_one()
        safe_reason = (reason or "").strip()[:500]
        self._validate_safe_text(safe_reason, "Transition reason")
        self.env["dev.session.event"].sudo().create(
            {
                "session_id": self.id,
                "state_transition": "%s → %s" % (old_state, new_state),
                "actor_id": self.env.user.id,
                "client_id": self.client_id.id,
                "timestamp": fields.Datetime.now(),
                "reason": safe_reason,
                "git_snapshot": json.dumps(
                    {
                        "branch": snapshot.get("branch"),
                        "head": snapshot.get("head"),
                        "dirty": snapshot.get("dirty"),
                        "status": snapshot.get("error") or "captured",
                    },
                    sort_keys=True,
                ),
                "correlation_id": str(uuid.uuid4()),
            }
        )

    def _manifest_dict(self):
        self.ensure_one()
        _path, policy = self._validate_launch_context()
        task = self.task_link_id
        work_item = self.work_item_id
        title = re.sub(
            r"[\x00-\x1f\x7f]",
            " ",
            (work_item.name if work_item else task.cached_task_title) or "",
        )[:200]
        payload = {
            "schema": "dev-session-hub.manifest.v1",
            "manifest_revision": self.manifest_revision,
            "session_id": self.id,
            "session_name": self.name,
            "project": self.project_id.name,
            "project_code": self.project_id.code,
            "environment": self.environment_id.name,
            "environment_type": self.environment_id.environment_type,
            "machine": self.machine_id.name,
            "ssh_alias": self.machine_id.ssh_alias,
            "tailscale_destination": self.machine_id.tailscale_name,
            "pinned_host_key_fingerprint": (
                self.machine_id.pinned_host_key_fingerprint
            ),
            "working_directory": os.path.realpath(self.working_directory),
            "database": self.environment_id.database_identifier,
            "port": self.environment_id.port,
            "odoo_version": self.environment_id.odoo_version,
            "service_reference": self.environment_id.service_container_reference,
            "branch": self.git_branch_snapshot,
            "head": self.git_head_snapshot,
            "dirty_state_summary": self.dirty_state_summary,
            "session_type": self.session_type,
            "execution_workspace_id": (
                self.execution_workspace_id.id if self.execution_workspace_id else None
            ),
            "execution_branch": (
                self.execution_workspace_id.execution_branch
                if self.execution_workspace_id
                else None
            ),
            "execution_base_head": (
                self.execution_workspace_id.base_head
                if self.execution_workspace_id
                else None
            ),
            "approved_plan_hash": (
                self.execution_workspace_id.approved_plan_hash
                if self.execution_workspace_id
                else None
            ),
            "execution_policy_hash": (
                self.execution_workspace_id.policy_hash
                if self.execution_workspace_id
                else None
            ),
            "execution_contract_hash": (
                self.execution_workspace_id.execution_contract_hash
                if self.execution_workspace_id
                else None
            ),
            "work_item_uuid": work_item.uuid if work_item else None,
            "task_source": "openproject" if work_item else (
                task.source_system if task else None
            ),
            "task_id": (
                work_item.op_work_package_id
                if work_item
                else task.openproject_work_package_id if task else None
            ),
            "odoo_task_id": work_item.odoo_task_id.id if work_item else None,
            "task_title": title or None,
            "production": False,
            "state": self.state,
            "client": self.client_id.name,
            "drift_warning": self.drift_warning or None,
            "capabilities": {
                "development_allowed": policy.development_allowed,
                "agent_write_allowed": policy.agent_write_permission,
                "tests_allowed": policy.test_permission,
                "deploy_allowed": False,
            },
            "guardrails": [
                "Do not access production",
                "Do not deploy",
                "Do not switch branches automatically",
                "Do not restart services automatically",
                "Do not perform Docker actions",
                "Do not commit or push automatically",
            ],
        }
        return self._sanitize_manifest_value(payload)

    @classmethod
    def _sanitize_manifest_value(cls, value):
        if isinstance(value, dict):
            return {
                key: cls._sanitize_manifest_value(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [cls._sanitize_manifest_value(item) for item in value]
        if isinstance(value, str):
            if SENSITIVE_TEXT.search(value):
                return "[redacted]"
            return MANIFEST_UNSAFE.sub("_", value)[:500]
        return value

    def _refresh_manifest(self):
        self.ensure_one()
        revision = str(uuid.uuid4())
        super(DevSession, self).write({"manifest_revision": revision})
        payload = self._manifest_dict()
        manifest_json = json.dumps(payload, indent=2, sort_keys=True)
        super(DevSession, self).write({"manifest_json": manifest_json})
        return payload

    def _transition(self, new_state, reason=None, check_drift=False):
        self.ensure_one()
        self._lock_transition()
        if new_state not in TRANSITIONS.get(self.state, set()):
            raise UserError(
                "Invalid development-session transition: %s → %s"
                % (self.state, new_state)
            )
        if new_state in ACTIVE_STATES:
            self._check_concurrency()
        launch_transition = new_state in ("started", "resumed")
        if launch_transition:
            self._validate_launch_context()
            snapshot = self._capture_git_snapshot()
        else:
            snapshot = self._capture_git_snapshot_best_effort()
        drift = (
            self._drift_message(snapshot)
            if check_drift and not snapshot.get("error")
            else ""
        )
        now = fields.Datetime.now()
        vals = {
            "state": new_state,
            "drift_warning": drift or False,
        }
        if not snapshot.get("error"):
            vals.update(
                git_branch_snapshot=snapshot["branch"],
                git_head_snapshot=snapshot["head"],
                dirty_state_summary=snapshot["dirty"],
            )
        if new_state == "started":
            vals.update(started_at=now, active_client_id=self.client_id.id)
            if self.name == "New Development Session":
                task_label = (
                    "#%s" % self.task_link_id.openproject_work_package_id
                    if self.task_link_id
                    else "Unlinked task"
                )
                vals["name"] = "%s — %s" % (self.project_id.name, task_label)
        elif new_state == "in_progress":
            vals.update(active_client_id=self.client_id.id)
        elif new_state == "paused":
            vals.update(paused_at=now, active_client_id=False)
        elif new_state == "resumed":
            vals.update(resumed_at=now, active_client_id=self.client_id.id)
        elif new_state == "completed":
            vals.update(completed_at=now, active_client_id=False)
        elif new_state in ("blocked", "abandoned"):
            vals.update(active_client_id=False)
        old_state = self.state
        super(DevSession, self).write(vals)
        self._append_event(old_state, new_state, snapshot, reason or self.last_note)
        if launch_transition:
            self._refresh_manifest()
        return drift

    def _open_launcher(self):
        self.ensure_one()
        if self.state not in ACTIVE_STATES:
            raise UserError("Only an active session can generate a launch artifact.")
        wizard = self.env["dev.launch.wizard"].create_from_session(self)
        return {
            "type": "ir.actions.act_window",
            "name": "Open in Cursor — Explicit MVP Launcher",
            "res_model": "dev.launch.wizard",
            "res_id": wizard.id,
            "view_mode": "form",
            "target": "new",
        }

    def _create_work_checkpoint(self, trigger, snapshot=None):
        self.ensure_one()
        work = self.work_item_id
        if not work:
            return self.env["dev.work.checkpoint"]
        snapshot = snapshot or self._capture_git_snapshot_best_effort()
        plan = work.approved_plan_id
        steps = (
            plan.step_ids.sorted(lambda step: (step.sequence, step.id))
            if plan
            else self.env["dev.work.plan.step"]
        )
        completed = steps.filtered(lambda step: step.status == "done")
        current = steps.filtered(lambda step: step.status == "in_progress")[:1]
        if not current:
            current = steps.filtered(lambda step: step.status == "pending")[:1]
        remaining = steps.filtered(
            lambda step: step.status in ("pending", "in_progress", "blocked")
        )
        next_step = (
            "%s — %s" % (current.step_key, current.title)
            if current
            else "Review the approved plan and record the next explicit action."
        )
        checkpoint = self.env["dev.work.checkpoint"].sudo().create(
            {
                "work_item_id": work.id,
                "session_id": self.id,
                "trigger": trigger,
                "lifecycle_phase": work.current_phase,
                "approved_plan_id": plan.id,
                "last_completed_step_id": completed[-1:].id,
                "current_step_id": current.id,
                "next_recommended_step": next_step,
                "remaining_step_keys": ", ".join(remaining.mapped("step_key"))[:1000],
                "blockers": work.blocker or False,
                "last_agent_note": self.last_note or False,
                "repository_id": self.repository_id.id,
                "working_directory": self.working_directory,
                "branch": snapshot.get("branch") or self.git_branch_snapshot,
                "git_head": snapshot.get("head") or self.git_head_snapshot,
                "dirty_summary": snapshot.get("dirty") or self.dirty_state_summary,
                "ahead_count": snapshot.get("ahead") or 0,
                "behind_count": snapshot.get("behind") or 0,
                "files_touched_summary": (
                    (snapshot.get("files_touched_summary") or "")[:4000] or False
                ),
                "environment_id": self.environment_id.id,
                "machine_id": self.machine_id.id,
                "client_id": self.client_id.id,
                "manifest_revision": self.manifest_revision,
                "cursor_thread_reference": self.cursor_agent_thread_id,
                "execution_workspace_id": self.execution_workspace_id.id,
                "base_head": (
                    self.execution_workspace_id.base_head
                    if self.execution_workspace_id
                    else False
                ),
                "dirty_digest": (
                    self.execution_workspace_id.dirty_digest
                    if self.execution_workspace_id
                    else False
                ),
            }
        )
        work._refresh_context_revision()
        return checkpoint

    def action_checkpoint_milestone(self):
        self.ensure_one()
        return self._create_work_checkpoint("milestone")

    def action_checkpoint_agent_handoff(self):
        self.ensure_one()
        return self._create_work_checkpoint("agent_handoff")

    def action_start(self):
        self.ensure_one()
        if self.work_item_id:
            if self.work_item_id.current_phase not in ("approved", "implementing"):
                raise UserError(
                    "A linked Work Item must have an exact approved plan before Start."
                )
            self.work_item_id._validate_transition_requirements("implementing")
        self._transition("started", "Session started")
        if self.work_item_id and self.work_item_id.current_phase == "approved":
            self.work_item_id.action_start_implementation()
        return self._open_launcher()

    def action_mark_in_progress(self):
        self.ensure_one()
        self._transition("in_progress", "Marked in progress")
        return True

    def action_pause(self):
        self.ensure_one()
        self._transition("paused", "Session paused")
        if self.work_item_id:
            self.work_item_id.action_pause()
        return True

    def action_resume(self):
        self.ensure_one()
        self._transition("resumed", "Session resumed", check_drift=True)
        if self.work_item_id:
            self.work_item_id.action_resume()
        wizard = self.env["dev.resume.brief.wizard"].create_from_session(self)
        return {
            "type": "ir.actions.act_window",
            "name": "Resume Brief — Review Before Cursor",
            "res_model": "dev.resume.brief.wizard",
            "res_id": wizard.id,
            "view_mode": "form",
            "target": "new",
        }

    def action_complete(self):
        self.ensure_one()
        self._transition("completed", "Session completed")
        return True

    def action_block(self):
        self.ensure_one()
        self._transition("blocked", "Session blocked")
        return True

    def action_abandon(self):
        self.ensure_one()
        self._transition("abandoned", "Session abandoned")
        return True

    def action_open_launcher(self):
        self.ensure_one()
        return self._open_launcher()

    def safe_remote_uri(self):
        self.ensure_one()
        self._validate_launch_context()
        alias = quote(self.machine_id.ssh_alias, safe="._-")
        path = quote(os.path.realpath(self.working_directory), safe="/")
        return "vscode-remote://ssh-remote+%s%s" % (alias, path)


class DevSessionEvent(models.Model):
    _name = "dev.session.event"
    _description = "Development Session Event"
    _order = "timestamp desc, id desc"

    session_id = fields.Many2one(
        "dev.session", required=True, ondelete="restrict", index=True
    )
    state_transition = fields.Char(required=True, readonly=True)
    actor_id = fields.Many2one(
        "res.users", required=True, ondelete="restrict", readonly=True
    )
    client_id = fields.Many2one(
        "dev.client", required=True, ondelete="restrict", readonly=True
    )
    timestamp = fields.Datetime(required=True, readonly=True, index=True)
    reason = fields.Char(readonly=True)
    git_snapshot = fields.Text(readonly=True)
    correlation_id = fields.Char(required=True, readonly=True, index=True)

    def write(self, vals):
        raise AccessError("Development session events are immutable.")

    def unlink(self):
        raise AccessError("Development session events are immutable.")
