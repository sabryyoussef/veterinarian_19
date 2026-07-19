# -*- coding: utf-8 -*-
import hashlib
import json
import os
import pwd
import re
import subprocess
import unicodedata
import uuid
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


WORKSPACE_STATES = [
    ("draft", "Draft"),
    ("pending_confirmation", "Pending Confirmation"),
    ("preparing", "Preparing"),
    ("ready", "Ready"),
    ("active", "Active"),
    ("paused", "Paused"),
    ("blocked", "Blocked"),
    ("review_required", "Review Required"),
    ("commit_approved", "Commit Approved"),
    ("committed_reviewed", "Committed — Reviewed"),
    ("push_approved", "Push Approved"),
    ("push_failed_review", "Push Failed — Review Required"),
    ("uncertain_remote_state", "Push Remote State Uncertain"),
    ("pushed_reviewed", "Pushed — Reviewed"),
    ("pr_approved", "PR Creation Approved"),
    ("pr_creation_failed_review", "PR Creation Failed — Review Required"),
    ("pr_uncertain_state", "PR Remote State Uncertain"),
    ("pr_created_reviewed", "PR Created — Reviewed"),
    ("merge_approved", "Merge Approved"),
    ("merge_failed_review", "Merge Failed — Review Required"),
    ("merge_uncertain_state", "Merge Remote State Uncertain"),
    ("merged_reviewed", "Merged — Reviewed"),
    ("deploy_staging_approved", "Deploy Staging Approved"),
    ("deploy_staging_running", "Deploy Staging Running"),
    ("deploy_staging_failed_safely", "Deploy Staging Failed Safely"),
    ("deploy_staging_uncertain", "Deploy Staging Uncertain"),
    ("deployed_staging_reviewed", "Deployed Staging — Reviewed"),
    ("deploy_production_approved", "Deploy Production Approved"),
    ("deploy_production_running", "Deploy Production Running"),
    ("deployed_production_reviewed", "Deployed Production — Reviewed"),
    ("rollback_requested", "Rollback Requested"),
    ("rollback_approved", "Rollback Approved"),
    ("rolled_back", "Rolled Back"),
    ("rollback_failed", "Rollback Failed"),
    ("rollback_uncertain", "Rollback Uncertain"),
    ("released", "Released"),
    ("cleanup_pending", "Cleanup Pending"),
    ("archived", "Archived"),
]
ACTIVE_WORKSPACE_STATES = (
    "pending_confirmation",
    "preparing",
    "ready",
    "active",
    "paused",
    "blocked",
    "review_required",
    "commit_approved",
    "committed_reviewed",
    "push_approved",
    "push_failed_review",
    "uncertain_remote_state",
    "pushed_reviewed",
    "pr_approved",
    "pr_creation_failed_review",
    "pr_uncertain_state",
    "pr_created_reviewed",
    "merge_approved",
    "merge_failed_review",
    "merge_uncertain_state",
    "merged_reviewed",
    "deploy_staging_approved",
    "deploy_staging_running",
    "deploy_staging_failed_safely",
    "deploy_staging_uncertain",
    "deployed_staging_reviewed",
    "deploy_production_approved",
    "deploy_production_running",
    "deployed_production_reviewed",
    "rollback_requested",
    "rollback_approved",
    "rolled_back",
    "rollback_failed",
    "rollback_uncertain",
)
SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
BRANCH_RE = re.compile(r"^devhub/DW-[0-9]+-[a-z0-9](?:[a-z0-9-]{0,70}[a-z0-9])?$")
FORBIDDEN_ROOTS = (
    "/home/sabry",
    "/root",
    "/etc",
    "/var/lib/docker",
    "/var/lib/containers",
    "/var/backups",
    "/tmp",
    "/var/tmp",
    "/run",
    "/dev",
    "/proc",
    "/sys",
    "/backup",
    "/srv/backup",
)


def _slug(value, fallback="task", limit=64):
    normalized = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore")
    result = re.sub(r"[^a-z0-9]+", "-", normalized.decode().lower()).strip("-")
    result = re.sub(r"-+", "-", result)[:limit].strip("-")
    return result or fallback


def _canonical_child(root, *parts):
    root = os.path.realpath(root or "")
    if not root or not os.path.isabs(root):
        raise ValidationError("The execution root must be a canonical absolute path.")
    candidate = os.path.realpath(os.path.join(root, *parts))
    try:
        inside = os.path.commonpath((root, candidate)) == root
    except ValueError:
        inside = False
    if not inside or candidate == root:
        raise ValidationError("The generated worktree path escapes its allowlisted root.")
    return candidate


def _digest_status(raw):
    entries = sorted(filter(None, raw.decode("utf-8", "replace").split("\0")))
    return hashlib.sha256("\0".join(entries).encode()).hexdigest()


def _bounded_text(value, limit=4000):
    value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", str(value or ""))
    return value[:limit]


def _validate_repository_relative_path(raw_path, repository_root):
    try:
        path = raw_path.decode("utf-8", "strict")
    except UnicodeDecodeError as exc:
        raise ValidationError("Git status contains an undecodable path.") from exc
    if not path or path.startswith("/"):
        raise ValidationError("Git status contains an unsafe absolute or empty path.")
    parts = path.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ValidationError("Git status contains an unsafe repository-relative path.")
    root = os.path.realpath(repository_root or "")
    if not root or not os.path.isabs(root):
        raise ValidationError("Git status validation requires a canonical repository root.")
    candidate = os.path.realpath(os.path.join(root, *parts))
    try:
        inside = os.path.commonpath((root, candidate)) == root
    except ValueError:
        inside = False
    if not inside or candidate == root:
        raise ValidationError("Git status path escapes the execution worktree.")
    return path


def _parse_git_porcelain_v1_z(raw, repository_root):
    """Parse ``git status --porcelain=v1 -z`` without filename heuristics."""
    if not isinstance(raw, bytes):
        raise ValidationError("Git status output must be bytes.")
    if not raw:
        return []
    if not raw.endswith(b"\0"):
        raise ValidationError("Git porcelain output is not NUL terminated.")
    fields = raw[:-1].split(b"\0")
    records = []
    index = 0
    ordinary_index = " MTADRC"
    ordinary_worktree = " MTD"
    unmerged = {"DD", "AU", "UD", "UA", "DU", "AA", "UU"}
    while index < len(fields):
        entry = fields[index]
        index += 1
        if len(entry) < 4 or entry[2:3] != b" ":
            raise ValidationError("Git porcelain contains a malformed status record.")
        try:
            status = entry[:2].decode("ascii", "strict")
        except UnicodeDecodeError as exc:
            raise ValidationError("Git porcelain contains an invalid status code.") from exc
        if status not in ("??", "!!") and status not in unmerged:
            if (
                status[0] not in ordinary_index
                or status[1] not in ordinary_worktree
                or status == "  "
            ):
                raise ValidationError("Git porcelain contains an unknown status code.")
        destination = _validate_repository_relative_path(
            entry[3:], repository_root
        )
        source = None
        if status[0] in ("R", "C"):
            if index >= len(fields) or not fields[index]:
                raise ValidationError(
                    "Git porcelain rename/copy record is missing its source path."
                )
            source = _validate_repository_relative_path(
                fields[index], repository_root
            )
            index += 1
        records.append(
            {"status": status, "path": destination, "source_path": source}
        )
    return records


def _git_policy_paths(records, include_rename_source=True):
    paths = []
    for record in records:
        for path in (
            record["path"],
            record.get("source_path") if include_rename_source else None,
        ):
            if path and path not in paths:
                paths.append(path)
    return paths


def _assert_git_changes_allowlisted(
    raw, repository_root, allowed_paths, require_rename_source=True
):
    records = _parse_git_porcelain_v1_z(raw, repository_root)
    normalized_allowed = {
        _validate_repository_relative_path(
            str(path).encode("utf-8", "strict"), repository_root
        )
        for path in allowed_paths
    }
    policy_paths = _git_policy_paths(records, require_rename_source)
    disallowed = set(policy_paths) - normalized_allowed
    if disallowed:
        raise AccessError(
            "Git change set contains %s path(s) outside the approved allowlist."
            % len(disallowed)
        )
    return policy_paths


class DevRepository(models.Model):
    _inherit = "dev.repository"

    execution_classification = fields.Selection(
        [
            ("safe_for_isolated_worktree", "Safe for Isolated Worktree"),
            ("requires_review", "Requires Review"),
            ("production_coupled", "Production Coupled"),
            ("forbidden_for_agent_execution", "Forbidden for Agent Execution"),
        ],
        default="requires_review",
        required=True,
    )
    agent_execution_allowed = fields.Boolean(default=False)
    worker_git_common_dir = fields.Char(
        help="Worker-owned or dedicated shared bare Git repository; never the main worktree .git directory."
    )
    worker_worktree_root = fields.Char()
    worker_identity = fields.Char(default="devworker")
    production_runtime_coupled = fields.Boolean(default=False, readonly=True)
    test_runtime_coupled = fields.Boolean(default=False, readonly=True)
    execution_audit_summary = fields.Text(readonly=True)
    execution_audited_at = fields.Datetime(readonly=True)

    @api.constrains("worker_git_common_dir", "worker_worktree_root")
    def _check_execution_roots(self):
        for record in self:
            paths = [
                path
                for path in (record.worker_git_common_dir, record.worker_worktree_root)
                if path
            ]
            for path in paths:
                if not os.path.isabs(path) or path != os.path.realpath(path):
                    raise ValidationError(
                        "Worker Git and worktree paths must be canonical absolute paths."
                    )
                if any(path == root or path.startswith(root + os.sep) for root in FORBIDDEN_ROOTS):
                    raise ValidationError("Worker execution paths cannot use a sensitive root.")
            if len(paths) == 2:
                if os.path.commonpath(paths) == paths[0] or os.path.commonpath(paths) == paths[1]:
                    raise ValidationError(
                        "The bare Git common directory and worktree root must be separate."
                    )
            main = os.path.realpath(record.working_directory or "")
            common = os.path.realpath(record.worker_git_common_dir or "")
            if common and (common == os.path.join(main, ".git") or common.startswith(main + os.sep)):
                raise ValidationError(
                    "Agent Git metadata must not be shared with the main developer worktree."
                )


class DevWorkItem(models.Model):
    _inherit = "dev.work.item"

    execution_workspace_ids = fields.One2many(
        "dev.execution.workspace", "work_item_id", readonly=True
    )
    execution_workspace_id = fields.Many2one(
        "dev.execution.workspace",
        compute="_compute_execution_workspace",
        string="Current Execution Workspace",
    )

    @api.depends("execution_workspace_ids.state", "execution_workspace_ids.create_date")
    def _compute_execution_workspace(self):
        for record in self:
            candidates = record.execution_workspace_ids.filtered(
                lambda workspace: workspace.state in ACTIVE_WORKSPACE_STATES
            )
            record.execution_workspace_id = candidates.sorted(
                lambda workspace: (workspace.create_date, workspace.id), reverse=True
            )[:1]

    def action_prepare_execution_workspace(self):
        self.ensure_one()
        existing = self.execution_workspace_id
        if existing:
            return existing._form_action()
        workspace = self.env["dev.execution.workspace"].create_proposal(self)
        return workspace._form_action()


class DevExecutionWorkspace(models.Model):
    _name = "dev.execution.workspace"
    _description = "Isolated Development Execution Workspace"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc, id desc"

    name = fields.Char(required=True, readonly=True, index=True)
    work_item_id = fields.Many2one(
        "dev.work.item", required=True, ondelete="restrict", readonly=True, index=True
    )
    plan_id = fields.Many2one(
        "dev.work.plan", required=True, ondelete="restrict", readonly=True
    )
    plan_revision = fields.Integer(required=True, readonly=True)
    approved_plan_hash = fields.Char(required=True, readonly=True)
    approval_id = fields.Many2one(
        "dev.work.approval", required=True, ondelete="restrict", readonly=True
    )
    policy_id = fields.Many2one(
        "dev.policy", required=True, ondelete="restrict", readonly=True
    )
    policy_hash = fields.Char(required=True, readonly=True)
    execution_contract_hash = fields.Char(required=True, readonly=True, index=True)
    repository_id = fields.Many2one(
        "dev.repository", required=True, ondelete="restrict", readonly=True
    )
    project_id = fields.Many2one(
        "dev.project", required=True, ondelete="restrict", readonly=True, index=True
    )
    environment_id = fields.Many2one(
        "dev.environment", required=True, ondelete="restrict", readonly=True
    )
    machine_id = fields.Many2one(
        "dev.machine", required=True, ondelete="restrict", readonly=True
    )
    base_branch = fields.Char(required=True, readonly=True)
    base_head = fields.Char(required=True, readonly=True)
    execution_branch = fields.Char(required=True, readonly=True, index=True)
    worktree_path = fields.Char(required=True, readonly=True, index=True)
    worker_identity = fields.Char(required=True, readonly=True)
    state = fields.Selection(
        WORKSPACE_STATES,
        default="draft",
        required=True,
        readonly=True,
        tracking=True,
        index=True,
    )
    creation_status = fields.Char(readonly=True)
    validation_status = fields.Char(readonly=True)
    current_head = fields.Char(readonly=True)
    dirty_summary = fields.Char(readonly=True)
    dirty_digest = fields.Char(readonly=True)
    changed_files_summary = fields.Text(readonly=True)
    git_status_summary = fields.Text(readonly=True)
    main_branch_before = fields.Char(readonly=True)
    main_head_before = fields.Char(readonly=True)
    main_dirty_summary_before = fields.Char(readonly=True)
    main_dirty_digest_before = fields.Char(readonly=True)
    main_branch_after = fields.Char(readonly=True)
    main_head_after = fields.Char(readonly=True)
    main_dirty_summary_after = fields.Char(readonly=True)
    main_dirty_digest_after = fields.Char(readonly=True)
    created_by_id = fields.Many2one(
        "res.users", default=lambda self: self.env.user, readonly=True, ondelete="restrict"
    )
    activated_at = fields.Datetime(readonly=True)
    released_at = fields.Datetime(readonly=True)
    cleanup_status = fields.Char(readonly=True)
    last_validated_at = fields.Datetime(readonly=True)
    active_session_id = fields.Many2one("dev.session", readonly=True, ondelete="restrict")
    last_checkpoint_id = fields.Many2one(
        "dev.work.checkpoint", readonly=True, ondelete="restrict"
    )
    lease_client_id = fields.Many2one("dev.client", readonly=True, ondelete="restrict")
    lease_owner = fields.Char(readonly=True)
    lease_token = fields.Char(readonly=True, copy=False)
    lease_version = fields.Integer(default=0, readonly=True, copy=False)
    lease_expires_at = fields.Datetime(readonly=True, copy=False)
    worker_status = fields.Char(readonly=True)
    worker_started_at = fields.Datetime(readonly=True)
    worker_stopped_at = fields.Datetime(readonly=True)
    worker_log_summary = fields.Text(readonly=True)
    worker_resume_brief = fields.Text(readonly=True)
    review_handoff = fields.Text(readonly=True)
    event_ids = fields.One2many(
        "dev.execution.workspace.event", "workspace_id", readonly=True
    )

    @api.constrains("work_item_id", "worktree_path", "state")
    def _check_active_workspace_uniqueness(self):
        for record in self.filtered(lambda workspace: workspace.state in ACTIVE_WORKSPACE_STATES):
            domain = [
                ("id", "!=", record.id),
                ("state", "in", ACTIVE_WORKSPACE_STATES),
                "|",
                ("work_item_id", "=", record.work_item_id.id),
                ("worktree_path", "=", record.worktree_path),
            ]
            if self.search_count(domain):
                raise ValidationError(
                    "Active Work Items must use distinct isolated workspaces."
                )

    @api.model
    def _git(self, args, cwd=None, git_dir=None, check=True):
        if not args:
            raise AccessError("An explicit allowlisted Git operation is required.")
        read_only = {"symbolic-ref", "rev-parse", "status", "show-ref"}
        safe_branch_create = (
            args[0] == "branch"
            and len(args) == 3
            and BRANCH_RE.fullmatch(args[1] or "")
            and SHA1_RE.fullmatch(args[2] or "")
        )
        safe_worktree_add = (
            args[0] == "worktree"
            and len(args) == 4
            and args[1] == "add"
            and os.path.isabs(args[2])
            and BRANCH_RE.fullmatch(args[3] or "")
        )
        if args[0] not in read_only and not safe_branch_create and not safe_worktree_add:
            raise AccessError(
                "Git operation denied: only bounded branch/worktree preparation and "
                "read-only validation are allowed."
            )
        command = ["git"]
        if cwd:
            command.extend(["-c", "safe.directory=%s" % os.path.realpath(cwd)])
        if git_dir:
            command.extend(["--git-dir", git_dir])
        if cwd:
            command.extend(["-C", cwd])
        command.extend(args)
        environment = {
            "PATH": "/usr/bin:/bin",
            "HOME": "/nonexistent",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
            "LANG": "C",
        }
        result = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            check=False,
            env=environment,
        )
        if check and result.returncode:
            raise UserError(
                "Git validation failed safely: %s"
                % result.stderr.decode("utf-8", "replace")[:1000]
            )
        return result

    @api.model
    def _main_snapshot(self, repository):
        path = os.path.realpath(repository.working_directory or "")
        if not os.path.isdir(path):
            raise UserError("The registered main worktree is missing.")
        branch = self._git(["symbolic-ref", "--short", "-q", "HEAD"], cwd=path, check=False)
        head = self._git(["rev-parse", "HEAD"], cwd=path)
        status = self._git(["status", "--porcelain=v1", "-z", "--untracked-files=all"], cwd=path)
        entries = list(filter(None, status.stdout.decode("utf-8", "replace").split("\0")))
        counts = {"staged": 0, "unstaged": 0, "untracked": 0, "conflicts": 0}
        for entry in entries:
            code = entry[:2]
            if code == "??":
                counts["untracked"] += 1
            elif "U" in code or code in ("AA", "DD"):
                counts["conflicts"] += 1
            else:
                counts["staged"] += int(code[0] != " ")
                counts["unstaged"] += int(code[1] != " ")
        return {
            "branch": branch.stdout.decode().strip() or "(detached)",
            "head": head.stdout.decode().strip(),
            "dirty": "staged=%(staged)s; unstaged=%(unstaged)s; "
            "untracked=%(untracked)s; conflicts=%(conflicts)s" % counts,
            "digest": _digest_status(status.stdout),
        }

    @api.model
    def _exact_approval(self, work):
        plan = work.approved_plan_id
        if (
            not plan
            or plan.status != "approved"
            or plan.content_hash != plan._hash_values()
        ):
            raise UserError("An exact, current approved plan is required.")
        approval = self.env["dev.work.approval"].search(
            [
                ("work_item_id", "=", work.id),
                ("plan_id", "=", plan.id),
                ("decision", "=", "approved"),
                ("plan_hash", "=", plan.content_hash),
            ],
            order="decided_at desc, id desc",
            limit=1,
        )
        if not approval or approval.plan_revision != plan.revision:
            raise UserError("The approved plan revision has no matching immutable approval.")
        return plan, approval

    @api.model
    def _effective_policy(self, work):
        policy = self.env["dev.policy"].search(
            [
                ("active", "=", True),
                ("project_id", "=", work.dev_project_id.id),
                ("environment_id", "=", work.preferred_environment_id.id),
            ],
            limit=1,
        )
        if not policy:
            policy = self.env["dev.policy"].search(
                [
                    ("active", "=", True),
                    ("project_id", "=", work.dev_project_id.id),
                    ("environment_id", "=", False),
                ],
                limit=1,
            )
        if not policy:
            raise UserError("A reviewed execution policy is required.")
        payload = {
            "id": policy.id,
            "project_id": policy.project_id.id,
            "environment_id": policy.environment_id.id or None,
            "production_access_policy": policy.production_access_policy,
            "development_allowed": policy.development_allowed,
            "agent_write_permission": policy.agent_write_permission,
            "test_permission": policy.test_permission,
            "deploy_permission": policy.deploy_permission,
            "launch_allowed": policy.launch_allowed,
            "required_confirmation": policy.required_confirmation,
            "allowed_operations": policy.allowed_operations or "",
            "branch_rules": policy.branch_rules or "",
        }
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return policy, digest

    @api.model
    def _assert_repository_policy(self, repository):
        if (
            not repository.active
            or not repository.agent_execution_allowed
            or repository.execution_classification != "safe_for_isolated_worktree"
            or repository.production_runtime_coupled
        ):
            raise UserError("The repository is not approved for isolated agent execution.")
        common = os.path.realpath(repository.worker_git_common_dir or "")
        root = os.path.realpath(repository.worker_worktree_root or "")
        repository._check_execution_roots()
        if not common or not root:
            raise UserError("Dedicated worker Git and worktree roots are not configured.")
        return common, root

    @api.model
    def create_proposal(self, work):
        work.ensure_one()
        self.env.cr.execute("SELECT pg_advisory_xact_lock(%s)", [work.id])
        if self.search_count(
            [
                ("work_item_id", "=", work.id),
                ("state", "in", ACTIVE_WORKSPACE_STATES),
            ]
        ):
            raise UserError("This Work Item already has an active execution workspace.")
        if work.current_phase != "approved":
            raise UserError(
                "Execution workspace preparation requires an approved Work Item."
            )
        plan, approval = self._exact_approval(work)
        policy, policy_hash = self._effective_policy(work)
        repository = work.preferred_repository_id
        environment = work.preferred_environment_id
        if not repository or repository.project_id != work.dev_project_id:
            raise UserError("A registered project repository is required.")
        if not environment or environment.project_id != work.dev_project_id:
            raise UserError("A registered project environment is required.")
        environment._assert_dev_hub_safe(work.dev_project_id)
        common, root = self._assert_repository_policy(repository)
        if not SHA1_RE.fullmatch(repository.head_cache or ""):
            raise UserError("The registered Base HEAD is missing or invalid.")
        if not repository.default_branch or repository.default_branch == "unresolved":
            raise UserError("The registered base branch is unresolved.")
        branch = "devhub/DW-%s-%s" % (work.id, _slug(work.name))
        if not BRANCH_RE.fullmatch(branch):
            raise ValidationError("The generated execution branch is not Git-safe.")
        project_code = _slug(work.dev_project_id.code or work.dev_project_id.name, limit=32)
        path = _canonical_child(root, project_code, "DW-%s" % work.id)
        if os.path.lexists(path):
            raise UserError("The proposed worktree path already exists; human review is required.")
        if self.search_count(
            [("worktree_path", "=", path), ("state", "in", ACTIVE_WORKSPACE_STATES)]
        ):
            raise UserError("The proposed worktree is already assigned.")
        snapshot = self._main_snapshot(repository)
        contract = {
            "work_item_uuid": work.uuid,
            "plan_id": plan.id,
            "plan_revision": plan.revision,
            "plan_hash": plan.content_hash,
            "approval_id": approval.id,
            "policy_id": policy.id,
            "policy_hash": policy_hash,
            "repository_id": repository.id,
            "environment_id": environment.id,
            "machine_id": environment.machine_id.id,
            "base_branch": repository.default_branch,
            "base_head": repository.head_cache,
            "execution_branch": branch,
            "worktree_path": path,
            "worker_identity": repository.worker_identity,
        }
        contract_hash = hashlib.sha256(
            json.dumps(contract, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        values = {
            "name": "DW-%s" % work.id,
            "work_item_id": work.id,
            "plan_id": plan.id,
            "plan_revision": plan.revision,
            "approved_plan_hash": plan.content_hash,
            "approval_id": approval.id,
            "policy_id": policy.id,
            "policy_hash": policy_hash,
            "execution_contract_hash": contract_hash,
            "repository_id": repository.id,
            "project_id": work.dev_project_id.id,
            "environment_id": environment.id,
            "machine_id": environment.machine_id.id,
            "base_branch": repository.default_branch,
            "base_head": repository.head_cache,
            "execution_branch": branch,
            "worktree_path": path,
            "worker_identity": repository.worker_identity,
            "state": "pending_confirmation",
            "creation_status": "Awaiting explicit human confirmation",
            "validation_status": "Preflight passed; no Git write performed",
            "main_branch_before": snapshot["branch"],
            "main_head_before": snapshot["head"],
            "main_dirty_summary_before": snapshot["dirty"],
            "main_dirty_digest_before": snapshot["digest"],
        }
        workspace = self.create(values)
        workspace._event("proposal_created", "Human confirmation required")
        return workspace

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            if values.get("state", "draft") not in ("draft", "pending_confirmation"):
                raise ValidationError("Workspaces must begin in Draft or Pending Confirmation.")
        return super().create(vals_list)

    def write(self, values):
        protected = {
            "work_item_id",
            "plan_id",
            "plan_revision",
            "approved_plan_hash",
            "approval_id",
            "policy_id",
            "policy_hash",
            "execution_contract_hash",
            "repository_id",
            "project_id",
            "environment_id",
            "machine_id",
            "base_branch",
            "base_head",
            "execution_branch",
            "worktree_path",
            "worker_identity",
        }
        if protected.intersection(values):
            raise AccessError("Execution workspace identity is immutable.")
        return super().write(values)

    def unlink(self):
        raise AccessError("Execution workspaces are retained for audit.")

    def _internal_write(self, values):
        return super(DevExecutionWorkspace, self).write(values)

    def _event(self, event_type, summary, payload=None):
        self.ensure_one()
        return self.env["dev.execution.workspace.event"].sudo().with_context(
            dev_execution_event=True
        ).create(
            {
                "workspace_id": self.id,
                "event_type": event_type,
                "summary": summary,
                "payload_json": json.dumps(payload or {}, sort_keys=True),
            }
        )

    def _assert_plan_unchanged(self):
        self.ensure_one()
        plan, approval = self._exact_approval(self.work_item_id)
        if (
            plan != self.plan_id
            or approval != self.approval_id
            or plan.revision != self.plan_revision
            or plan.content_hash != self.approved_plan_hash
        ):
            raise UserError("Plan approval changed after workspace preparation.")
        policy, policy_hash = self._effective_policy(self.work_item_id)
        if policy != self.policy_id or policy_hash != self.policy_hash:
            raise UserError("Execution policy changed after workspace preparation.")
        contract = {
            "work_item_uuid": self.work_item_id.uuid,
            "plan_id": self.plan_id.id,
            "plan_revision": self.plan_revision,
            "plan_hash": self.approved_plan_hash,
            "approval_id": self.approval_id.id,
            "policy_id": self.policy_id.id,
            "policy_hash": self.policy_hash,
            "repository_id": self.repository_id.id,
            "environment_id": self.environment_id.id,
            "machine_id": self.machine_id.id,
            "base_branch": self.base_branch,
            "base_head": self.base_head,
            "execution_branch": self.execution_branch,
            "worktree_path": self.worktree_path,
            "worker_identity": self.worker_identity,
        }
        expected_contract_hash = hashlib.sha256(
            json.dumps(contract, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if self.execution_contract_hash != expected_contract_hash:
            raise UserError("Execution contract hash mismatch; execution is blocked.")

    def _assert_worker_identity(self, require_effective=False):
        self.ensure_one()
        try:
            account = pwd.getpwnam(self.worker_identity)
        except KeyError as exc:
            raise UserError("The restricted worker OS identity does not exist.") from exc
        groups = set(os.getgrouplist(account.pw_name, account.pw_gid))
        forbidden_groups = set()
        try:
            import grp

            for group_name in ("docker", "sudo", "wheel", "root"):
                try:
                    forbidden_groups.add(grp.getgrnam(group_name).gr_gid)
                except KeyError:
                    continue
        except ImportError:
            raise UserError("Worker group isolation cannot be verified on this host.")
        if (
            account.pw_uid == 0
            or groups.intersection(forbidden_groups)
            or os.path.realpath(account.pw_dir).startswith("/home/sabry")
        ):
            raise UserError("The worker identity violates root, sudo, or Docker isolation.")
        if require_effective and os.geteuid() != account.pw_uid:
            raise UserError(
                "Physical Git provisioning must run through the restricted worker-owned "
                "provisioning helper; cross-user Git metadata writes are denied."
            )
        return account

    def action_confirm_prepare(self):
        self.ensure_one()
        if not (
            self.env.is_superuser()
            or self.env.user.has_group("dev_session_hub.group_dev_hub_manager")
        ):
            raise AccessError("Only a Dev Hub Manager may confirm Git workspace creation.")
        self.env.cr.execute(
            "SELECT id FROM dev_execution_workspace WHERE id = %s FOR UPDATE NOWAIT",
            [self.id],
        )
        if self.state != "pending_confirmation":
            raise UserError("Only a pending proposal can be confirmed.")
        self._assert_plan_unchanged()
        self.environment_id._assert_dev_hub_safe(self.project_id)
        common, root = self._assert_repository_policy(self.repository_id)
        account = self._assert_worker_identity(require_effective=True)
        if self.worktree_path != _canonical_child(
            root, _slug(self.project_id.code or self.project_id.name, limit=32), self.name
        ):
            raise UserError("The proposed worktree path no longer matches policy.")
        current_main = self._main_snapshot(self.repository_id)
        expected_main = {
            "branch": self.main_branch_before,
            "head": self.main_head_before,
            "dirty": self.main_dirty_summary_before,
            "digest": self.main_dirty_digest_before,
        }
        if current_main != expected_main:
            self._internal_write(
                {"state": "blocked", "validation_status": "Main worktree drift before creation"}
            )
            self._event("blocked", "Main worktree changed after confirmation proposal")
            raise UserError("The main developer worktree changed; preparation stopped.")
        if os.path.lexists(self.worktree_path):
            self._internal_write(
                {"state": "review_required", "validation_status": "Worktree path collision"}
            )
            raise UserError("The worktree path exists; it will not be overwritten.")
        bare = self._git(["rev-parse", "--is-bare-repository"], git_dir=common)
        if bare.stdout.decode().strip() != "true":
            raise UserError("The dedicated worker Git common directory must be bare.")
        base = self._git(["rev-parse", "%s^{commit}" % self.base_branch], git_dir=common)
        if base.stdout.decode().strip() != self.base_head:
            raise UserError("The base branch does not resolve to the approved Base HEAD.")
        collision = self._git(
            ["show-ref", "--verify", "--quiet", "refs/heads/%s" % self.execution_branch],
            git_dir=common,
            check=False,
        )
        if collision.returncode == 0:
            existing = self._git(["rev-parse", self.execution_branch], git_dir=common)
            self._internal_write(
                {
                    "state": "review_required",
                    "validation_status": "Branch collision at %s"
                    % existing.stdout.decode().strip(),
                }
            )
            raise UserError(
                "The execution branch already exists. Choose explicit reuse or a new revision."
            )
        self._internal_write({"state": "preparing", "creation_status": "Creating branch"})
        self._git(["branch", self.execution_branch, self.base_head], git_dir=common)
        try:
            old_umask = os.umask(0o007)
            try:
                self._git(
                    ["worktree", "add", self.worktree_path, self.execution_branch],
                    git_dir=common,
                )
            finally:
                os.umask(old_umask)
        except Exception:
            self._internal_write(
                {
                    "state": "blocked",
                    "creation_status": "Branch created; worktree creation failed",
                }
            )
            self._event(
                "blocked",
                "Physical worktree creation failed; branch was retained for human review",
            )
            raise
        self._validate_physical(account)
        after = self._main_snapshot(self.repository_id)
        values = {
            "main_branch_after": after["branch"],
            "main_head_after": after["head"],
            "main_dirty_summary_after": after["dirty"],
            "main_dirty_digest_after": after["digest"],
        }
        if after != expected_main:
            values.update(
                state="blocked",
                validation_status="Main worktree changed during preparation",
            )
            self._internal_write(values)
            self._event("blocked", "Main worktree invariant failed after creation")
            raise UserError("Main worktree protection failed; execution is blocked.")
        values.update(
            state="ready",
            creation_status="Branch and physical worktree created",
            validation_status="Ready; main worktree unchanged",
            last_validated_at=fields.Datetime.now(),
        )
        self._internal_write(values)
        self._event("workspace_ready", "Isolated branch and worktree validated")
        return self._form_action()

    def _validate_physical(self, account=None):
        self.ensure_one()
        self._assert_plan_unchanged()
        self.environment_id._assert_dev_hub_safe(self.project_id)
        common, root = self._assert_repository_policy(self.repository_id)
        expected_path = _canonical_child(
            root, _slug(self.project_id.code or self.project_id.name, limit=32), self.name
        )
        if self.worktree_path != expected_path or not os.path.isdir(expected_path):
            raise UserError("The registered isolated worktree is missing or unsafe.")
        if os.path.islink(expected_path):
            raise UserError("A symlink cannot be used as an execution worktree.")
        actual_common = self._git(["rev-parse", "--git-common-dir"], cwd=expected_path)
        actual_common = actual_common.stdout.decode().strip()
        if not os.path.isabs(actual_common):
            actual_common = os.path.realpath(os.path.join(expected_path, actual_common))
        if os.path.realpath(actual_common) != common:
            raise UserError("The worktree is linked to an unexpected Git common directory.")
        branch = self._git(["symbolic-ref", "--short", "HEAD"], cwd=expected_path)
        head = self._git(["rev-parse", "HEAD"], cwd=expected_path)
        if branch.stdout.decode().strip() != self.execution_branch:
            raise UserError("The worktree branch does not match the execution workspace.")
        current_head = head.stdout.decode().strip()
        if not SHA1_RE.fullmatch(current_head):
            raise UserError("The worktree HEAD is invalid.")
        status = self._git(
            ["status", "--porcelain=v1", "-z", "--untracked-files=all"], cwd=expected_path
        )
        records = _parse_git_porcelain_v1_z(status.stdout, expected_path)
        paths = _git_policy_paths(records)
        summary = "changed=%s" % len(paths)
        audit_entries = []
        for record in records:
            entry = "%s %s" % (
                record["status"],
                json.dumps(record["path"], ensure_ascii=True),
            )
            if record["source_path"]:
                entry += " <- %s" % json.dumps(
                    record["source_path"], ensure_ascii=True
                )
            audit_entries.append(entry)
        self._internal_write(
            {
                "current_head": current_head,
                "dirty_summary": summary,
                "dirty_digest": _digest_status(status.stdout),
                "changed_files_summary": "\n".join(paths[:100]),
                "git_status_summary": "\n".join(audit_entries[:100]),
                "validation_status": "Validated",
                "last_validated_at": fields.Datetime.now(),
            }
        )
        return True

    def action_validate(self):
        for workspace in self:
            if workspace.state not in ACTIVE_WORKSPACE_STATES:
                raise UserError("Only a retained active workspace can be validated.")
            workspace._validate_physical()
            workspace._event("validated", "Workspace, branch, HEAD, and plan validated")
        return True

    def action_pause(self):
        self.ensure_one()
        if self.state != "active":
            raise UserError("Only an Active workspace can be paused.")
        self._validate_physical()
        self._internal_write({"state": "paused", "lease_expires_at": fields.Datetime.now()})
        self._event("paused", "Workspace paused; physical worktree retained")
        return True

    def action_resume(self):
        self.ensure_one()
        if self.state not in ("paused", "blocked"):
            raise UserError("Only a Paused or Blocked workspace can resume.")
        self._validate_physical()
        self._internal_write({"state": "ready"})
        self._event("resumed", "Same isolated worktree validated for resume")
        return self._form_action()

    def action_mark_review_required(self):
        self.ensure_one()
        if self.state not in ("ready", "active", "paused"):
            raise UserError("The workspace is not in an implementation state.")
        self._validate_physical()
        self._internal_write({"state": "review_required"})
        self._event("review_required", "Implementation awaits human Git review")
        return True

    def action_release(self):
        self.ensure_one()
        if self.active_session_id and self.active_session_id.state in (
            "started",
            "in_progress",
            "resumed",
        ):
            raise UserError("An active session must end before workspace release.")
        if self.lease_expires_at and self.lease_expires_at > fields.Datetime.now():
            raise UserError("An active worker lease prevents workspace release.")
        self._validate_physical()
        self._internal_write(
            {"state": "released", "released_at": fields.Datetime.now()}
        )
        self._event("released", "Workspace retained; cleanup requires separate approval")
        return True

    def action_request_cleanup(self):
        self.ensure_one()
        if self.state != "released":
            raise UserError("Release the workspace before requesting cleanup.")
        self._validate_physical()
        if self.dirty_summary != "changed=0":
            raise UserError("Dirty worktrees cannot enter automatic cleanup.")
        self._internal_write(
            {
                "state": "cleanup_pending",
                "cleanup_status": "Human approval required; no removal performed",
            }
        )
        self._event("cleanup_requested", "No worktree or branch was deleted")
        return True

    def acquire_lease(self, owner, client, seconds=900):
        self.ensure_one()
        if not (30 <= int(seconds) <= 3600):
            raise ValidationError("Worker lease duration must be between 30 and 3600 seconds.")
        self.env.cr.execute(
            "SELECT id FROM dev_execution_workspace WHERE id = %s FOR UPDATE NOWAIT",
            [self.id],
        )
        now = fields.Datetime.now()
        if self.lease_expires_at and self.lease_expires_at > now:
            raise AccessError("Concurrent write execution is already leased.")
        token = str(uuid.uuid4())
        version = self.lease_version + 1
        self._internal_write(
            {
                "lease_owner": str(owner)[:200],
                "lease_client_id": client.id,
                "lease_token": token,
                "lease_version": version,
                "lease_expires_at": now + timedelta(seconds=int(seconds)),
                "state": "active",
                "activated_at": self.activated_at or now,
            }
        )
        self._event("lease_acquired", "Exclusive worker lease acquired", {"version": version})
        return {"lease_token": token, "lease_version": version}

    def assert_lease(self, token, version):
        self.ensure_one()
        if (
            not token
            or token != self.lease_token
            or int(version) != self.lease_version
            or not self.lease_expires_at
            or self.lease_expires_at <= fields.Datetime.now()
        ):
            raise AccessError("The worker lease is stale, expired, or fenced.")
        return True

    def _assert_worker_execution(self, token, version):
        self.ensure_one()
        if self.state != "active":
            raise AccessError("Worker mutation requires an Active execution workspace.")
        self._assert_worker_identity(require_effective=True)
        self.assert_lease(token, version)
        self._assert_plan_unchanged()
        self.environment_id._assert_dev_hub_safe(self.project_id)
        self._validate_physical()
        self.assert_lease(token, version)
        return True

    def start_worker(self, owner, client, seconds=900):
        self.ensure_one()
        if self.state != "ready":
            raise UserError("The Dev Worker can start only from a Ready workspace.")
        self._assert_worker_identity(require_effective=True)
        self._assert_plan_unchanged()
        self.environment_id._assert_dev_hub_safe(self.project_id)
        self._validate_physical()
        lease = self.acquire_lease(owner, client, seconds=seconds)
        if self.work_item_id.current_phase == "approved":
            self.work_item_id.sudo().action_start_implementation()
        elif self.work_item_id.current_phase != "implementing":
            raise UserError("The Work Item is not eligible for worker implementation.")
        self.sudo()._internal_write(
            {
                "worker_status": "running",
                "worker_started_at": fields.Datetime.now(),
                "worker_stopped_at": False,
            }
        )
        self._event(
            "worker_started",
            "Restricted Dev Worker started under exclusive lease",
            {"version": lease["lease_version"]},
        )
        return lease

    def worker_update_step(self, token, version, step, status, result_summary=None):
        self.ensure_one()
        self._assert_worker_execution(token, version)
        step = self.env["dev.work.plan.step"].browse(step.id).exists()
        if not step or step.plan_id != self.plan_id:
            raise AccessError("The requested step is outside the approved Plan.")
        values = {"status": status}
        if result_summary is not None:
            values["result_summary"] = _bounded_text(result_summary, 1000)
        step.sudo().write(values)
        self.assert_lease(token, version)
        self._event(
            "worker_step_%s" % status,
            "%s moved to %s" % (step.step_key, status),
            {"step": step.step_key},
        )
        return True

    def worker_checkpoint(
        self,
        token,
        version,
        summary,
        trigger="milestone",
        test_result=None,
    ):
        self.ensure_one()
        self._assert_worker_execution(token, version)
        if trigger not in ("milestone", "pause", "agent_handoff"):
            raise ValidationError("Unsupported worker checkpoint trigger.")
        test_result = dict(test_result or {})
        steps = self.plan_id.step_ids.sorted(lambda item: (item.sequence, item.id))
        completed = steps.filtered(lambda item: item.status == "done")
        current = steps.filtered(lambda item: item.status == "in_progress")[:1]
        if not current:
            current = steps.filtered(lambda item: item.status == "pending")[:1]
        remaining = steps.filtered(
            lambda item: item.status in ("pending", "in_progress", "blocked")
        )
        next_action = (
            "%s — %s" % (current.step_key, current.title)
            if current
            else "Prepare the bounded human review handoff."
        )
        checkpoint = self.env["dev.work.checkpoint"].sudo().create(
            {
                "work_item_id": self.work_item_id.id,
                "execution_workspace_id": self.id,
                "trigger": trigger,
                "lifecycle_phase": self.work_item_id.current_phase,
                "approved_plan_id": self.plan_id.id,
                "last_completed_step_id": completed[-1:].id,
                "current_step_id": current.id,
                "next_recommended_step": next_action,
                "remaining_step_keys": ", ".join(remaining.mapped("step_key"))[:1000],
                "last_agent_note": _bounded_text(summary),
                "repository_id": self.repository_id.id,
                "working_directory": self.worktree_path,
                "branch": self.execution_branch,
                "git_head": self.current_head,
                "base_head": self.base_head,
                "dirty_summary": self.dirty_summary,
                "dirty_digest": self.dirty_digest,
                "files_touched_summary": self.changed_files_summary,
                "tests_run": max(0, int(test_result.get("run", 0))),
                "tests_passed": max(0, int(test_result.get("passed", 0))),
                "tests_failed": max(0, int(test_result.get("failed", 0))),
                "tests_skipped": max(0, int(test_result.get("skipped", 0))),
                "test_commands_summary": _bounded_text(
                    test_result.get("command", ""), 1000
                ),
                "test_duration_seconds": max(
                    0.0, min(float(test_result.get("duration", 0.0)), 86400.0)
                ),
                "test_evidence_references": _bounded_text(
                    test_result.get("evidence", ""), 1000
                ),
                "environment_id": self.environment_id.id,
                "machine_id": self.machine_id.id,
                "client_id": self.lease_client_id.id,
            }
        )
        self.assert_lease(token, version)
        self.sudo()._internal_write({"last_checkpoint_id": checkpoint.id})
        self._event(
            "worker_checkpoint",
            "Immutable worker checkpoint captured",
            {"checkpoint_id": checkpoint.id, "trigger": trigger},
        )
        return checkpoint

    def worker_pause(self, token, version, summary, test_result=None):
        self.ensure_one()
        checkpoint = self.worker_checkpoint(
            token,
            version,
            summary,
            trigger="pause",
            test_result=test_result,
        )
        self.assert_lease(token, version)
        self.work_item_id.sudo().action_pause()
        completed = self.plan_id.step_ids.filtered(
            lambda item: item.status == "done"
        ).mapped("step_key")
        remaining = self.plan_id.step_ids.filtered(
            lambda item: item.status in ("pending", "in_progress", "blocked")
        ).mapped("step_key")
        self.sudo()._internal_write(
            {
                "state": "paused",
                "worker_status": "paused",
                "worker_resume_brief": _bounded_text(
                    "Workspace: %s\nBranch: %s\nHEAD: %s\nDirty digest: %s\n"
                    "Plan hash: %s\nPolicy hash: %s\nContract hash: %s\n"
                    "Completed: %s\nRemaining: %s"
                    % (
                        self.worktree_path,
                        self.execution_branch,
                        self.current_head,
                        self.dirty_digest,
                        self.approved_plan_hash,
                        self.policy_hash,
                        self.execution_contract_hash,
                        ", ".join(completed),
                        ", ".join(remaining),
                    )
                ),
                "lease_owner": False,
                "lease_client_id": False,
                "lease_token": False,
                "lease_expires_at": fields.Datetime.now(),
                "last_checkpoint_id": checkpoint.id,
            }
        )
        self._event(
            "worker_paused",
            "Dev Worker paused and prior lease fenced",
            {"version": version, "checkpoint_id": checkpoint.id},
        )
        return checkpoint

    def worker_resume(self, owner, client, expected_dirty_digest, seconds=900):
        self.ensure_one()
        if self.state != "paused":
            raise UserError("The Dev Worker can resume only a Paused workspace.")
        self._assert_worker_identity(require_effective=True)
        self._assert_plan_unchanged()
        self.environment_id._assert_dev_hub_safe(self.project_id)
        self._validate_physical()
        if self.dirty_digest != expected_dirty_digest:
            raise UserError("Workspace dirty digest changed while the worker was paused.")
        self.sudo().action_resume()
        self.work_item_id.sudo().action_resume()
        lease = self.acquire_lease(owner, client, seconds=seconds)
        self.sudo()._internal_write({"worker_status": "running"})
        self._event(
            "worker_resumed",
            "Same worktree resumed under a new fencing version",
            {"version": lease["lease_version"]},
        )
        return lease

    def worker_mark_review_required(
        self, token, version, review_handoff, test_result=None
    ):
        self.ensure_one()
        self._assert_worker_execution(token, version)
        if self.plan_id.step_ids.filtered(lambda item: item.status != "done"):
            raise UserError("Every approved Plan step must be complete before review.")
        test_result = dict(test_result or {})
        if int(test_result.get("failed", 0)) or int(test_result.get("errors", 0)):
            raise UserError("Failing tests block the human review handoff.")
        handoff = _bounded_text(review_handoff, 8000)
        if not handoff:
            raise ValidationError("A bounded review handoff is required.")
        self.work_item_id.sudo().action_start_testing()
        checkpoint = self.worker_checkpoint(
            token,
            version,
            handoff,
            trigger="agent_handoff",
            test_result=test_result,
        )
        report = self.env["dev.completion.report"].sudo().create(
            {
                "work_item_id": self.work_item_id.id,
                "plan_id": self.plan_id.id,
                "original_request_summary": self.work_item_id.name,
                "implemented_summary": handoff,
                "completed_steps_summary": ", ".join(
                    self.plan_id.step_ids.sorted(
                        lambda item: (item.sequence, item.id)
                    ).mapped("step_key")
                ),
                "changed_components_summary": (
                    self.changed_files_summary or "No changed files recorded."
                ),
                "repository_reference": self.repository_id.name,
                "branch": self.execution_branch,
                "tests_summary": _bounded_text(
                    test_result.get("summary", "Approved worker tests passed."), 2000
                ),
                "uat_status": "pending",
                "known_limitations": (
                    "No commit, push, PR, merge, deployment, service restart, "
                    "Docker operation, Production access, or external message."
                ),
                "rollback_notes": (
                    "Human may discard the uncommitted allowlisted test files; "
                    "no automatic cleanup is authorized."
                ),
                "deployment_status": "not_deployed",
                "production_status": "not_verified",
                "generated_by": "agent",
                "run_reference": "phase5-worker-workspace-%s" % self.id,
            }
        )
        report.action_ready_review()
        self.work_item_id.sudo().action_ready_for_review()
        self.assert_lease(token, version)
        self.sudo()._internal_write(
            {
                "state": "review_required",
                "worker_status": "stopped_at_review_required",
                "worker_stopped_at": fields.Datetime.now(),
                "review_handoff": handoff,
                "worker_log_summary": (
                    "Bounded implementation complete; tests passed; "
                    "stopped for human review."
                ),
                "lease_owner": False,
                "lease_client_id": False,
                "lease_token": False,
                "lease_expires_at": fields.Datetime.now(),
                "last_checkpoint_id": checkpoint.id,
            }
        )
        self._event(
            "worker_stopped",
            "Dev Worker stopped at mandatory human review gate",
            {"checkpoint_id": checkpoint.id, "version": version},
        )
        return checkpoint

    def _form_action(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Execution Workspace",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "current",
        }


class DevExecutionWorkspaceEvent(models.Model):
    _name = "dev.execution.workspace.event"
    _description = "Immutable Execution Workspace Event"
    _order = "occurred_at desc, id desc"

    workspace_id = fields.Many2one(
        "dev.execution.workspace", required=True, ondelete="restrict", readonly=True
    )
    event_type = fields.Char(required=True, readonly=True)
    summary = fields.Char(required=True, readonly=True)
    payload_json = fields.Text(readonly=True)
    actor_id = fields.Many2one(
        "res.users",
        required=True,
        default=lambda self: self.env.user,
        ondelete="restrict",
        readonly=True,
    )
    occurred_at = fields.Datetime(
        required=True, default=fields.Datetime.now, readonly=True
    )

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("dev_execution_event"):
            raise AccessError("Workspace events are created only by guarded actions.")
        return super().create(vals_list)

    def write(self, vals):
        raise AccessError("Workspace events are immutable.")

    def unlink(self):
        raise AccessError("Workspace events are immutable.")


class DevSessionExecutionWorkspace(models.Model):
    _inherit = "dev.session"

    def action_start(self):
        self.ensure_one()
        workspace = self.execution_workspace_id
        if workspace:
            workspace._validate_physical()
            if workspace.state != "ready":
                raise UserError("The isolated workspace is not Ready.")
        result = super().action_start()
        if workspace:
            workspace._internal_write(
                {
                    "state": "active",
                    "active_session_id": self.id,
                    "activated_at": workspace.activated_at or fields.Datetime.now(),
                }
            )
            workspace._event("session_started", "Manual isolated Cursor session started")
        return result

    def action_pause(self):
        self.ensure_one()
        result = super().action_pause()
        workspace = self.execution_workspace_id
        if workspace:
            workspace._validate_physical()
            checkpoint = self.work_item_id.current_checkpoint_id
            workspace._internal_write(
                {
                    "state": "paused",
                    "active_session_id": False,
                    "last_checkpoint_id": checkpoint.id,
                }
            )
            workspace._event("session_paused", "Immutable checkpoint captured")
        return result

    def action_resume(self):
        self.ensure_one()
        workspace = self.execution_workspace_id
        if workspace:
            workspace.action_resume()
        result = super().action_resume()
        if workspace:
            workspace._internal_write(
                {
                    "state": "active",
                    "active_session_id": self.id,
                    "activated_at": workspace.activated_at or fields.Datetime.now(),
                }
            )
            workspace._event("session_resumed", "Same physical worktree resumed")
        return result

    def action_complete(self):
        result = super().action_complete()
        for session in self.filtered("execution_workspace_id"):
            workspace = session.execution_workspace_id
            workspace._validate_physical()
            workspace._internal_write(
                {"state": "review_required", "active_session_id": False}
            )
            workspace._event("session_completed", "Human Git review is required")
        return result

    def action_block(self):
        result = super().action_block()
        for session in self.filtered("execution_workspace_id"):
            session.execution_workspace_id._internal_write(
                {"state": "blocked", "active_session_id": False}
            )
            session.execution_workspace_id._event("session_blocked", "Execution blocked")
        return result

    def action_abandon(self):
        result = super().action_abandon()
        for session in self.filtered("execution_workspace_id"):
            session.execution_workspace_id._internal_write(
                {"state": "review_required", "active_session_id": False}
            )
            session.execution_workspace_id._event(
                "session_abandoned", "Workspace retained for human review"
            )
        return result


class DevWorkCheckpointExecutionWorkspace(models.Model):
    _inherit = "dev.work.checkpoint"

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for checkpoint in records.filtered("execution_workspace_id"):
            checkpoint.execution_workspace_id._internal_write(
                {"last_checkpoint_id": checkpoint.id}
            )
        return records
