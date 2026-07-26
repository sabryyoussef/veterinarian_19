# -*- coding: utf-8 -*-
import hashlib
import json
import os
import re
import stat
import subprocess

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from .dev_execution import (
    SHA1_RE,
    _digest_status,
    _git_policy_paths,
    _parse_git_porcelain_v1_z,
    _validate_repository_relative_path,
)


COMMIT_MESSAGE_LIMIT = 2000
COMMIT_AUTHOR_NAME = "Dev Worker"
COMMIT_AUTHOR_EMAIL = "devworker@devhub.invalid"
SECRET_MARKERS = (
    "begin private key",
    "password=",
    "passwd=",
    "api_key=",
    "apikey=",
    "access_token=",
    "secret=",
)


def _canonical_hash(payload):
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _safe_commit_message(value):
    value = str(value or "")
    if not value.strip() or len(value) > COMMIT_MESSAGE_LIMIT:
        raise ValidationError("Commit message must contain 1–2000 characters.")
    if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", value):
        raise ValidationError("Commit message contains forbidden control characters.")
    if len(value.splitlines()[0]) > 200:
        raise ValidationError("Commit subject must not exceed 200 characters.")
    lowered = value.casefold()
    if any(marker in lowered for marker in SECRET_MARKERS):
        raise ValidationError("Commit message contains a forbidden secret-like marker.")
    return value.strip() + "\n"


class DevGitCommitApproval(models.Model):
    _name = "dev.git.commit.approval"
    _description = "Immutable Human Git Commit Approval"
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
    branch = fields.Char(required=True, readonly=True)
    current_head = fields.Char(required=True, readonly=True)
    dirty_digest = fields.Char(required=True, readonly=True)
    changed_files_digest = fields.Char(required=True, readonly=True)
    changed_files_summary = fields.Text(required=True, readonly=True)
    git_status_summary = fields.Text(readonly=True)
    diff_summary = fields.Text(required=True, readonly=True)
    plan_id = fields.Many2one(
        "dev.work.plan", required=True, readonly=True, ondelete="restrict"
    )
    plan_hash = fields.Char(required=True, readonly=True)
    policy_hash = fields.Char(required=True, readonly=True)
    execution_contract_hash = fields.Char(required=True, readonly=True)
    approver_id = fields.Many2one(
        "res.users", required=True, readonly=True, ondelete="restrict"
    )
    approved_at = fields.Datetime(required=True, readonly=True, index=True)
    commit_message = fields.Text(required=True, readonly=True)
    commit_message_hash = fields.Char(required=True, readonly=True)
    binding_hash = fields.Char(required=True, readonly=True, copy=False, index=True)
    main_branch = fields.Char(required=True, readonly=True)
    main_head = fields.Char(required=True, readonly=True)
    main_dirty_digest = fields.Char(required=True, readonly=True)
    checkpoint_id = fields.Many2one(
        "dev.work.checkpoint", readonly=True, ondelete="restrict"
    )
    tests_summary = fields.Text(readonly=True)
    event_ids = fields.One2many(
        "dev.git.commit.approval.event", "approval_id", readonly=True
    )
    approval_state = fields.Char(compute="_compute_approval_state")

    @api.depends("event_ids.event_type", "event_ids.occurred_at")
    def _compute_approval_state(self):
        for record in self:
            events = record.event_ids.sorted(
                lambda item: (item.occurred_at, item.id), reverse=True
            )
            record.approval_state = events[:1].event_type if events else "approved"

    def _binding_values(self):
        self.ensure_one()
        return {
            "work_item_id": self.work_item_id.id,
            "workspace_id": self.workspace_id.id,
            "branch": self.branch,
            "current_head": self.current_head,
            "dirty_digest": self.dirty_digest,
            "changed_files_digest": self.changed_files_digest,
            "changed_files_summary": self.changed_files_summary,
            "plan_id": self.plan_id.id,
            "plan_hash": self.plan_hash,
            "policy_hash": self.policy_hash,
            "execution_contract_hash": self.execution_contract_hash,
            "approver_id": self.approver_id.id,
            "approved_at": fields.Datetime.to_string(self.approved_at),
            "commit_message_hash": self.commit_message_hash,
            "main_branch": self.main_branch,
            "main_head": self.main_head,
            "main_dirty_digest": self.main_dirty_digest,
        }

    def assert_integrity(self):
        for record in self:
            if record.binding_hash != _canonical_hash(record._binding_values()):
                raise AccessError("Commit approval integrity validation failed.")
        return True

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("dev_git_commit_approval"):
            raise AccessError("Commit approvals require the guarded human review flow.")
        records = super().create(vals_list)
        for record in records:
            super(DevGitCommitApproval, record).write(
                {"binding_hash": _canonical_hash(record._binding_values())}
            )
        return records

    def write(self, values):
        raise AccessError("Git commit approvals are immutable.")

    def unlink(self):
        raise AccessError("Git commit approvals are retained for audit.")


class DevGitCommitApprovalEvent(models.Model):
    _name = "dev.git.commit.approval.event"
    _description = "Immutable Git Commit Approval Event"
    _order = "occurred_at desc, id desc"

    approval_id = fields.Many2one(
        "dev.git.commit.approval",
        required=True,
        readonly=True,
        ondelete="restrict",
        index=True,
    )
    event_type = fields.Selection(
        [
            ("rejected", "Rejected"),
            ("superseded", "Superseded"),
            ("consumed", "Consumed by Commit"),
        ],
        required=True,
        readonly=True,
    )
    occurred_at = fields.Datetime(
        required=True, readonly=True, default=fields.Datetime.now
    )
    actor_id = fields.Many2one(
        "res.users",
        required=True,
        readonly=True,
        default=lambda self: self.env.user,
        ondelete="restrict",
    )
    summary = fields.Char(required=True, readonly=True)
    payload_json = fields.Text(readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("dev_git_commit_event"):
            raise AccessError("Commit approval events require a guarded action.")
        return super().create(vals_list)

    def write(self, values):
        raise AccessError("Git commit approval events are immutable.")

    def unlink(self):
        raise AccessError("Git commit approval events are retained for audit.")


class DevGitCommitRecord(models.Model):
    _name = "dev.git.commit.record"
    _description = "Immutable Reviewed Local Git Commit Record"
    _order = "committed_at desc, id desc"

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
    approval_id = fields.Many2one(
        "dev.git.commit.approval",
        required=True,
        readonly=True,
        ondelete="restrict",
        index=True,
    )
    branch = fields.Char(required=True, readonly=True)
    parent_sha = fields.Char(required=True, readonly=True)
    commit_sha = fields.Char(required=True, readonly=True, index=True)
    committed_files_summary = fields.Text(required=True, readonly=True)
    approver_id = fields.Many2one(
        "res.users", required=True, readonly=True, ondelete="restrict"
    )
    committed_at = fields.Datetime(required=True, readonly=True)
    commit_message_hash = fields.Char(required=True, readonly=True)
    test_evidence_references = fields.Text(readonly=True)
    author_name = fields.Char(required=True, readonly=True)
    author_email = fields.Char(required=True, readonly=True)
    audit_hash = fields.Char(required=True, readonly=True, copy=False, index=True)

    def _audit_values(self):
        self.ensure_one()
        return {
            "work_item_id": self.work_item_id.id,
            "workspace_id": self.workspace_id.id,
            "approval_id": self.approval_id.id,
            "branch": self.branch,
            "parent_sha": self.parent_sha,
            "commit_sha": self.commit_sha,
            "committed_files_summary": self.committed_files_summary,
            "approver_id": self.approver_id.id,
            "committed_at": fields.Datetime.to_string(self.committed_at),
            "commit_message_hash": self.commit_message_hash,
            "author_name": self.author_name,
            "author_email": self.author_email,
        }

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("dev_git_commit_record"):
            raise AccessError("Commit records require guarded commit execution.")
        records = super().create(vals_list)
        for record in records:
            super(DevGitCommitRecord, record).write(
                {"audit_hash": _canonical_hash(record._audit_values())}
            )
        return records

    def write(self, values):
        raise AccessError("Git commit records are immutable.")

    def unlink(self):
        raise AccessError("Git commit records are retained for audit.")


class DevExecutionWorkspace(models.Model):
    _inherit = "dev.execution.workspace"

    changed_files_digest = fields.Char(readonly=True)
    review_diff_summary = fields.Text(readonly=True)
    review_tests_summary = fields.Text(readonly=True)
    commit_approval_ids = fields.One2many(
        "dev.git.commit.approval", "workspace_id", readonly=True
    )
    commit_approval_id = fields.Many2one(
        "dev.git.commit.approval", readonly=True, ondelete="restrict"
    )
    commit_record_id = fields.Many2one(
        "dev.git.commit.record", readonly=True, ondelete="restrict"
    )
    committed_sha = fields.Char(readonly=True)
    committed_parent_sha = fields.Char(readonly=True)
    committed_at = fields.Datetime(readonly=True)

    def _require_commit_manager(self):
        if not self.env.user.has_group("dev_session_hub.group_dev_hub_manager"):
            raise AccessError("Only a Dev Hub manager may authorize a Git commit.")

    def _assert_no_worker_lease(self):
        self.ensure_one()
        if self.lease_token or (
            self.lease_expires_at and self.lease_expires_at > fields.Datetime.now()
        ):
            raise AccessError("An active or unreleased worker lease blocks Git commit.")

    def _review_change_binding(self):
        self.ensure_one()
        self._validate_physical()
        status = self._git(
            ["status", "--porcelain=v1", "-z", "--untracked-files=all"],
            cwd=self.worktree_path,
        )
        records = _parse_git_porcelain_v1_z(status.stdout, self.worktree_path)
        paths = _git_policy_paths(records)
        if not paths:
            raise UserError("There are no reviewed changes to commit.")
        content = []
        for path in sorted(paths):
            absolute = os.path.realpath(os.path.join(self.worktree_path, path))
            _validate_repository_relative_path(path.encode("utf-8"), self.worktree_path)
            if os.path.lexists(absolute):
                metadata = os.lstat(absolute)
                if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                    raise AccessError(
                        "Reviewed Git changes must be regular files or deletions."
                    )
                digest = hashlib.sha256()
                with open(absolute, "rb") as changed_file:
                    for chunk in iter(lambda: changed_file.read(65536), b""):
                        digest.update(chunk)
                content.append(
                    {"path": path, "kind": "file", "sha256": digest.hexdigest()}
                )
            else:
                content.append({"path": path, "kind": "deleted", "sha256": None})
        counts = {}
        for record in records:
            counts[record["status"]] = counts.get(record["status"], 0) + 1
        checkpoint = self.last_checkpoint_id
        tests = (
            "run=%s; passed=%s; failed=%s; skipped=%s; commands=%s"
            % (
                checkpoint.tests_run,
                checkpoint.tests_passed,
                checkpoint.tests_failed,
                checkpoint.tests_skipped,
                checkpoint.test_commands_summary or "",
            )
            if checkpoint
            else "No checkpoint test evidence."
        )
        return {
            "current_head": self.current_head,
            "dirty_digest": _digest_status(status.stdout),
            "changed_files": paths,
            "changed_files_summary": "\n".join(paths),
            "changed_files_digest": _canonical_hash(content),
            "git_status_summary": self.git_status_summary or "",
            "diff_summary": "Changed paths: %s; statuses: %s"
            % (
                len(paths),
                ", ".join(
                    "%s=%s" % (status_code, counts[status_code])
                    for status_code in sorted(counts)
                ),
            ),
            "tests_summary": tests,
            "checkpoint_id": checkpoint.id,
        }

    def _default_commit_message(self):
        self.ensure_one()
        title = re.sub(r"\s+", " ", self.work_item_id.name or "Reviewed change").strip()
        subject = "[DW-%s] %s" % (self.work_item_id.id, title)
        subject = subject[:200].rstrip()
        return _safe_commit_message(
            "%s\n\nWork Item: DW-%s\nApproved Plan revision: %s\nTests: %s"
            % (
                subject,
                self.work_item_id.id,
                self.plan_revision,
                (
                    self.last_checkpoint_id.test_commands_summary
                    if self.last_checkpoint_id
                    else "See Dev Hub checkpoint"
                ),
            )
        )

    def action_review_changes(self):
        self.ensure_one()
        self._require_commit_manager()
        if self.state not in ("review_required", "commit_approved"):
            raise UserError("Changes may be reviewed only at the human review gate.")
        self._assert_no_worker_lease()
        binding = self._review_change_binding()
        self.sudo()._internal_write(
            {
                "changed_files_digest": binding["changed_files_digest"],
                "review_diff_summary": binding["diff_summary"],
                "review_tests_summary": binding["tests_summary"],
            }
        )
        self._event("commit_reviewed", "Human opened the bounded Git change review")
        return self._form_action()

    def action_open_commit_approval(self):
        self.ensure_one()
        self.action_review_changes()
        if self.state != "review_required":
            raise UserError("A fresh commit approval requires Review Required state.")
        return {
            "type": "ir.actions.act_window",
            "name": "Approve Git Commit",
            "res_model": "dev.git.commit.approval.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_workspace_id": self.id,
                "default_commit_message": self._default_commit_message(),
            },
        }

    def create_commit_approval(self, commit_message):
        self.ensure_one()
        self._require_commit_manager()
        if self.state != "review_required":
            raise UserError("Commit approval requires Review Required state.")
        self._assert_no_worker_lease()
        self._assert_worker_identity(require_effective=True)
        self._assert_plan_unchanged()
        self.environment_id._assert_dev_hub_safe(self.project_id)
        binding = self._review_change_binding()
        message = _safe_commit_message(commit_message)
        main = self._main_snapshot(self.repository_id)
        previous = self.commit_approval_ids.filtered(
            lambda approval: approval.approval_state == "approved"
        )
        for approval in previous:
            self.env["dev.git.commit.approval.event"].sudo().with_context(
                dev_git_commit_event=True
            ).create(
                {
                    "approval_id": approval.id,
                    "event_type": "superseded",
                    "actor_id": self.env.user.id,
                    "summary": "Superseded by a fresh exact-state approval",
                }
            )
        approval = self.env["dev.git.commit.approval"].sudo().with_context(
            dev_git_commit_approval=True
        ).create(
            {
                "work_item_id": self.work_item_id.id,
                "workspace_id": self.id,
                "branch": self.execution_branch,
                "current_head": binding["current_head"],
                "dirty_digest": binding["dirty_digest"],
                "changed_files_digest": binding["changed_files_digest"],
                "changed_files_summary": binding["changed_files_summary"],
                "git_status_summary": binding["git_status_summary"],
                "diff_summary": binding["diff_summary"],
                "plan_id": self.plan_id.id,
                "plan_hash": self.approved_plan_hash,
                "policy_hash": self.policy_hash,
                "execution_contract_hash": self.execution_contract_hash,
                "approver_id": self.env.user.id,
                "approved_at": fields.Datetime.now(),
                "commit_message": message,
                "commit_message_hash": hashlib.sha256(message.encode()).hexdigest(),
                "binding_hash": "pending",
                "main_branch": main["branch"],
                "main_head": main["head"],
                "main_dirty_digest": main["digest"],
                "checkpoint_id": binding["checkpoint_id"],
                "tests_summary": binding["tests_summary"],
            }
        )
        self.sudo()._internal_write(
            {
                "state": "commit_approved",
                "commit_approval_id": approval.id,
                "changed_files_digest": binding["changed_files_digest"],
                "review_diff_summary": binding["diff_summary"],
                "review_tests_summary": binding["tests_summary"],
            }
        )
        self._event(
            "commit_approved",
            "Human approved one exact-state local Git commit",
            {"approval_id": approval.id},
        )
        return approval

    def _assert_commit_approval_current(self, approval):
        self.ensure_one()
        if not approval:
            raise AccessError("A human commit approval is required.")
        approval.ensure_one()
        self._require_commit_manager()
        if self.state != "commit_approved" or self.commit_approval_id != approval:
            raise AccessError("No current human commit approval is bound to this workspace.")
        if approval.event_ids:
            raise AccessError("The Git commit approval is no longer active.")
        approval.assert_integrity()
        self._assert_no_worker_lease()
        self._assert_worker_identity(require_effective=True)
        self._assert_plan_unchanged()
        self.environment_id._assert_dev_hub_safe(self.project_id)
        binding = self._review_change_binding()
        expected = {
            "branch": (self.execution_branch, approval.branch),
            "HEAD": (binding["current_head"], approval.current_head),
            "dirty digest": (binding["dirty_digest"], approval.dirty_digest),
            "changed-files digest": (
                binding["changed_files_digest"],
                approval.changed_files_digest,
            ),
            "Plan": (self.plan_id.id, approval.plan_id.id),
            "Plan hash": (self.approved_plan_hash, approval.plan_hash),
            "policy hash": (self.policy_hash, approval.policy_hash),
            "execution contract hash": (
                self.execution_contract_hash,
                approval.execution_contract_hash,
            ),
            "commit message hash": (
                hashlib.sha256(approval.commit_message.encode()).hexdigest(),
                approval.commit_message_hash,
            ),
        }
        mismatches = [name for name, values in expected.items() if values[0] != values[1]]
        if mismatches:
            raise AccessError(
                "Commit approval is stale; fresh human review is required (%s)."
                % ", ".join(mismatches)
            )
        return binding

    def action_open_commit_execution(self):
        self.ensure_one()
        approval = self.commit_approval_id
        self._assert_commit_approval_current(approval)
        return {
            "type": "ir.actions.act_window",
            "name": "Confirm Approved Git Commit",
            "res_model": "dev.git.commit.execution.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_workspace_id": self.id,
                "default_approval_id": approval.id,
            },
        }

    def _run_bounded_commit_git(self, args, input_data=None, check=True):
        self.ensure_one()
        command = [
            "git",
            "-c",
            "safe.directory=%s" % os.path.realpath(self.worktree_path),
            "-C",
            self.worktree_path,
            *args,
        ]
        environment = {
            "PATH": "/usr/bin:/bin",
            "HOME": "/nonexistent",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
            "LANG": "C",
            "GIT_AUTHOR_NAME": COMMIT_AUTHOR_NAME,
            "GIT_AUTHOR_EMAIL": COMMIT_AUTHOR_EMAIL,
            "GIT_COMMITTER_NAME": COMMIT_AUTHOR_NAME,
            "GIT_COMMITTER_EMAIL": COMMIT_AUTHOR_EMAIL,
        }
        result = subprocess.run(
            command,
            input=input_data,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60,
            check=False,
            env=environment,
        )
        if check and result.returncode:
            raise UserError(
                "Bounded Git commit failed safely: %s"
                % result.stderr.decode("utf-8", "replace")[:1000]
            )
        return result

    def _staged_content_digest(self, paths):
        self.ensure_one()
        content = []
        for path in sorted(paths):
            shown = self._run_bounded_commit_git(
                ["show", ":%s" % path], check=False
            )
            if shown.returncode:
                content.append({"path": path, "kind": "deleted", "sha256": None})
            else:
                content.append(
                    {
                        "path": path,
                        "kind": "file",
                        "sha256": hashlib.sha256(shown.stdout).hexdigest(),
                    }
                )
        return _canonical_hash(content)

    def execute_approved_commit(self, approval):
        self.ensure_one()
        self.env.cr.execute(
            "SELECT id FROM dev_execution_workspace WHERE id = %s FOR UPDATE NOWAIT",
            [self.id],
        )
        binding = self._assert_commit_approval_current(approval)
        paths = binding["changed_files"]
        parent = approval.current_head
        self._run_bounded_commit_git(["add", "--", *paths])
        staged = self._run_bounded_commit_git(
            ["diff", "--cached", "--name-only", "--no-renames", "-z", parent]
        )
        staged_paths = [
            _validate_repository_relative_path(raw_path, self.worktree_path)
            for raw_path in staged.stdout.rstrip(b"\0").split(b"\0")
            if raw_path
        ]
        if set(staged_paths) != set(paths):
            raise AccessError("Staged files differ from the human-reviewed change set.")
        if self._staged_content_digest(paths) != approval.changed_files_digest:
            raise AccessError("Staged content differs from the human-reviewed change set.")
        unstaged = self._run_bounded_commit_git(
            ["diff", "--name-only", "-z"], check=True
        )
        if unstaged.stdout:
            raise AccessError("Files changed after staging; fresh human review is required.")
        staged_status = self._run_bounded_commit_git(
            ["status", "--porcelain=v1", "-z", "--untracked-files=all"]
        )
        staged_records = _parse_git_porcelain_v1_z(
            staged_status.stdout, self.worktree_path
        )
        if set(_git_policy_paths(staged_records)) != set(paths):
            raise AccessError(
                "Unexpected files appeared after approval; fresh review is required."
            )
        self._run_bounded_commit_git(
            [
                "-c",
                "user.name=%s" % COMMIT_AUTHOR_NAME,
                "-c",
                "user.email=%s" % COMMIT_AUTHOR_EMAIL,
                "commit",
                "-F",
                "-",
            ],
            input_data=approval.commit_message.encode("utf-8"),
        )
        head = self._run_bounded_commit_git(["rev-parse", "HEAD"]).stdout.decode().strip()
        if not SHA1_RE.fullmatch(head) or head == parent:
            raise UserError("Git commit did not create the expected new commit.")
        actual_parent = (
            self._run_bounded_commit_git(["rev-parse", "%s^" % head])
            .stdout.decode()
            .strip()
        )
        count = (
            self._run_bounded_commit_git(["rev-list", "--count", "%s..%s" % (parent, head)])
            .stdout.decode()
            .strip()
        )
        committed = self._run_bounded_commit_git(
            ["diff-tree", "--no-commit-id", "--name-only", "-r", "--no-renames", "-z", head]
        )
        committed_paths = [
            _validate_repository_relative_path(raw_path, self.worktree_path)
            for raw_path in committed.stdout.rstrip(b"\0").split(b"\0")
            if raw_path
        ]
        status = self._run_bounded_commit_git(
            ["status", "--porcelain=v1", "-z", "--untracked-files=all"]
        )
        if (
            actual_parent != parent
            or count != "1"
            or set(committed_paths) != set(paths)
            or status.stdout
        ):
            raise UserError("Post-commit Git validation failed; human investigation required.")
        main = self._main_snapshot(self.repository_id)
        if (
            main["branch"] != approval.main_branch
            or main["head"] != approval.main_head
            or main["digest"] != approval.main_dirty_digest
        ):
            raise UserError("Main worktree changed during commit; evidence is preserved.")
        committed_at = fields.Datetime.now()
        record = self.env["dev.git.commit.record"].sudo().with_context(
            dev_git_commit_record=True
        ).create(
            {
                "work_item_id": self.work_item_id.id,
                "workspace_id": self.id,
                "approval_id": approval.id,
                "branch": self.execution_branch,
                "parent_sha": parent,
                "commit_sha": head,
                "committed_files_summary": "\n".join(committed_paths),
                "approver_id": approval.approver_id.id,
                "committed_at": committed_at,
                "commit_message_hash": approval.commit_message_hash,
                "test_evidence_references": approval.tests_summary,
                "author_name": COMMIT_AUTHOR_NAME,
                "author_email": COMMIT_AUTHOR_EMAIL,
                "audit_hash": "pending",
            }
        )
        self.env["dev.git.commit.approval.event"].sudo().with_context(
            dev_git_commit_event=True
        ).create(
            {
                "approval_id": approval.id,
                "event_type": "consumed",
                "actor_id": self.env.user.id,
                "summary": "Exact-state approval consumed by one local commit",
                "payload_json": json.dumps({"commit_sha": head}, sort_keys=True),
            }
        )
        self._validate_physical()
        self.sudo()._internal_write(
            {
                "state": "committed_reviewed",
                "commit_record_id": record.id,
                "committed_sha": head,
                "committed_parent_sha": parent,
                "committed_at": committed_at,
            }
        )
        self._event(
            "commit_created",
            "One human-approved local Git commit created; no push performed",
            {"commit_sha": head, "approval_id": approval.id},
        )
        return record

    def action_reject_commit_changes(self):
        self.ensure_one()
        self._require_commit_manager()
        if self.state not in ("review_required", "commit_approved"):
            raise UserError("Only reviewed changes may return to implementation.")
        self._assert_no_worker_lease()
        if self.commit_approval_id and not self.commit_approval_id.event_ids:
            self.env["dev.git.commit.approval.event"].sudo().with_context(
                dev_git_commit_event=True
            ).create(
                {
                    "approval_id": self.commit_approval_id.id,
                    "event_type": "rejected",
                    "actor_id": self.env.user.id,
                    "summary": "Human rejected the reviewed change set",
                }
            )
        checkpoint = self.env["dev.work.checkpoint"].sudo().create(
            {
                "work_item_id": self.work_item_id.id,
                "execution_workspace_id": self.id,
                "trigger": "client_review",
                "lifecycle_phase": self.work_item_id.current_phase,
                "approved_plan_id": self.plan_id.id,
                "next_recommended_step": "Revise implementation after human rejection.",
                "last_agent_note": "Human returned reviewed changes to implementation.",
                "repository_id": self.repository_id.id,
                "working_directory": self.worktree_path,
                "branch": self.execution_branch,
                "git_head": self.current_head,
                "base_head": self.base_head,
                "dirty_summary": self.dirty_summary,
                "dirty_digest": self.dirty_digest,
                "files_touched_summary": self.changed_files_summary,
                "environment_id": self.environment_id.id,
                "machine_id": self.machine_id.id,
            }
        )
        if self.work_item_id.current_phase == "ready_for_review":
            self.work_item_id.sudo().transition_lifecycle(
                "implementing", "Human returned changes to implementation"
            )
        self.sudo()._internal_write(
            {
                "state": "ready",
                "commit_approval_id": False,
                "last_checkpoint_id": checkpoint.id,
            }
        )
        self._event(
            "commit_rejected",
            "Human rejected commit and returned workspace to implementation",
            {"checkpoint_id": checkpoint.id},
        )
        return True
