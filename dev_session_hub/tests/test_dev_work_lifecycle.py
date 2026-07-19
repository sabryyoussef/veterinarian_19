# -*- coding: utf-8 -*-
import hashlib
import json
import socket
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from psycopg2.errors import UniqueViolation

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, new_test_user, tagged
from odoo.addons.dev_session_hub.models.dev_execution import _canonical_child, _slug


@tagged("post_install", "-at_install")
class TestDevWorkLifecycle(TransactionCase):
    """Behavioral coverage for the Phase 1-4 development-work contract."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.dev_project = cls.env.ref("dev_session_hub.dev_project_petspot")
        cls.repository = cls.env.ref("dev_session_hub.dev_repository_petspot")
        cls.environment = cls.env.ref("dev_session_hub.dev_environment_petspot_test")
        cls.windows = cls.env.ref("dev_session_hub.dev_client_windows_desktop")
        cls.ubuntu = cls.env.ref("dev_session_hub.dev_client_ubuntu_precision")
        cls.task_link = cls.env.ref("dev_session_hub.dev_task_petspot_wp337")

        cls.backend = cls.env["openproject.backend"].create(
            {
                "name": "Dev Hub lifecycle test backend",
                "api_url": "http://127.0.0.1:9",
                "public_url": "https://openproject.test.invalid",
                "verify_ssl": True,
                "enable_pull": False,
                "enable_push": False,
            }
        )
        cls.odoo_project = cls.env["project.project"].create(
            {"name": "Dev Hub lifecycle test project"}
        )
        cls.odoo_task = cls.env["project.task"].create(
            {
                "name": "Lifecycle work package 880001",
                "project_id": cls.odoo_project.id,
                "op_backend_id": cls.backend.id,
                "op_work_package_id": 880001,
                "op_url": "https://openproject.test.invalid/work_packages/880001",
            }
        )
        cls.machine = cls.env["dev.machine"].create(
            {
                "name": "Lifecycle non-production target",
                "hostname": socket.gethostname(),
                "tailscale_name": "lifecycle-test.tailcf9988.ts.net",
                "tailscale_ip_reference": "100.64.0.98",
                "tailscale_destination_verified": True,
                "tailscale_verified_at": "2026-07-18 16:20:00",
                "pinned_host_key_fingerprint": (
                    "SHA256:BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"
                ),
                "ssh_alias": "lifecycle-test-ts",
                "role": "TransactionCase target only",
                "trust_zone": "trusted_dev",
                "production": False,
                "allowed_path_prefixes": cls.repository.working_directory,
            }
        )
        cls.environment.machine_id = cls.machine
        cls.snapshot = {
            "branch": "feature/dev-work-lifecycle",
            "head": "a" * 40,
            "dirty": "staged=0; unstaged=2; untracked=1; conflicts=0; digest=abc123",
            "captured_at": "2026-07-18 16:20:00",
        }
        cls.commit_manager = new_test_user(
            cls.env,
            login="dev-hub-commit-manager-%s" % uuid.uuid4().hex,
            groups=(
                "dev_session_hub.group_dev_hub_user,"
                "dev_session_hub.group_dev_hub_manager"
            ),
        )
        cls.dev_project.write({"member_ids": [(4, cls.commit_manager.id)]})

        required_models = {
            "dev.work.item",
            "dev.work.lifecycle.event",
            "dev.work.source.message",
            "dev.work.analysis",
            "dev.work.plan",
            "dev.work.plan.step",
            "dev.work.approval",
            "dev.work.checkpoint",
            "dev.completion.report",
            "dev.work.communication",
            "dev.external.outbox",
            "dev.work.generation",
            "dev.execution.workspace",
            "dev.execution.workspace.event",
            "dev.git.commit.approval",
            "dev.git.commit.approval.event",
            "dev.git.commit.record",
            "dev.git.remote",
            "dev.git.push.approval",
            "dev.git.push.approval.event",
            "dev.git.push.record",
            "dev.git.pr.target",
            "dev.git.pr.approval",
            "dev.git.pr.approval.event",
            "dev.git.pr.record",
        }
        missing = sorted(name for name in required_models if name not in cls.env)
        if missing:
            raise AssertionError("Missing lifecycle models: %s" % ", ".join(missing))

    def setUp(self):
        super().setUp()
        self._commit_wp_sequence = 890000
        launcher = patch.object(
            type(self.env["dev.session"]),
            "_pin_enforced_launcher_available",
            autospec=True,
            return_value=True,
        )
        launcher.start()
        self.addCleanup(launcher.stop)
        open_launcher = patch.object(
            type(self.env["dev.session"]),
            "_open_launcher",
            autospec=True,
            return_value={"type": "disabled-launcher-test-double"},
        )
        open_launcher.start()
        self.addCleanup(open_launcher.stop)

    def _model_vals(self, model_name, **values):
        """Keep fixtures compatible with optional presentation-only fields."""
        fields = self.env[model_name]._fields
        return {name: value for name, value in values.items() if name in fields}

    def _work(self, wp_id=880001, task=None, **extra):
        source_key = uuid.uuid4().hex
        source = self.env["dev.work.source.message"].create(
            {
                "provider": "manual",
                "provider_message_id": source_key,
                "chatwoot_account_id": 1,
                "chatwoot_inbox_id": 2,
                "chatwoot_conversation_id": 775,
                "chatwoot_message_id": 776,
                "group_jid": "120363000000000000@g.us",
                "message_timestamp": "2026-07-18 16:20:00",
                "text_snapshot": "Sanitized lifecycle test request %s" % source_key,
            }
        )
        values = {
            "name": "Lifecycle test work",
            "dev_project_id": self.dev_project.id,
            "odoo_project_id": self.odoo_project.id,
            "odoo_task_id": (task or self.odoo_task).id,
            "op_backend_id": self.backend.id if wp_id else False,
            "op_work_package_id": wp_id,
            "op_reference": "WP #%s" % wp_id,
            "op_url": "https://openproject.test.invalid/work_packages/%s" % wp_id,
            "responsible_user_id": self.env.user.id,
            "preferred_repository_id": self.repository.id,
            "preferred_environment_id": self.environment.id,
            "source_message_ids": [(4, source.id)],
        }
        values.update(extra)
        return self.env["dev.work.item"].create(
            self._model_vals("dev.work.item", **values)
        )

    def _call(self, record, names, *args):
        for name in names:
            method = getattr(record, name, None)
            if method:
                return method(*args)
        self.fail("%s implements none of %s" % (record._name, ", ".join(names)))

    def _transition(self, work, phase):
        method = getattr(work, "transition_lifecycle", None)
        if method:
            return method(phase, "TransactionCase transition to %s" % phase)
        method = getattr(work, "action_transition", None)
        if method:
            return method(phase)
        method = getattr(work, "_transition", None)
        if method:
            return method(phase)
        method = getattr(work, "_transition_phase", None)
        if method:
            return method(phase)
        return self._call(
            work,
            (
                "action_%s" % phase,
                "action_mark_%s" % phase,
                "action_set_%s" % phase,
            ),
        )

    def _snapshot_patch(self, snapshot=None):
        return patch.object(
            type(self.env["dev.session"]),
            "_capture_git_snapshot",
            autospec=True,
            return_value=snapshot or self.snapshot,
        )

    def _session(self, work, client=None, environment=None, machine=None):
        environment = environment or self.environment
        machine = machine or self.machine
        return self.env["dev.session"].create(
            {
                "client_id": (client or self.windows).id,
                "project_id": self.dev_project.id,
                "environment_id": environment.id,
                "machine_id": machine.id,
                "repository_id": self.repository.id,
                "working_directory": self.repository.working_directory,
                "task_link_id": self.task_link.id,
                "work_item_id": work.id,
            }
        )

    def _analysis(self, work):
        return self.env["dev.work.analysis"].create(
            self._model_vals(
                "dev.work.analysis",
                work_item_id=work.id,
                revision=1,
                status="draft",
                problem_summary="A bounded lifecycle test problem",
                original_request_snapshot="Please fix the test-only behavior.",
                reproduction_context="Reproduce in the isolated test database.",
                current_behavior="The workflow is incomplete.",
                expected_behavior="The workflow is controlled and auditable.",
                technical_findings="No external service is required.",
                affected_modules_files="dev_session_hub",
                risks="No production access.",
                dependencies="project, openproject_sync",
                open_questions="None",
                evidence_references="test://analysis/1",
                origin="manual",
                repository_observed=self.repository.working_directory,
                head_observed="a" * 40,
            )
        )

    def _plan(self, work, with_step=False):
        plan = self.env["dev.work.plan"].create(
            self._model_vals(
                "dev.work.plan",
                work_item_id=work.id,
                revision=1,
                status="draft",
                goal="Implement the bounded lifecycle.",
                scope="Odoo models and tests.",
                out_of_scope="Production and autonomous workers.",
                proposed_changes="Add lifecycle records.",
                affected_modules_files="dev_session_hub",
                migration_impact="None in TransactionCase.",
                security_impact="No direct external transport.",
                test_plan="Run post-install TransactionCase tests.",
                rollback_plan="Uninstall the test-only module.",
                dependencies="project, openproject_sync",
                risks="Incorrect lifecycle transition.",
                acceptance_criteria="All requested lifecycle tests pass.",
                origin="manual",
            )
        )
        if with_step:
            self.env["dev.work.plan.step"].create(
                {
                    "plan_id": plan.id,
                    "step_key": "S1",
                    "sequence": 1,
                    "title": "Implement the bounded lifecycle",
                    "description": "No external calls.",
                }
            )
        return plan

    def _accept_analysis(self, analysis):
        return self._call(
            analysis,
            ("action_accept", "action_mark_accepted", "action_set_accepted"),
        )

    def _submit_plan(self, plan):
        return self._call(
            plan,
            (
                "action_request_approval",
                "action_submit_for_approval",
                "action_await_approval",
            ),
        )

    def _approve_plan(self, plan):
        return self._call(
            plan,
            ("action_approve_exact", "action_approve", "action_approve_exact_hash"),
        )

    def _approved_plan(self, work):
        if work.lifecycle_phase == "received":
            self._transition(work, "triage")
            self._transition(work, "registered")
            self._transition(work, "analyzing")
            analysis = self._analysis(work)
            self._accept_analysis(analysis)
            self._transition(work, "planning")
        plan = self._plan(work, with_step=True)
        self._submit_plan(plan)
        self._approve_plan(plan)
        return plan

    def _commit_review_workspace(self):
        self._commit_wp_sequence += 1
        wp_id = self._commit_wp_sequence
        task = self.env["project.task"].create(
            {
                "name": "Commit review work package %s" % wp_id,
                "project_id": self.odoo_project.id,
                "op_backend_id": self.backend.id,
                "op_work_package_id": wp_id,
                "op_url": "https://openproject.test.invalid/work_packages/%s" % wp_id,
            }
        )
        work = self._work(wp_id=wp_id, task=task)
        plan = self._approved_plan(work)
        workspace = self._workspace_proposal(work)
        step = plan.step_ids[:1]
        step.write({"status": "in_progress"})
        step.write({"status": "done"})
        self._transition(work, "implementing")
        self._transition(work, "testing")
        checkpoint = self.env["dev.work.checkpoint"].sudo().create(
            {
                "work_item_id": work.id,
                "execution_workspace_id": workspace.id,
                "trigger": "agent_handoff",
                "lifecycle_phase": "testing",
                "approved_plan_id": plan.id,
                "next_recommended_step": "Human reviews exact Git changes.",
                "working_directory": workspace.worktree_path,
                "branch": workspace.execution_branch,
                "git_head": workspace.base_head,
                "base_head": workspace.base_head,
                "dirty_summary": "changed=1",
                "dirty_digest": "d" * 64,
                "files_touched_summary": "tests/approved.py",
                "tests_run": 1,
                "tests_passed": 1,
                "tests_failed": 0,
                "test_commands_summary": "approved-targeted-test",
            }
        )
        report = self.env["dev.completion.report"].create(
            {
                "work_item_id": work.id,
                "plan_id": plan.id,
                "original_request_summary": "One bounded Test-only change.",
                "implemented_summary": "Added one approved Test file.",
                "completed_steps_summary": step.step_key,
                "changed_components_summary": "tests/approved.py",
                "repository_reference": self.repository.name,
                "branch": workspace.execution_branch,
                "tests_summary": "1/1 passed.",
                "uat_status": "passed",
                "known_limitations": "Local review only.",
                "rollback_notes": "Discard the uncommitted Test file.",
            }
        )
        report.action_ready_review()
        self._transition(work, "ready_for_review")
        workspace._internal_write(
            {
                "state": "review_required",
                "current_head": workspace.base_head,
                "dirty_summary": "changed=1",
                "dirty_digest": "d" * 64,
                "changed_files_summary": "tests/approved.py",
                "git_status_summary": '?? "tests/approved.py"',
                "last_checkpoint_id": checkpoint.id,
            }
        )
        return work, plan, workspace, checkpoint

    def _commit_binding(self, workspace, checkpoint=None):
        checkpoint = checkpoint or workspace.last_checkpoint_id
        return {
            "current_head": workspace.base_head,
            "dirty_digest": "d" * 64,
            "changed_files": ["tests/approved.py"],
            "changed_files_summary": "tests/approved.py",
            "changed_files_digest": "c" * 64,
            "git_status_summary": '?? "tests/approved.py"',
            "diff_summary": "Changed paths: 1; statuses: ??=1",
            "tests_summary": "run=1; passed=1; failed=0",
            "checkpoint_id": checkpoint.id,
        }

    def _create_commit_approval(self, workspace, binding=None):
        binding = binding or self._commit_binding(workspace)
        workspace = workspace.with_user(self.commit_manager)
        with patch.object(
            type(workspace),
            "_assert_worker_identity",
            autospec=True,
            return_value=True,
        ), patch.object(
            type(workspace),
            "_assert_plan_unchanged",
            autospec=True,
            return_value=True,
        ), patch.object(
            type(workspace),
            "_review_change_binding",
            autospec=True,
            return_value=binding,
        ), patch.object(
            type(workspace),
            "_main_snapshot",
            autospec=True,
            return_value={
                "branch": "main",
                "head": workspace.base_head,
                "dirty": "clean",
                "digest": "0" * 64,
            },
        ):
            return workspace.create_commit_approval(
                "[DW-%s] Add approved Test file" % workspace.work_item_id.id
            )

    def _push_review_workspace(self):
        work, plan, workspace, checkpoint = self._commit_review_workspace()
        commit_approval = self._create_commit_approval(workspace)
        commit_sha = "b" * 40
        committed_at = fields.Datetime.now()
        commit_record = (
            self.env["dev.git.commit.record"]
            .sudo()
            .with_context(dev_git_commit_record=True)
            .create(
                {
                    "work_item_id": work.id,
                    "workspace_id": workspace.id,
                    "approval_id": commit_approval.id,
                    "branch": workspace.execution_branch,
                    "parent_sha": workspace.base_head,
                    "commit_sha": commit_sha,
                    "committed_files_summary": "tests/approved.py",
                    "approver_id": self.commit_manager.id,
                    "committed_at": committed_at,
                    "commit_message_hash": commit_approval.commit_message_hash,
                    "author_name": "Dev Worker",
                    "author_email": "devworker@devhub.invalid",
                    "audit_hash": "pending",
                }
            )
        )
        self.repository.write({"approved_push_root": "/srv/devhub-uat/remotes"})
        remote = self.env["dev.git.remote"].create(
            {
                "name": "uat-%s" % uuid.uuid4().hex[:8],
                "repository_id": self.repository.id,
                "remote_url": "/srv/devhub-uat/remotes/push-%s.git"
                % uuid.uuid4().hex,
                "protocol": "file",
                "approved": True,
                "non_production": True,
                "allowed_branch_prefix": "devhub/",
            }
        )
        workspace._internal_write(
            {
                "state": "committed_reviewed",
                "current_head": commit_sha,
                "dirty_summary": "changed=0",
                "dirty_digest": "0" * 64,
                "commit_record_id": commit_record.id,
                "committed_sha": commit_sha,
                "committed_parent_sha": workspace.base_head,
                "committed_at": committed_at,
            }
        )
        return work, plan, workspace, remote, commit_record, checkpoint

    def _push_git_fake(self, workspace, remote, heads=None, tags=None):
        heads = heads or {}
        tags = tags or {}
        lines = [
            "%s\trefs/heads/%s" % (sha, name) for name, sha in sorted(heads.items())
        ] + ["%s\trefs/tags/%s" % (sha, name) for name, sha in sorted(tags.items())]

        def fake(_workspace, args, check=True):
            if args == ["remote", "get-url", remote.name]:
                return SimpleNamespace(
                    returncode=0, stdout=(remote.remote_url + "\n").encode(), stderr=b""
                )
            if args == ["fetch", "--no-tags", "--prune", remote.name]:
                return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
            if args == ["ls-remote", "--heads", "--tags", remote.name]:
                output = ("\n".join(lines) + ("\n" if lines else "")).encode()
                return SimpleNamespace(returncode=0, stdout=output, stderr=b"")
            if args[:2] == ["merge-base", "--is-ancestor"]:
                return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
            if args and args[0] == "rev-list":
                return SimpleNamespace(returncode=0, stdout=b"1\n", stderr=b"")
            raise AssertionError("Unexpected Push Git call: %r" % (args,))

        return fake

    def _create_push_approval(self, workspace, remote, heads=None, tags=None):
        workspace = workspace.with_user(self.commit_manager)
        fake = self._push_git_fake(workspace, remote, heads=heads, tags=tags)
        with patch.object(
            type(workspace), "_assert_worker_identity", autospec=True, return_value=True
        ), patch.object(
            type(workspace), "_assert_plan_unchanged", autospec=True, return_value=True
        ), patch.object(
            type(workspace), "_validate_physical", autospec=True, return_value=True
        ), patch.object(
            type(workspace), "_run_push_git", autospec=True, side_effect=fake
        ):
            return workspace.create_push_approval(remote)

    def _pr_review_workspace(self):
        work, plan, workspace, _file_remote, commit_record, checkpoint = (
            self._push_review_workspace()
        )
        remote = self.env["dev.git.remote"].create(
            {
                "name": "github-uat-%s" % uuid.uuid4().hex[:8],
                "repository_id": self.repository.id,
                "remote_url": "https://github.com/example/devhub-uat.git",
                "protocol": "https",
                "approved": True,
                "non_production": True,
                "allowed_branch_prefix": "devhub/",
                "credential_profile_reference": "/srv/devhub/credentials/github-pr",
            }
        )
        push_approval = self._create_push_approval(workspace, remote)
        now = fields.Datetime.now()
        push_record = (
            self.env["dev.git.push.record"]
            .sudo()
            .with_context(dev_git_push_record=True)
            .create(
                {
                    "work_item_id": work.id,
                    "workspace_id": workspace.id,
                    "approval_id": push_approval.id,
                    "remote_id": remote.id,
                    "local_branch": workspace.execution_branch,
                    "remote_branch": workspace.execution_branch,
                    "commit_sha": workspace.committed_sha,
                    "remote_head_after": workspace.committed_sha,
                    "approver_id": self.commit_manager.id,
                    "pushed_at": now,
                    "result": "success",
                    "verification_result": "exact branch verified",
                    "reconciliation_state": "pushed",
                    "approved_pre_refs_digest": push_approval.remote_heads_digest,
                    "expected_remote_head": workspace.committed_sha,
                    "observed_post_refs_digest": "f" * 64,
                    "reconciled_at": now,
                    "reconciliation_result": "exact expected source commit verified",
                    "audit_hash": "pending",
                }
            )
        )
        target = self.env["dev.git.pr.target"].create(
            {
                "name": "GitHub staging %s" % uuid.uuid4().hex[:8],
                "repository_id": self.repository.id,
                "source_remote_id": remote.id,
                "target_repository_id": self.repository.id,
                "github_repository": "example/devhub-uat",
                "target_branch": "staging",
                "allowed_target_branches": "develop\ntest\nstaging",
                "credential_profile_reference": "/srv/devhub/credentials/github-pr",
                "credential_broker_reference": (
                    "/srv/devhub/credentials/github/mint-devhub-pr-token"
                ),
                "credential_type": "github_app",
                "github_app_slug": "devhub-pr-uat",
                "github_app_id": 1001,
                "github_installation_id": 2001,
                "credential_owner_reference": "devhub-pr-uat",
                "credential_repository_restriction": "example/devhub-uat",
                "credential_permission_summary": (
                    "contents:read\nmetadata:read\npull_requests:write"
                ),
                "credential_expires_at": fields.Datetime.add(
                    fields.Datetime.now(), minutes=50
                ),
                "credential_validated_at": fields.Datetime.now(),
                "credential_validation_digest": "9" * 64,
                "approved": True,
                "non_production": True,
            }
        )
        workspace._internal_write(
            {
                "state": "pushed_reviewed",
                "push_remote_id": remote.id,
                "push_remote_branch": workspace.execution_branch,
                "push_remote_head": workspace.committed_sha,
                "push_record_id": push_record.id,
                "pushed_at": now,
            }
        )
        return work, plan, workspace, remote, target, commit_record, checkpoint

    def _pr_base_patches(self, workspace):
        snapshot = {
            "heads": {workspace.execution_branch: workspace.committed_sha},
            "tags": {},
            "heads_json": "{}",
            "tags_json": "{}",
            "heads_digest": "a" * 64,
            "tags_digest": "b" * 64,
            "target_head": workspace.committed_sha,
        }
        return (
            patch.object(
                type(workspace),
                "_assert_worker_identity",
                autospec=True,
                return_value=True,
            ),
            patch.object(
                type(workspace),
                "_assert_plan_unchanged",
                autospec=True,
                return_value=True,
            ),
            patch.object(
                type(workspace),
                "_validate_physical",
                autospec=True,
                return_value=True,
            ),
            patch.object(
                type(workspace),
                "_remote_snapshot",
                autospec=True,
                return_value=snapshot,
            ),
            patch.object(
                type(workspace),
                "_assert_scoped_github_identity",
                autospec=True,
                return_value=True,
            ),
        )

    def _create_pr_approval(self, workspace, target, title=None, body=None):
        workspace = workspace.with_user(self.commit_manager)
        title = title or "[DW-%s] Controlled PR" % workspace.work_item_id.id
        body = body or "Controlled implementation summary.\n\nTests: all passed."
        patches = self._pr_base_patches(workspace)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patch.object(
            type(workspace),
            "_github_json",
            autospec=True,
            return_value={"ref": "refs/heads/staging"},
        ), patch.object(
            type(workspace), "_matching_open_prs", autospec=True, return_value=[]
        ):
            workspace._internal_write(
                {
                    "pr_target_id": target.id,
                    "pr_source_branch": workspace.execution_branch,
                    "pr_source_sha": workspace.committed_sha,
                    "pr_target_branch": target.target_branch,
                    "pr_title_preview": title,
                    "pr_body_preview": body,
                    "pr_body_digest": hashlib.sha256(body.encode()).hexdigest(),
                }
            )
            return workspace.create_pr_approval(target, title, body)

    def _approved_report(self, work):
        plan = self._approved_plan(work)
        step = plan.step_ids[:1]
        step.write({"status": "in_progress"})
        step.write({"status": "done"})
        self._transition(work, "implementing")
        self._transition(work, "testing")
        self.env["dev.work.checkpoint"].sudo().create(
            {
                "work_item_id": work.id,
                "trigger": "client_review",
                "lifecycle_phase": "testing",
                "next_recommended_step": "Review completion report.",
            }
        )
        report = self.env["dev.completion.report"].create(
            {
                "work_item_id": work.id,
                "plan_id": plan.id,
                "original_request_summary": "Safe original request",
                "implemented_summary": "Implemented lifecycle controls.",
                "completed_steps_summary": "S1",
                "changed_components_summary": "dev_session_hub only",
                "repository_reference": self.repository.working_directory,
                "branch": "feature/dev-work-lifecycle",
                "tests_summary": "TransactionCase passed.",
                "uat_status": "not_applicable",
                "known_limitations": "No production deployment.",
                "rollback_notes": "No deployment was performed.",
            }
        )
        report.action_ready_review()
        self._transition(work, "ready_for_review")
        report.action_approve()
        self._transition(work, "completed")
        return report

    def _new_revision(self, record):
        result = self._call(
            record,
            ("action_new_revision", "new_revision", "create_new_revision"),
        )
        if getattr(result, "_name", None) == record._name:
            return result
        return self.env[record._name].search(
            [
                ("work_item_id", "=", record.work_item_id.id),
                ("revision", ">", record.revision),
            ],
            order="revision desc",
            limit=1,
        )

    def test_source_dedupe_and_many_to_many_work_items(self):
        first = self._work()
        second_task = self.env["project.task"].create(
            {"name": "Second source-derived task", "project_id": self.odoo_project.id}
        )
        second = self._work(wp_id=False, task=second_task)
        values = self._model_vals(
            "dev.work.source.message",
            provider="evolution",
            instance_reference="test-instance",
            provider_message_id="message-001",
            evolution_message_id="message-001",
            group_jid="120363000000000000@g.us",
            sender_jid="201000000000@s.whatsapp.net",
            chatwoot_account_id=1,
            chatwoot_inbox_id=2,
            chatwoot_conversation_id=3,
            chatwoot_message_id=4,
            message_timestamp="2026-07-18 16:20:00",
            text_snapshot="Sanitized development request",
            text_hash="b" * 64,
            attachment_references="attachment://safe-reference",
            source_url="https://chatwoot.test.invalid/conversations/3",
            dedupe_key="evolution:test-instance:message-001",
            work_item_ids=[(6, 0, [first.id, second.id])],
        )
        source = self.env["dev.work.source.message"].create(values)
        self.assertEqual(set(source.work_item_ids.ids), {first.id, second.id})
        with self.assertRaises(UniqueViolation), self.env.cr.savepoint():
            self.env["dev.work.source.message"].create(values)

    def test_openproject_and_odoo_task_identity_constraints(self):
        self._work()
        other_task = self.env["project.task"].create(
            {"name": "Other task", "project_id": self.odoo_project.id}
        )
        with self.assertRaises(UniqueViolation), self.env.cr.savepoint():
            self._work(task=other_task)

        unlinked = self.env["project.task"].create(
            {"name": "Unlinked unique work", "project_id": self.odoo_project.id}
        )
        self._work(wp_id=False, task=unlinked)
        with self.assertRaises(UniqueViolation), self.env.cr.savepoint():
            self._work(wp_id=False, task=unlinked)

        mismatched = self.env["project.task"].create(
            {
                "name": "Mismatched WP task",
                "project_id": self.odoo_project.id,
                "op_backend_id": self.backend.id,
                "op_work_package_id": 880099,
            }
        )
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self._work(wp_id=880098, task=mismatched)

    def test_lifecycle_direct_write_transition_rules_and_events(self):
        work = self._work()
        phase_field = (
            "current_phase"
            if "current_phase" in work._fields
            else "state"
        )
        self.assertEqual(work[phase_field], "received")
        with self.assertRaises(AccessError):
            work.write({phase_field: "implementing"})

        self._transition(work, "triage")
        self.assertEqual(work[phase_field], "triage")
        events = self.env["dev.work.lifecycle.event"].search(
            [("work_item_id", "=", work.id)]
        )
        self.assertEqual(len(events), 2)
        with self.assertRaises(UserError):
            self._transition(work, "implementing")
        with self.assertRaises(AccessError):
            events.write({"reason": "tampered"})
        with self.assertRaises(AccessError):
            events.unlink()

    def test_accepted_analysis_is_immutable_and_revisioned(self):
        work = self._work()
        self._transition(work, "triage")
        self._transition(work, "registered")
        self._transition(work, "analyzing")
        analysis = self._analysis(work)
        original_hash = analysis.content_hash
        self._accept_analysis(analysis)
        self.assertEqual(analysis.status, "accepted")
        self.assertTrue(analysis.content_hash)
        with self.assertRaises(AccessError):
            analysis.write({"problem_summary": "mutated after acceptance"})

        revision = self._new_revision(analysis)
        self.assertTrue(revision)
        self.assertEqual(revision.revision, analysis.revision + 1)
        self.assertEqual(revision.parent_revision_id, analysis)
        self.assertEqual(revision.status, "draft")
        self.assertEqual(analysis.content_hash, original_hash or analysis.content_hash)
        accepted = (
            work.current_accepted_analysis_id
            if "current_accepted_analysis_id" in work._fields
            else work.accepted_analysis_id
        )
        self.assertEqual(accepted, analysis)

    def test_exact_plan_hash_approval_and_new_revision_clears_effective_approval(self):
        work = self._work()
        self._transition(work, "triage")
        self._transition(work, "registered")
        self._transition(work, "analyzing")
        analysis = self._analysis(work)
        self._accept_analysis(analysis)
        self._transition(work, "planning")
        plan = self._plan(work, with_step=True)
        self._submit_plan(plan)
        self.assertEqual(plan.status, "awaiting_approval")
        self.assertTrue(plan.content_hash)

        approval_model = self.env["dev.work.approval"]
        with self.assertRaises(UserError), self.env.cr.savepoint():
            plan.action_approve_exact("0" * 64)

        self._approve_plan(plan)
        self.assertEqual(plan.status, "approved")
        approvals = approval_model.search(
            [("work_item_id", "=", work.id), ("decision", "=", "approved")]
        )
        self.assertEqual(len(approvals), 1)
        approval_hash_field = (
            "exact_plan_hash"
            if "exact_plan_hash" in approvals._fields
            else "plan_hash"
        )
        self.assertEqual(approvals[approval_hash_field], plan.content_hash)
        with self.assertRaises(AccessError):
            plan.write({"goal": "Mutated approved goal"})
        with self.assertRaises(AccessError):
            approvals.write({"comment": "tampered"})

        revision = self._new_revision(plan)
        self.assertEqual(revision.revision, plan.revision + 1)
        self.assertEqual(revision.parent_revision_id, plan)
        self.assertEqual(revision.status, "draft")
        approved = (
            work.current_approved_plan_id
            if "current_approved_plan_id" in work._fields
            else work.approved_plan_id
        )
        self.assertFalse(approved)

    def test_plan_step_progress(self):
        work = self._work()
        plan = self._plan(work)
        Step = self.env["dev.work.plan.step"]
        steps = Step
        for sequence, status in enumerate(("done", "done", "done", "pending"), 1):
            steps |= Step.create(
                self._model_vals(
                    "dev.work.plan.step",
                    plan_id=plan.id,
                    plan_revision_id=plan.id,
                    step_key="S%s" % sequence,
                    sequence=sequence,
                    title="Step %s" % sequence,
                    description="Bounded test step",
                    status=status,
                )
            )
        plan.invalidate_recordset()
        self.assertEqual(plan.progress, 75.0)
        work.invalidate_recordset()
        self.assertEqual(work.completed_step_count, 3)
        self.assertEqual(work.actionable_step_count, 4)
        if "progress_done" in plan._fields:
            self.assertEqual(plan.progress_done, 3)
        if "progress_total" in plan._fields:
            self.assertEqual(plan.progress_total, 4)

    def test_checkpoint_is_immutable_and_pause_creates_one(self):
        work = self._work()
        self._approved_plan(work)
        session = self._session(work)
        with self._snapshot_patch():
            session.action_start()
            before = self.env["dev.work.checkpoint"].search_count(
                [("work_item_id", "=", work.id)]
            )
            session.action_pause()
        checkpoints = self.env["dev.work.checkpoint"].search(
            [("work_item_id", "=", work.id)], order="id desc"
        )
        self.assertEqual(len(checkpoints), before + 1)
        self.assertEqual(checkpoints[0].session_id, session)
        self.assertEqual(checkpoints[0].trigger, "pause")
        self.assertEqual(checkpoints[0].branch, self.snapshot["branch"])
        self.assertEqual(checkpoints[0].git_head, self.snapshot["head"])
        with self.assertRaises(AccessError):
            checkpoints[0].write({"blockers": "tampered"})
        with self.assertRaises(AccessError):
            checkpoints[0].unlink()

    def test_resume_brief_is_sanitized_bounded_and_reports_drift(self):
        work = self._work()
        self._approved_plan(work)
        source = self.env["dev.work.source.message"].create(
            self._model_vals(
                "dev.work.source.message",
                provider="chatwoot",
                chatwoot_conversation_id=991,
                chatwoot_message_id=992,
                text_snapshot="Safe original request",
                provider_message_id="992",
                work_item_ids=[(4, work.id)],
            )
        )
        self.assertTrue(source)
        session = self._session(work)
        with self._snapshot_patch():
            session.action_start()
            session.action_pause()
        changed = dict(
            self.snapshot,
            branch="feature/changed",
            head="d" * 40,
            dirty="staged=0; unstaged=3; untracked=1; conflicts=0; digest=changed",
        )
        session.client_id = self.ubuntu
        with self._snapshot_patch(changed):
            session.action_resume()

        brief = self._call(
            work,
            (
                "build_resume_brief",
                "_build_resume_brief",
                "get_resume_brief",
                "generate_resume_brief",
            ),
            session,
        )
        if isinstance(brief, dict):
            serialized = json.dumps(brief, sort_keys=True)
        else:
            serialized = str(brief)
        self.assertLessEqual(len(serialized), 16000)
        self.assertIn("changed", serialized.lower())
        self.assertIn("feature/changed", serialized)
        forbidden = (
            "password=",
            "authorization:",
            "bearer ",
            "private key",
            "cursor transcript",
        )
        for token in forbidden:
            self.assertNotIn(token, serialized.lower())
        with self._snapshot_patch():
            session.action_abandon()

    def test_completion_report_lifecycle_and_immutability(self):
        work = self._work()
        plan = self._approved_plan(work)
        step = plan.step_ids[:1]
        step.write({"status": "in_progress"})
        step.write({"status": "done"})
        self._transition(work, "implementing")
        self._transition(work, "testing")
        self.env["dev.work.checkpoint"].sudo().create(
            {
                "work_item_id": work.id,
                "trigger": "client_review",
                "lifecycle_phase": "testing",
                "next_recommended_step": "Review the completion report.",
            }
        )
        report = self.env["dev.completion.report"].create(
            self._model_vals(
                "dev.completion.report",
                work_item_id=work.id,
                plan_id=plan.id,
                revision=1,
                status="draft",
                original_request_summary="Safe original request",
                implemented_summary="Implemented lifecycle controls.",
                completed_steps_summary="S1",
                changed_components_summary="dev_session_hub only",
                repository_reference=self.repository.working_directory,
                branch="feature/dev-work-lifecycle",
                tests_summary="TransactionCase passed.",
                uat_status="not_applicable",
                known_limitations="No production deployment.",
                rollback_notes="No deployment was performed.",
                deployment_status="not_deployed",
                production_status="not_verified",
                follow_up_items="Review before Phase 5.",
            )
        )
        self._call(
            report,
            ("action_ready_review", "action_submit_for_review", "action_request_review"),
        )
        self.assertEqual(report.status, "ready_review")
        self._transition(work, "ready_for_review")
        self._call(report, ("action_approve", "action_mark_approved"))
        self.assertEqual(report.status, "approved")
        self.assertTrue(report.content_hash)
        with self.assertRaises(AccessError):
            report.write({"implemented_summary": "tampered"})
        completed = (
            work.completion_report_id
            if "completion_report_id" in work._fields
            else work.current_completion_report_id
        )
        self.assertEqual(completed, report)

    def test_communication_requires_review_and_queues_chatwoot_without_http(self):
        work = self._work()
        report = self._approved_report(work)
        communication = self.env["dev.work.communication"].create(
            self._model_vals(
                "dev.work.communication",
                work_item_id=work.id,
                completion_report_id=report.id,
                source_message_id=work.source_message_ids[:1].id,
                communication_type="completion",
                chatwoot_account_id=1,
                chatwoot_inbox_id=2,
                chatwoot_conversation_id=775,
                destination_type="group_jid",
                destination_reference="120363000000000000@g.us",
                language_code="en",
                body="The reviewed test-only work is complete.",
            )
        )
        with self.assertRaises(UserError):
            self._call(
                communication,
                ("action_queue", "action_queue_send", "action_send"),
            )

        with patch(
            "requests.sessions.Session.request",
            side_effect=AssertionError("Dev Hub must never perform direct HTTP"),
        ):
            self._call(
                communication,
                ("action_review", "action_submit_review", "action_request_review"),
            )
            self._call(
                communication,
                ("action_approve_send", "action_approve"),
            )
            outbox = self._call(
                communication,
                ("action_queue", "action_queue_send", "action_send"),
            )

        self.assertEqual(outbox.channel, "chatwoot")
        self.assertEqual(outbox.state, "pending")
        self.assertEqual(outbox.idempotency_key, communication.idempotency_key)
        payload_field = (
            "payload_json" if "payload_json" in outbox._fields else "payload"
        )
        payload = outbox[payload_field]
        self.assertLessEqual(len(payload), 16000)
        self.assertIn("chatwoot", payload.lower())
        self.assertNotIn("api_token", payload.lower())
        self.assertFalse(communication.chatwoot_message_id)
        self.assertFalse(communication.evolution_message_id)
        self.assertEqual(communication.state, "queued")

    def test_full_phase_1_to_4_uat_without_automatic_send(self):
        work = self._work()
        self._transition(work, "triage")
        self._transition(work, "registered")
        self._transition(work, "analyzing")
        analysis = self._analysis(work)
        self._accept_analysis(analysis)
        self._transition(work, "planning")

        plan_v1 = self._plan(work)
        for sequence in range(1, 6):
            self.env["dev.work.plan.step"].create(
                {
                    "plan_id": plan_v1.id,
                    "step_key": "P%s" % sequence,
                    "sequence": sequence * 10,
                    "title": "Test-safe implementation step %s" % sequence,
                }
            )
        plan_v2 = self._new_revision(plan_v1)
        self.assertEqual(plan_v2.revision, 2)
        self.assertEqual(plan_v1.status, "superseded")
        self._submit_plan(plan_v2)
        self._approve_plan(plan_v2)

        session = self._session(work)
        with self._snapshot_patch():
            session.action_start()
        for step in plan_v2.step_ids.sorted(lambda item: (item.sequence, item.id))[:3]:
            step.write({"status": "in_progress"})
            step.write({"status": "done", "result_summary": "Verified in Test."})
        with self._snapshot_patch():
            session.action_pause()
        self.assertEqual(work.current_checkpoint_id.trigger, "pause")
        self.assertEqual(work.completed_step_count, 3)

        with self._snapshot_patch():
            session.write({"client_id": self.ubuntu.id})
            action = session.action_resume()
        wizard = self.env[action["res_model"]].browse(action["res_id"])
        self.assertIn("Revision 2", wizard.resume_brief)
        self.assertIn("progress 3 / 5", wizard.resume_brief)
        for step in plan_v2.step_ids.filtered(lambda item: item.status == "pending"):
            step.write({"status": "in_progress"})
            step.write({"status": "done", "result_summary": "Verified in Test."})
        self._transition(work, "testing")

        report = self.env["dev.completion.report"].create(
            {
                "work_item_id": work.id,
                "plan_id": plan_v2.id,
                "original_request_summary": work.source_message_ids[:1].text_snapshot,
                "implemented_summary": "Completed the approved Test-only lifecycle plan.",
                "completed_steps_summary": "P1, P2, P3, P4, P5",
                "changed_components_summary": "dev_session_hub only",
                "repository_reference": self.repository.working_directory,
                "branch": "feature/dev-work-lifecycle",
                "tests_summary": "Five plan steps completed; TransactionCase passed.",
                "uat_status": "passed",
                "known_limitations": "No production deployment and no autonomous worker.",
                "rollback_notes": "No external deployment occurred.",
            }
        )
        report.action_ready_review()
        with self._snapshot_patch():
            work.action_ready_for_review()
        report.action_approve()
        work.action_complete()

        before = self.env["dev.external.outbox"].search_count(
            [("work_item_id", "=", work.id), ("channel", "=", "chatwoot")]
        )
        source = work.source_message_ids[:1]
        communication = self.env["dev.work.communication"].create(
            {
                "work_item_id": work.id,
                "completion_report_id": report.id,
                "source_message_id": source.id,
                "communication_type": "completion",
                "body": "تم الانتهاء من العمل واختباره على بيئة الاختبار.",
                "chatwoot_account_id": source.chatwoot_account_id or 1,
                "chatwoot_inbox_id": source.chatwoot_inbox_id or 2,
                "chatwoot_conversation_id": source.chatwoot_conversation_id or 3,
                "reply_to_chatwoot_message_id": source.chatwoot_message_id,
                "destination_type": "group_jid",
                "destination_reference": source.group_jid
                or "120363000000000000@g.us",
            }
        )
        communication.action_review()
        communication.action_approve()
        self.assertEqual(
            self.env["dev.external.outbox"].search_count(
                [("work_item_id", "=", work.id), ("channel", "=", "chatwoot")]
            ),
            before,
            "Human approval must not auto-send or auto-queue.",
        )
        communication.action_queue()
        work.action_reported()
        with self._snapshot_patch():
            session.action_complete()
        self.assertEqual(work.lifecycle_phase, "reported")

    def test_production_linked_session_is_denied_without_external_calls(self):
        work = self._work()
        self._approved_plan(work)
        production = self.env["dev.environment"].create(
            {
                "name": "Lifecycle blocked production fixture",
                "project_id": self.dev_project.id,
                "environment_type": "production",
                "machine_id": self.machine.id,
                "database_identifier": "redacted-production-fixture",
                "port": 9997,
                "config_reference": "/unresolved/production.conf",
                "service_container_reference": "unresolved",
                "data_sensitivity": "production",
                "production_guard_policy": "Development launch disabled.",
            }
        )
        session = self._session(work, environment=production)
        with patch(
            "requests.sessions.Session.request",
            side_effect=AssertionError("Production denial must not call HTTP"),
        ), self.assertRaises(UserError):
            session.action_start()
        self.assertEqual(session.state, "draft")
        self.assertFalse(
            self.env["dev.work.checkpoint"].search(
                [("session_id", "=", session.id)]
            )
        )

    def _outbox_user(self):
        return new_test_user(
            self.env,
            login="dev-hub-outbox-%s" % uuid.uuid4().hex,
            groups="dev_session_hub.group_dev_hub_integration",
        )

    def _generation_user(self):
        return new_test_user(
            self.env,
            login="dev-hub-generation-%s" % uuid.uuid4().hex,
            groups="dev_session_hub.group_dev_hub_generation",
        )

    def _generation_ready_work(self):
        work = self._work()
        self._transition(work, "triage")
        self._transition(work, "registered")
        self.env["dev.work.checkpoint"].sudo().create(
            {
                "work_item_id": work.id,
                "trigger": "milestone",
                "lifecycle_phase": "registered",
                "repository_id": self.repository.id,
                "git_head": "b" * 40,
                "next_recommended_step": "Generate analysis.",
            }
        )
        work._refresh_context_revision()
        return work

    def test_outbox_service_leasing_callbacks_and_queue_idempotency(self):
        work = self._work()
        outbox = work._queue_outbox(
            "openproject",
            "milestone",
            {
                "schema": "dev-hub.op-milestone.v1",
                "backend_id": self.backend.id,
                "work_package_id": work.op_work_package_id,
                "milestone": "material_blocker",
                "summary": "Test-only blocker.",
                "status_hint": "on_hold",
            },
            "test:%s" % uuid.uuid4().hex,
        )
        duplicate = work._queue_outbox(
            outbox.channel,
            outbox.operation,
            json.loads(outbox.payload_json),
            outbox.idempotency_key,
        )
        self.assertEqual(duplicate, outbox)

        integration = self._outbox_user()
        service = self.env["dev.external.outbox"].with_user(integration)
        lease = service.service_lease(limit=1, consumer_ref="test-consumer")
        self.assertEqual(lease[0]["id"], outbox.id)
        self.assertEqual(outbox.state, "leased")
        service.service_mark_processing(
            outbox.id, outbox.correlation_id, lease[0]["lease_token"]
        )
        result = service.service_ack_success(
            outbox.id,
            outbox.correlation_id,
            lease[0]["lease_token"],
            {"external_reference": "test-activity-1"},
        )
        self.assertEqual(result["state"], "done")
        self.assertEqual(outbox.state, "done")
        self.assertEqual(
            service.service_ack_success(outbox.id, outbox.correlation_id)["state"],
            "done",
        )

        ordinary = new_test_user(
            self.env,
            login="dev-hub-ordinary-%s" % uuid.uuid4().hex,
            groups="dev_session_hub.group_dev_hub_user",
        )
        with self.assertRaises(AccessError):
            self.env["dev.external.outbox"].with_user(ordinary).service_lease()

    def test_outbox_retry_dead_letter_and_service_scope(self):
        work = self._work()
        outbox = work._prepare_op_milestone(
            "material_blocker", "Safe test-only retry.", "on_hold"
        )
        outbox_user = self._outbox_user()
        generation_user = self._generation_user()
        service = self.env["dev.external.outbox"].with_user(outbox_user)
        with self.assertRaises(AccessError):
            self.env["dev.external.outbox"].with_user(generation_user).service_lease()
        lease = service.service_lease(limit=1, consumer_ref="retry-test")[0]
        retry = service.service_ack_failure(
            outbox.id,
            outbox.correlation_id,
            "temporary_transport",
            "Temporary transport failure before a confirmed delivery.",
            lease_token=lease["lease_token"],
            transient=True,
            retry_after_seconds=30,
        )
        self.assertEqual(retry["state"], "retry")
        outbox.with_context(dev_outbox_action=True).write(
            {"next_attempt_at": fields.Datetime.now()}
        )
        lease = service.service_lease(limit=1, consumer_ref="dead-letter-test")[0]
        service.service_mark_processing(
            outbox.id, outbox.correlation_id, lease["lease_token"]
        )
        dead = service.service_ack_failure(
            outbox.id,
            outbox.correlation_id,
            "delivery_uncertain",
            "External outcome is uncertain; automatic retry is unsafe.",
            lease_token=lease["lease_token"],
            transient=True,
            delivery_uncertain=True,
        )
        self.assertEqual(dead["state"], "uncertain_delivery")

    def test_outbox_stale_lease_is_fenced_and_uncertain_delivery_reconciles(self):
        work = self._work()
        outbox = work._prepare_op_milestone(
            "material_blocker", "Safe reconciliation test.", "on_hold"
        )
        service = self.env["dev.external.outbox"].with_user(self._outbox_user())
        first = service.service_lease(limit=1, consumer_ref="first-worker")[0]
        service.service_mark_processing(
            outbox.id, outbox.correlation_id, first["lease_token"]
        )
        service.service_ack_failure(
            outbox.id,
            outbox.correlation_id,
            "delivery_uncertain",
            "Provider acceptance requires reconciliation.",
            lease_token=first["lease_token"],
            transient=False,
            delivery_uncertain=True,
            retry_after_seconds=30,
        )
        self.assertEqual(outbox.state, "uncertain_delivery")
        outbox.with_context(dev_outbox_action=True).write(
            {"next_attempt_at": fields.Datetime.now()}
        )
        second = service.service_lease(limit=1, consumer_ref="reconciler")[0]
        self.assertTrue(second["reconcile_only"])
        self.assertNotEqual(first["lease_token"], second["lease_token"])
        self.assertGreater(second["lease_version"], first["lease_version"])
        with self.assertRaises(AccessError):
            service.service_mark_processing(
                outbox.id, outbox.correlation_id, first["lease_token"]
            )
        service.service_mark_processing(
            outbox.id, outbox.correlation_id, second["lease_token"]
        )
        result = service.service_ack_success(
            outbox.id,
            outbox.correlation_id,
            second["lease_token"],
            {"external_reference": "reconciled-activity-1"},
        )
        self.assertEqual(result["state"], "done")
        self.assertFalse(outbox.reconciliation_required)

    def test_outbox_rejects_unsupported_or_malformed_intents(self):
        work = self._work()
        with self.assertRaises(ValidationError):
            self.env["dev.external.outbox"].with_context(
                dev_internal_outbox=True
            ).create(
                {
                    "work_item_id": work.id,
                    "channel": "chatwoot",
                    "operation": "public_message",
                    "payload_json": {
                        "schema": "dev-hub.chatwoot-public-message.v0",
                        "account_id": 1,
                    },
                    "idempotency_key": "invalid:%s" % uuid.uuid4().hex,
                }
            )
        with self.assertRaises(ValidationError):
            work._prepare_op_milestone(
                "every_transition", "Unsupported noisy milestone.", "in_progress"
            )

    def test_generation_callbacks_create_drafts_without_plan_approval(self):
        work = self._generation_ready_work()
        analysis_request = work.action_request_analysis_generation()
        integration = self._generation_user()
        service = self.env["dev.work.generation"].with_user(integration)
        with self.assertRaises(AccessError):
            self.env["dev.work.item"].with_user(integration).import_analysis_draft(
                {
                    "work_item_uuid": work.uuid,
                    "problem_summary": "Bypass attempt.",
                    "original_request_summary": "Must use service_complete.",
                }
            )
        lease = service.service_lease(limit=1, consumer_ref="generation-test")[0]
        self.assertEqual(lease["id"], analysis_request.id)
        service.service_mark_processing(
            analysis_request.id,
            analysis_request.correlation_id,
            lease["lease_token"],
            "dify:analysis",
            "analysis-run-%s" % uuid.uuid4().hex,
        )
        outcome = service.service_complete(
            analysis_request.id,
            analysis_request.correlation_id,
            lease["lease_token"],
            {
                "problem_summary": "A bounded test problem.",
                "original_request_summary": "A bounded test request.",
                "technical_findings": "No production evidence.",
                "observed_head": "b" * 40,
            },
        )
        analysis = self.env[outcome["artifact_model"]].browse(
            outcome["artifact_record_id"]
        )
        self.assertEqual(analysis.status, "generated")
        self.assertEqual(work.current_phase, "analyzing")

        analysis.action_accept()
        plan_request = work.action_request_plan_generation()
        lease = service.service_lease(limit=1, consumer_ref="generation-test")[0]
        self.assertEqual(lease["id"], plan_request.id)
        service.service_mark_processing(
            plan_request.id,
            plan_request.correlation_id,
            lease["lease_token"],
            "dify:plan",
            "plan-run-%s" % uuid.uuid4().hex,
        )
        outcome = service.service_complete(
            plan_request.id,
            plan_request.correlation_id,
            lease["lease_token"],
            {
                "goal": "Implement only the approved scope.",
                "scope": "Test scope.",
                "out_of_scope": "Production deployment.",
                "proposed_changes": "Change the test fixture.",
                "affected_components": "dev_session_hub tests.",
                "migration_impact": "None.",
                "security_impact": "Guarded callback only.",
                "test_plan": "Run TransactionCase.",
                "rollback_plan": "Revert the reviewed change.",
                "dependencies": "Odoo test framework.",
                "risks": "Incorrect callback state.",
                "acceptance_criteria": "The test passes.",
                "steps": [
                    {
                        "step_key": "S1",
                        "sequence": 10,
                        "title": "Implement fixture",
                        "description": "Apply the bounded change.",
                        "dependency_keys": "",
                        "acceptance_evidence": "TransactionCase output.",
                    }
                ],
            },
        )
        plan = self.env[outcome["artifact_model"]].browse(outcome["artifact_record_id"])
        self.assertEqual(plan.status, "awaiting_approval")
        self.assertEqual(work.current_phase, "awaiting_plan_approval")
        self.assertFalse(plan.approval_ids)
        with self.assertRaises(AccessError):
            self.env["dev.work.generation"].with_user(
                self._outbox_user()
            ).service_lease()

    def test_generation_rejects_stale_context(self):
        work = self._generation_ready_work()
        request = work.action_request_analysis_generation()
        integration = self._generation_user()
        service = self.env["dev.work.generation"].with_user(integration)
        lease = service.service_lease(limit=1, consumer_ref="stale-test")[0]
        with self.assertRaises(AccessError):
            service.service_mark_processing(
                request.id,
                request.correlation_id,
                "stale-generation-token",
                "dify:analysis",
                "stale-worker-run",
            )
        service.service_mark_processing(
            request.id,
            request.correlation_id,
            lease["lease_token"],
            "dify:analysis",
            "stale-run-%s" % uuid.uuid4().hex,
        )
        work.action_analyze()
        outcome = service.service_complete(
            request.id,
            request.correlation_id,
            lease["lease_token"],
            {
                "problem_summary": "Stale output.",
                "original_request_summary": "Stale request.",
            },
        )
        self.assertEqual(outcome["error_code"], "stale_generation_context")
        self.assertEqual(request.state, "dead_letter")
        self.assertFalse(request.artifact_record_id)

    def test_generation_rejects_invalid_schema_and_production(self):
        work = self._generation_ready_work()
        request = work.action_request_analysis_generation()
        service = self.env["dev.work.generation"].with_user(self._generation_user())
        lease = service.service_lease(limit=1, consumer_ref="invalid-output-test")[0]
        service.service_mark_processing(
            request.id,
            request.correlation_id,
            lease["lease_token"],
            "dify:analysis",
            "invalid-run-%s" % uuid.uuid4().hex,
        )
        outcome = service.service_complete(
            request.id,
            request.correlation_id,
            lease["lease_token"],
            {"problem_summary": "Missing required original request summary."},
        )
        self.assertEqual(outcome["error_code"], "invalid_generation_output")
        self.assertEqual(request.state, "dead_letter")
        self.assertFalse(request.artifact_record_id)

        production = self.env["dev.environment"].create(
            {
                "name": "Generation blocked production fixture",
                "project_id": self.dev_project.id,
                "environment_type": "production",
                "machine_id": self.machine.id,
                "database_identifier": "redacted-production-generation",
                "odoo_version": "19.0",
                "port": 65531,
                "config_reference": "/unresolved/production.conf",
                "service_container_reference": "unresolved-production-service",
                "url": "https://production.invalid",
                "data_sensitivity": "production",
                "production_guard_policy": "Generation disabled.",
            }
        )
        blocked = work
        blocked.write({"preferred_environment_id": production.id})
        with self.assertRaises(UserError):
            blocked.action_request_analysis_generation()

    def test_communication_context_cannot_forge_review_or_queue(self):
        work = self._work()
        report = self._approved_report(work)
        source = work.source_message_ids[:1]
        communication = self.env["dev.work.communication"].create(
            {
                "work_item_id": work.id,
                "completion_report_id": report.id,
                "source_message_id": source.id,
                "communication_type": "completion",
                "body": "Reviewed exact destination test.",
                "chatwoot_account_id": source.chatwoot_account_id,
                "chatwoot_inbox_id": source.chatwoot_inbox_id,
                "chatwoot_conversation_id": source.chatwoot_conversation_id,
                "destination_type": "group_jid",
                "destination_reference": source.group_jid,
            }
        )
        communication.action_review()
        with self.assertRaises(AccessError):
            communication.with_context(dev_communication_action=True).write(
                {"state": "queued"}
            )
        with self.assertRaises(AccessError):
            communication.write({"body": "Changed after review"})
        communication.action_approve()
        first = communication.action_queue()
        second = communication.action_queue()
        self.assertEqual(first, second)
        self.assertEqual(communication.review_hash, communication.approved_hash)

    def test_approver_cannot_forge_immutable_approval_record(self):
        work = self._work()
        self._transition(work, "triage")
        self._transition(work, "registered")
        self._transition(work, "analyzing")
        analysis = self._analysis(work)
        analysis.action_accept()
        self._transition(work, "planning")
        plan = self._plan(work, with_step=True)
        plan.action_submit_for_approval()
        approver = new_test_user(
            self.env,
            login="dev-hub-approver-%s" % uuid.uuid4().hex,
            groups=(
                "dev_session_hub.group_dev_hub_user,"
                "dev_session_hub.group_dev_hub_approver"
            ),
        )
        self.dev_project.write({"member_ids": [(4, approver.id)]})
        self.assertIn(approver, self.dev_project.member_ids)
        with self.assertRaises(AccessError):
            self.env["dev.work.approval"].with_user(approver).with_context(
                dev_internal_approval=True
            ).create(
                {
                    "work_item_id": work.id,
                    "plan_id": plan.id,
                    "plan_revision": plan.revision,
                    "plan_hash": plan.content_hash,
                    "decision": "approved",
                    "approver_id": approver.id,
                    "decided_at": "2026-07-18 20:00:00",
                }
            )
        approval = plan.with_user(approver).action_approve_exact(plan.content_hash)
        self.assertEqual(approval.approver_id, approver)

    def _execution_repository(self):
        self.repository.write(
            {
                "execution_classification": "safe_for_isolated_worktree",
                "agent_execution_allowed": True,
                "worker_identity": "devworker",
                "worker_git_common_dir": "/srv/devhub/repos/petspot.git",
                "worker_worktree_root": "/srv/devhub/worktrees",
                "production_runtime_coupled": False,
                "default_branch": "main",
                "head_cache": "a" * 40,
            }
        )
        return self.repository

    def _workspace_proposal(self, work):
        self._execution_repository()
        snapshot = {
            "branch": "feature/manual-work",
            "head": "b" * 40,
            "dirty": "staged=0; unstaged=1; untracked=0; conflicts=0",
            "digest": "c" * 64,
        }
        model = self.env["dev.execution.workspace"]
        with patch.object(type(model), "_main_snapshot", autospec=True, return_value=snapshot):
            return model.create_proposal(work)

    def test_execution_workspace_requires_exact_current_approval(self):
        work = self._work()
        self._execution_repository()
        with self.assertRaises(UserError):
            self.env["dev.execution.workspace"].create_proposal(work)

        plan = self._approved_plan(work)
        workspace = self._workspace_proposal(work)
        self.assertEqual(workspace.plan_id, plan)
        self.assertEqual(workspace.approved_plan_hash, plan.content_hash)
        self.assertEqual(workspace.state, "pending_confirmation")

        plan.action_new_revision()
        with self.assertRaises(UserError):
            workspace._assert_plan_unchanged()

    def test_execution_workspace_uses_bounded_branch_and_generated_path(self):
        work = self._work(name="../ Shopify / Order: Sync " + "x" * 200)
        self._approved_plan(work)
        workspace = self._workspace_proposal(work)
        self.assertRegex(workspace.execution_branch, r"^devhub/DW-\d+-[a-z0-9-]+$")
        self.assertLessEqual(len(workspace.execution_branch), 90)
        self.assertEqual(
            workspace.worktree_path,
            "/srv/devhub/worktrees/petspot/DW-%s" % work.id,
        )
        self.assertNotIn("..", workspace.worktree_path)
        self.assertEqual(_slug("A / B"), "a-b")
        with self.assertRaises(ValidationError):
            _canonical_child("/srv/devhub/worktrees", "..", "escape")

    def test_execution_workspace_binds_reviewed_policy_hash(self):
        work = self._work()
        self._approved_plan(work)
        workspace = self._workspace_proposal(work)
        self.assertTrue(workspace.policy_hash)
        self.assertTrue(workspace.execution_contract_hash)
        workspace.policy_id.write(
            {"allowed_operations": "Changed after workspace confirmation."}
        )
        with self.assertRaises(UserError):
            workspace._assert_plan_unchanged()

    def test_execution_workspace_rejects_contract_hash_mismatch(self):
        work = self._work()
        self._approved_plan(work)
        workspace = self._workspace_proposal(work)
        self.env.cr.execute(
            "UPDATE dev_execution_workspace SET execution_contract_hash = %s "
            "WHERE id = %s",
            ["0" * 64, workspace.id],
        )
        workspace.invalidate_recordset(["execution_contract_hash"])
        with self.assertRaises(UserError):
            workspace._assert_plan_unchanged()

    def test_execution_repository_rejects_main_and_sensitive_roots(self):
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self.repository.write(
                {
                    "worker_git_common_dir": (
                        self.repository.working_directory + "/.git"
                    ),
                    "worker_worktree_root": "/srv/devhub/worktrees",
                }
            )
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self.repository.write(
                {
                    "worker_git_common_dir": "/srv/devhub/repos/petspot.git",
                    "worker_worktree_root": "/home/sabry/dev-worktrees",
                }
            )

    def test_execution_workspace_denies_production_environment_and_target(self):
        work = self._work()
        self._approved_plan(work)
        self._execution_repository()
        production = self.env["dev.environment"].create(
            {
                "name": "Execution workspace blocked production fixture",
                "project_id": self.dev_project.id,
                "environment_type": "production",
                "machine_id": self.machine.id,
                "database_identifier": "redacted-production-execution-fixture",
                "port": 65529,
                "config_reference": "/unresolved/production-execution.conf",
                "service_container_reference": "unresolved",
                "data_sensitivity": "production",
                "production_guard_policy": "Execution workspace preparation disabled.",
            }
        )
        work.write({"preferred_environment_id": production.id})
        with self.assertRaises(UserError):
            self.env["dev.execution.workspace"].create_proposal(work)

        work.write({"preferred_environment_id": self.environment.id})
        self.machine.write({"production": True})
        with self.assertRaises(UserError):
            self.env["dev.execution.workspace"].create_proposal(work)

    def test_execution_workspace_branch_and_path_collisions_fail_closed(self):
        work = self._work()
        self._approved_plan(work)
        self._execution_repository()
        model = self.env["dev.execution.workspace"]
        with patch("odoo.addons.dev_session_hub.models.dev_execution.os.path.lexists", return_value=True):
            with self.assertRaises(UserError):
                model.create_proposal(work)

        workspace = self._workspace_proposal(work)

        def fake_git(_workspace, args, **_kwargs):
            if args == ["rev-parse", "--is-bare-repository"]:
                return SimpleNamespace(stdout=b"true\n", returncode=0)
            if args == ["rev-parse", "%s^{commit}" % workspace.base_branch]:
                return SimpleNamespace(
                    stdout=(workspace.base_head + "\n").encode(), returncode=0
                )
            if args[0] == "show-ref":
                return SimpleNamespace(stdout=b"", returncode=0)
            if args == ["rev-parse", workspace.execution_branch]:
                return SimpleNamespace(
                    stdout=(workspace.base_head + "\n").encode(), returncode=0
                )
            raise AssertionError("Unexpected Git call: %r" % (args,))

        with patch.object(
            type(workspace),
            "_assert_worker_identity",
            autospec=True,
            return_value=True,
        ), patch.object(
            type(workspace),
            "_main_snapshot",
            autospec=True,
            return_value={
                "branch": workspace.main_branch_before,
                "head": workspace.main_head_before,
                "dirty": workspace.main_dirty_summary_before,
                "digest": workspace.main_dirty_digest_before,
            },
        ), patch.object(
            type(workspace),
            "_git",
            autospec=True,
            side_effect=fake_git,
        ):
            with self.assertRaises(UserError):
                workspace.action_confirm_prepare()

    def test_execution_workspace_concurrency_and_stale_lease_are_fenced(self):
        work = self._work()
        self._approved_plan(work)
        workspace = self._workspace_proposal(work)
        workspace._internal_write({"state": "ready"})
        first = workspace.acquire_lease("worker-a", self.windows, seconds=60)
        with self.assertRaises(AccessError):
            workspace.acquire_lease("worker-b", self.ubuntu, seconds=60)
        self.assertTrue(
            workspace.assert_lease(first["lease_token"], first["lease_version"])
        )
        with self.assertRaises(AccessError):
            workspace.assert_lease(first["lease_token"], first["lease_version"] - 1)

    def test_phase5_worker_is_lease_fenced_and_stops_for_review(self):
        work = self._work()
        plan = self._approved_plan(work)
        workspace = self._workspace_proposal(work)
        workspace._internal_write({"state": "ready"})
        step = plan.step_ids[:1]
        with patch.object(
            type(workspace),
            "_assert_worker_identity",
            autospec=True,
            return_value=True,
        ), patch.object(
            type(workspace), "_validate_physical", autospec=True, return_value=True
        ):
            first = workspace.start_worker("devworker", self.ubuntu, seconds=60)
            with self.assertRaises(AccessError):
                workspace.worker_update_step(
                    "stale-token", first["lease_version"], step, "in_progress"
                )
            workspace.worker_update_step(
                first["lease_token"], first["lease_version"], step, "in_progress"
            )
            workspace.worker_update_step(
                first["lease_token"],
                first["lease_version"],
                step,
                "done",
                "Bounded test-only change completed.",
            )
            checkpoint = workspace.worker_pause(
                first["lease_token"],
                first["lease_version"],
                "Targeted test passed before pause.",
                {"run": 1, "passed": 1, "command": "approved-targeted-test"},
            )
            self.assertEqual(workspace.state, "paused")
            self.assertEqual(workspace.last_checkpoint_id, checkpoint)
            with self.assertRaises(AccessError):
                workspace.assert_lease(
                    first["lease_token"], first["lease_version"]
                )

            second = workspace.worker_resume(
                "devworker",
                self.ubuntu,
                workspace.dirty_digest,
                seconds=60,
            )
            self.assertGreater(second["lease_version"], first["lease_version"])
            with self.assertRaises(AccessError):
                workspace.acquire_lease("second-writer", self.windows, seconds=60)

            workspace.worker_mark_review_required(
                second["lease_token"],
                second["lease_version"],
                "One allowlisted test file changed; targeted and regression tests passed.",
                {"run": 2, "passed": 2, "failed": 0, "errors": 0},
            )
            self.assertEqual(workspace.state, "review_required")
            self.assertEqual(work.current_phase, "ready_for_review")
            self.assertEqual(workspace.worker_status, "stopped_at_review_required")
            self.assertTrue(workspace.review_handoff)
            with self.assertRaises(AccessError):
                workspace.assert_lease(
                    second["lease_token"], second["lease_version"]
                )

    def test_git_commit_requires_human_approval_and_review_state(self):
        _work, _plan, workspace, _checkpoint = self._commit_review_workspace()
        with self.assertRaises(AccessError):
            workspace.action_open_commit_execution()
        workspace._internal_write({"state": "ready"})
        with self.assertRaises(UserError):
            workspace.with_user(self.commit_manager).create_commit_approval(
                "[DW-1] Not reviewed"
            )

    def test_git_commit_approval_is_immutable_and_exactly_bound(self):
        work, plan, workspace, _checkpoint = self._commit_review_workspace()
        approval = self._create_commit_approval(workspace)
        self.assertEqual(workspace.state, "commit_approved")
        self.assertEqual(approval.work_item_id, work)
        self.assertEqual(approval.plan_id, plan)
        self.assertEqual(approval.current_head, workspace.base_head)
        self.assertEqual(approval.dirty_digest, "d" * 64)
        self.assertEqual(approval.changed_files_digest, "c" * 64)
        self.assertEqual(approval.plan_hash, workspace.approved_plan_hash)
        self.assertEqual(approval.policy_hash, workspace.policy_hash)
        self.assertEqual(
            approval.execution_contract_hash, workspace.execution_contract_hash
        )
        approval.assert_integrity()
        with self.assertRaises(AccessError):
            approval.write({"commit_message": "Changed after approval"})
        with self.assertRaises(AccessError):
            approval.unlink()

    def test_commit_approval_denies_dirty_head_and_changed_file_drift(self):
        for label, key, value in (
            ("dirty", "dirty_digest", "e" * 64),
            ("head", "current_head", "f" * 40),
            ("changed files", "changed_files_digest", "a" * 64),
        ):
            with self.subTest(label=label):
                _work, _plan, workspace, _checkpoint = (
                    self._commit_review_workspace()
                )
                approval = self._create_commit_approval(workspace)
                drifted = self._commit_binding(workspace)
                drifted[key] = value
                with patch.object(
                    type(workspace),
                    "_assert_worker_identity",
                    autospec=True,
                    return_value=True,
                ), patch.object(
                    type(workspace),
                    "_assert_plan_unchanged",
                    autospec=True,
                    return_value=True,
                ), patch.object(
                    type(workspace),
                    "_review_change_binding",
                    autospec=True,
                    return_value=drifted,
                ):
                    with self.assertRaises(AccessError):
                        workspace._assert_commit_approval_current(approval)

    def test_commit_approval_denies_plan_policy_and_contract_drift(self):
        for field_name in (
            "approved_plan_hash",
            "policy_hash",
            "execution_contract_hash",
        ):
            with self.subTest(field_name=field_name):
                _work, _plan, workspace, _checkpoint = (
                    self._commit_review_workspace()
                )
                approval = self._create_commit_approval(workspace)
                workspace._internal_write({field_name: "f" * 64})
                with patch.object(
                    type(workspace),
                    "_assert_worker_identity",
                    autospec=True,
                    return_value=True,
                ), patch.object(
                    type(workspace),
                    "_assert_plan_unchanged",
                    autospec=True,
                    return_value=True,
                ), patch.object(
                    type(workspace),
                    "_review_change_binding",
                    autospec=True,
                    return_value=self._commit_binding(workspace),
                ):
                    with self.assertRaises(AccessError):
                        workspace._assert_commit_approval_current(approval)

    def test_commit_approval_denies_active_or_concurrent_worker_lease(self):
        _work, _plan, workspace, _checkpoint = self._commit_review_workspace()
        workspace._internal_write(
            {
                "lease_token": "active-token",
                "lease_owner": "second-writer",
                "lease_client_id": self.ubuntu.id,
                "lease_expires_at": fields.Datetime.add(
                    fields.Datetime.now(), minutes=5
                ),
            }
        )
        with self.assertRaises(AccessError):
            workspace.with_user(self.commit_manager).create_commit_approval(
                "[DW-1] Lease must block"
            )

    def test_commit_approval_denies_production_environment(self):
        _work, _plan, workspace, _checkpoint = self._commit_review_workspace()
        production = self.environment.copy(
            {
                "name": "Commit Production Denial",
                "environment_type": "production",
            }
        )
        workspace._internal_write({"environment_id": production.id})
        with patch.object(
            type(workspace),
            "_assert_worker_identity",
            autospec=True,
            return_value=True,
        ), patch.object(
            type(workspace),
            "_assert_plan_unchanged",
            autospec=True,
            return_value=True,
        ):
            with self.assertRaises(UserError):
                workspace.with_user(self.commit_manager).create_commit_approval(
                    "[DW-1] Production denied"
                )

    def test_unexpected_file_after_approval_requires_fresh_review(self):
        _work, _plan, workspace, _checkpoint = self._commit_review_workspace()
        approval = self._create_commit_approval(workspace)
        unexpected = self._commit_binding(workspace)
        unexpected.update(
            {
                "changed_files": [
                    "tests/approved.py",
                    "deploy/unexpected.conf",
                ],
                "changed_files_summary": (
                    "tests/approved.py\ndeploy/unexpected.conf"
                ),
                "changed_files_digest": "b" * 64,
            }
        )
        with patch.object(
            type(workspace),
            "_assert_worker_identity",
            autospec=True,
            return_value=True,
        ), patch.object(
            type(workspace),
            "_assert_plan_unchanged",
            autospec=True,
            return_value=True,
        ), patch.object(
            type(workspace),
            "_review_change_binding",
            autospec=True,
            return_value=unexpected,
        ):
            with self.assertRaises(AccessError):
                workspace._assert_commit_approval_current(approval)

    def test_human_rejection_invalidates_approval_and_returns_implementation(self):
        work, _plan, workspace, _checkpoint = self._commit_review_workspace()
        approval = self._create_commit_approval(workspace)
        workspace.with_user(self.commit_manager).action_reject_commit_changes()
        self.assertEqual(workspace.state, "ready")
        self.assertFalse(workspace.commit_approval_id)
        self.assertEqual(work.current_phase, "implementing")
        self.assertEqual(approval.approval_state, "rejected")
        self.assertEqual(workspace.last_checkpoint_id.trigger, "client_review")

    def test_bounded_commit_stages_exact_files_and_records_one_local_commit(self):
        _work, _plan, workspace, _checkpoint = self._commit_review_workspace()
        approval = self._create_commit_approval(workspace)
        parent = workspace.base_head
        commit_sha = "b" * 40
        binding = self._commit_binding(workspace)
        results = [
            SimpleNamespace(returncode=0, stdout=b"", stderr=b""),  # add
            SimpleNamespace(
                returncode=0, stdout=b"tests/approved.py\0", stderr=b""
            ),
            SimpleNamespace(returncode=0, stdout=b"", stderr=b""),  # unstaged
            SimpleNamespace(
                returncode=0, stdout=b"A  tests/approved.py\0", stderr=b""
            ),
            SimpleNamespace(returncode=0, stdout=b"", stderr=b""),  # commit
            SimpleNamespace(
                returncode=0, stdout=commit_sha.encode() + b"\n", stderr=b""
            ),
            SimpleNamespace(
                returncode=0, stdout=parent.encode() + b"\n", stderr=b""
            ),
            SimpleNamespace(returncode=0, stdout=b"1\n", stderr=b""),
            SimpleNamespace(
                returncode=0, stdout=b"tests/approved.py\0", stderr=b""
            ),
            SimpleNamespace(returncode=0, stdout=b"", stderr=b""),  # clean
        ]
        with patch.object(
            type(workspace),
            "_assert_commit_approval_current",
            autospec=True,
            return_value=binding,
        ), patch.object(
            type(workspace),
            "_run_bounded_commit_git",
            autospec=True,
            side_effect=results,
        ) as git_call, patch.object(
            type(workspace),
            "_staged_content_digest",
            autospec=True,
            return_value=approval.changed_files_digest,
        ), patch.object(
            type(workspace),
            "_main_snapshot",
            autospec=True,
            return_value={
                "branch": approval.main_branch,
                "head": approval.main_head,
                "dirty": "clean",
                "digest": approval.main_dirty_digest,
            },
        ), patch.object(
            type(workspace), "_validate_physical", autospec=True, return_value=True
        ):
            record = workspace.execute_approved_commit(approval)
        commands = [call.args[1] for call in git_call.call_args_list]
        self.assertIn(["add", "--", "tests/approved.py"], commands)
        self.assertEqual(sum(command[-3:] == ["commit", "-F", "-"] for command in commands), 1)
        self.assertFalse(any("push" in command for command in commands))
        self.assertFalse(any("merge" in command for command in commands))
        self.assertFalse(any("deploy" in command for command in commands))
        self.assertEqual(workspace.state, "committed_reviewed")
        self.assertEqual(workspace.committed_sha, commit_sha)
        self.assertEqual(record.parent_sha, parent)
        self.assertEqual(record.committed_files_summary, "tests/approved.py")
        self.assertEqual(approval.approval_state, "consumed")

    def test_git_push_requires_human_approval_and_committed_review_state(self):
        _work, _plan, workspace, remote, _record, _checkpoint = (
            self._push_review_workspace()
        )
        with self.assertRaises(AccessError):
            workspace.action_open_push_execution()
        workspace._internal_write({"state": "review_required"})
        with self.assertRaises(AccessError):
            self._create_push_approval(workspace, remote)

    def test_push_approval_is_immutable_and_exactly_bound(self):
        work, _plan, workspace, remote, _record, _checkpoint = (
            self._push_review_workspace()
        )
        approval = self._create_push_approval(workspace, remote)
        self.assertEqual(workspace.state, "push_approved")
        self.assertEqual(approval.work_item_id, work)
        self.assertEqual(approval.local_branch, workspace.execution_branch)
        self.assertEqual(approval.local_head, workspace.committed_sha)
        self.assertEqual(approval.commit_sha, workspace.committed_sha)
        self.assertEqual(approval.remote_id, remote)
        self.assertEqual(approval.remote_branch, workspace.execution_branch)
        self.assertEqual(approval.push_mode, "normal")
        approval.assert_integrity()
        with self.assertRaises(AccessError):
            approval.write({"remote_branch": "devhub/changed"})
        with self.assertRaises(AccessError):
            approval.unlink()

    def test_push_approval_denies_bound_state_drift(self):
        for label, field_name, value in (
            ("head", "current_head", "c" * 40),
            ("commit", "committed_sha", "d" * 40),
            ("branch", "execution_branch", "devhub/DW-999-drift"),
            ("policy", "policy_hash", "e" * 64),
            ("contract", "execution_contract_hash", "f" * 64),
        ):
            with self.subTest(label=label):
                _work, _plan, workspace, remote, _record, _checkpoint = (
                    self._push_review_workspace()
                )
                approval = self._create_push_approval(workspace, remote)
                workspace._internal_write({field_name: value})
                with patch.object(
                    type(workspace),
                    "_assert_push_base",
                    autospec=True,
                    return_value=True,
                ):
                    with self.assertRaises(AccessError):
                        workspace._assert_push_approval_current(approval)

    def test_push_remote_and_target_policy_denies_protected_or_arbitrary_targets(self):
        _work, _plan, workspace, remote, _record, _checkpoint = (
            self._push_review_workspace()
        )
        for branch in ("main", "master", "production", "release/19.0"):
            with self.subTest(branch=branch), self.assertRaises(AccessError):
                remote.assert_push_allowed(branch)
        with self.assertRaises(AccessError):
            remote.assert_push_allowed("feature/arbitrary")
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self.env["dev.git.remote"].create(
                {
                    "name": "bad-url",
                    "repository_id": self.repository.id,
                    "remote_url": "https://user:secret@example.invalid/repo.git",
                    "protocol": "https",
                    "approved": True,
                }
            )
        remote.write({"approved": False})
        with self.assertRaises(AccessError):
            remote.assert_push_allowed(workspace.execution_branch)

    def test_push_remote_url_structured_validation(self):
        self.repository.write({"approved_push_root": "/srv/devhub-uat/remotes"})
        allowed = (
            ("https", "https://github.com/org/repo.git", "git"),
            ("ssh", "ssh://git@github.com/org/repo.git", "git"),
            ("ssh", "git@github.com:org/repo.git", "git"),
        )
        for index, (protocol, url, ssh_user) in enumerate(allowed):
            with self.subTest(url=url):
                remote = self.env["dev.git.remote"].create(
                    {
                        "name": "allowed-%s-%s" % (index, uuid.uuid4().hex[:6]),
                        "repository_id": self.repository.id,
                        "remote_url": url,
                        "protocol": protocol,
                        "approved": True,
                        "allowed_ssh_user": ssh_user,
                        "credential_profile_reference": (
                            "/srv/devhub/credentials/github/test_ssh_config"
                        ),
                    }
                )
                self.assertEqual(remote.remote_url, url)

        denied = (
            ("https", "https://user@github.com/org/repo.git", "git"),
            ("https", "https://:password@github.com/org/repo.git", "git"),
            ("https", "https://user:password@example.com/repo.git", "git"),
            ("https", "https://example.com/repo.git?access_token=SECRET", "git"),
            ("https", "https://example.com/repo.git?token=SECRET", "git"),
            ("https", "https://example.com/repo.git?anything=value", "git"),
            ("https", "https://example.com/repo.git#credential", "git"),
            ("ssh", "ssh://git@github.com/org/repo.git?token=SECRET", "git"),
            ("ssh", "ssh://git@github.com/org/repo.git#credential", "git"),
            ("ssh", "ssh://root@github.com/org/repo.git", "git"),
            ("ssh", "not a remote", "git"),
            ("https", "ssh://git@github.com/org/repo.git", "git"),
        )
        for index, (protocol, url, ssh_user) in enumerate(denied):
            with self.subTest(url=url), self.assertRaises(ValidationError), self.env.cr.savepoint():
                self.env["dev.git.remote"].create(
                    {
                        "name": "denied-%s-%s" % (index, uuid.uuid4().hex[:6]),
                        "repository_id": self.repository.id,
                        "remote_url": url,
                        "protocol": protocol,
                        "approved": True,
                        "allowed_ssh_user": ssh_user,
                        "credential_profile_reference": (
                            "/srv/devhub/credentials/github/test_ssh_config"
                        ),
                    }
                )

    def test_credential_bearing_legacy_remote_never_reaches_push_approval(self):
        _work, _plan, workspace, remote, _record, _checkpoint = (
            self._push_review_workspace()
        )
        secret_url = "https://github.com/org/repo.git?access_token=NEVER_STORE"
        self.env.cr.execute(
            "UPDATE dev_git_remote SET protocol = 'https', remote_url = %s WHERE id = %s",
            [secret_url, remote.id],
        )
        remote.invalidate_recordset(["protocol", "remote_url"])
        before = self.env["dev.git.push.approval"].search_count(
            [("workspace_id", "=", workspace.id)]
        )
        with self.assertRaises(ValidationError) as caught:
            self._create_push_approval(workspace, remote)
        self.assertNotIn("NEVER_STORE", str(caught.exception))
        self.assertEqual(
            self.env["dev.git.push.approval"].search_count(
                [("workspace_id", "=", workspace.id)]
            ),
            before,
        )
        self.assertFalse(
            self.env["dev.git.push.approval"].search(
                [("remote_url_reference", "ilike", "NEVER_STORE")]
            )
        )
        self.assertFalse(
            self.env["dev.git.push.approval.event"].search(
                [("payload_json", "ilike", "NEVER_STORE")]
            )
        )

    def test_push_denies_dirty_workspace_active_lease_and_production(self):
        _work, _plan, workspace, remote, _record, _checkpoint = (
            self._push_review_workspace()
        )
        workspace._internal_write({"dirty_summary": "changed=1"})
        fake = self._push_git_fake(workspace, remote)
        with patch.object(
            type(workspace), "_assert_worker_identity", autospec=True, return_value=True
        ), patch.object(
            type(workspace), "_assert_plan_unchanged", autospec=True, return_value=True
        ), patch.object(
            type(workspace), "_validate_physical", autospec=True, return_value=True
        ), patch.object(type(workspace), "_run_push_git", autospec=True, side_effect=fake):
            with self.assertRaises(AccessError):
                workspace.with_user(self.commit_manager)._assert_push_base(remote)
        workspace._internal_write(
            {
                "dirty_summary": "changed=0",
                "lease_token": "active-push-writer",
                "lease_expires_at": fields.Datetime.add(
                    fields.Datetime.now(), minutes=5
                ),
            }
        )
        with self.assertRaises(AccessError):
            self._create_push_approval(workspace, remote)
        workspace._internal_write({"lease_token": False, "lease_expires_at": False})
        production = self.environment.copy(
            {"name": "Push production denial", "environment_type": "production"}
        )
        workspace._internal_write({"environment_id": production.id})
        with self.assertRaises(UserError):
            self._create_push_approval(workspace, remote)

    def test_push_remote_advance_and_non_fast_forward_require_fresh_approval(self):
        _work, _plan, workspace, remote, _record, _checkpoint = (
            self._push_review_workspace()
        )
        approval = self._create_push_approval(workspace, remote)
        advanced = {workspace.execution_branch: "c" * 40}
        fake = self._push_git_fake(workspace, remote, heads=advanced)
        with patch.object(
            type(workspace), "_assert_push_approval_current", autospec=True, return_value=True
        ), patch.object(
            type(workspace), "_run_push_git", autospec=True, side_effect=fake
        ), patch.object(
            type(workspace),
            "_main_snapshot",
            autospec=True,
            return_value={"branch": "main", "head": "a" * 40, "digest": "0" * 64},
        ):
            with self.assertRaises(AccessError):
                workspace.with_user(self.commit_manager).execute_approved_push(approval)

    def test_push_git_runner_forbids_force_all_and_tags(self):
        _work, _plan, workspace, _remote, _record, _checkpoint = (
            self._push_review_workspace()
        )
        commands = (
            ["push", "-f", "origin"],
            ["push", "--force", "origin"],
            ["push", "--force=true", "origin"],
            ["push", "--force=false", "origin"],
            ["push", "--force-with-lease", "origin"],
            ["push", "--force-with-lease=refs/heads/test", "origin"],
            ["push", "--force-if-includes", "origin"],
            ["push", "origin", "+refs/heads/x:refs/heads/y"],
            ["push", "origin", "+branch"],
            ["push", "--porcelain", "origin", "+refs/heads/x:refs/heads/y"],
            ["push", "--porcelain", "--force=true", "origin", "branch"],
            ["push", "--all", "origin"],
            ["push", "--tags", "origin"],
        )
        with patch(
            "odoo.addons.dev_session_hub.models.dev_git_push.subprocess.run"
        ) as subprocess_run:
            for command in commands:
                with self.subTest(command=command), self.assertRaises(AccessError):
                    workspace._run_push_git(command)
            subprocess_run.assert_not_called()
        ssh_remote = self.env["dev.git.remote"].create(
            {
                "name": "github-ssh-%s" % uuid.uuid4().hex[:8],
                "repository_id": self.repository.id,
                "remote_url": "git@github.com:sabryyoussef/veterinarian_19.git",
                "protocol": "ssh",
                "approved": True,
                "non_production": True,
                "allowed_branch_prefix": "devhub/",
                "allowed_ssh_user": "git",
                "credential_profile_reference": (
                    "/srv/devhub/credentials/github/push_ssh_config"
                ),
            }
        )
        with patch(
            "odoo.addons.dev_session_hub.models.dev_git_push.subprocess.run",
            return_value=SimpleNamespace(returncode=0, stdout=b"", stderr=b""),
        ) as subprocess_run:
            workspace._run_push_git(
                ["ls-remote", "--heads", "--tags", ssh_remote.name]
            )
        environment = subprocess_run.call_args.kwargs["env"]
        self.assertEqual(
            environment["GIT_SSH_COMMAND"],
            "/usr/bin/ssh -F /srv/devhub/credentials/github/push_ssh_config",
        )
        self.assertNotIn("PRIVATE KEY", json.dumps(environment))

    def test_push_failure_reconciliation_states_and_retry_gate(self):
        scenarios = (
            ("exact", 1, "reconciled_success", "pushed_reviewed"),
            ("mismatch", 1, "push_failed_review", "push_failed_review"),
            ("unknown", 1, "uncertain_remote_state", "uncertain_remote_state"),
        )
        for label, returncode, record_state, workspace_state in scenarios:
            with self.subTest(label=label):
                _work, _plan, workspace, remote, _record, _checkpoint = (
                    self._push_review_workspace()
                )
                approval = self._create_push_approval(workspace, remote)
                before = {
                    "heads": {},
                    "tags": {},
                    "heads_json": "{}",
                    "tags_json": "{}",
                    "heads_digest": approval.remote_heads_digest,
                    "tags_digest": approval.remote_tags_digest,
                    "target_head": None,
                }
                if label == "exact":
                    after = {
                        **before,
                        "heads": {workspace.execution_branch: approval.commit_sha},
                        "heads_digest": "a" * 64,
                        "target_head": approval.commit_sha,
                    }
                elif label == "mismatch":
                    after = {
                        **before,
                        "heads": {workspace.execution_branch: "c" * 40},
                        "heads_digest": "b" * 64,
                        "target_head": "c" * 40,
                    }
                else:
                    after = UserError("transport unavailable with no credential detail")

                def git_result(_workspace, args, check=True):
                    if args[0] in ("fetch",):
                        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
                    if args[0] == "push":
                        return SimpleNamespace(
                            returncode=returncode,
                            stdout=b"",
                            stderr=b"sanitized transport failure",
                        )
                    raise AssertionError("Unexpected reconciliation Git call: %r" % args)

                snapshots = [before, after]
                main = {"branch": "main", "head": "a" * 40, "digest": "0" * 64}
                with patch.object(
                    type(workspace),
                    "_assert_push_approval_current",
                    autospec=True,
                    return_value=True,
                ), patch.object(
                    type(workspace), "_run_push_git", autospec=True, side_effect=git_result
                ), patch.object(
                    type(workspace),
                    "_remote_snapshot",
                    autospec=True,
                    side_effect=snapshots,
                ), patch.object(
                    type(workspace), "_validate_physical", autospec=True, return_value=True
                ), patch.object(
                    type(workspace), "_main_snapshot", autospec=True, return_value=main
                ):
                    record = workspace.with_user(
                        self.commit_manager
                    ).execute_approved_push(approval)
                self.assertEqual(record.reconciliation_state, record_state)
                self.assertEqual(workspace.state, workspace_state)
                self.assertEqual(record.expected_remote_head, approval.commit_sha)
                self.assertEqual(
                    record.approved_pre_refs_digest, approval.remote_heads_digest
                )
                if label == "unknown":
                    self.assertFalse(record.observed_post_refs_digest)
                else:
                    self.assertTrue(record.observed_post_refs_digest)
                if workspace_state != "pushed_reviewed":
                    with self.assertRaises(AccessError):
                        self._create_push_approval(workspace, remote)

    def test_exact_push_updates_one_branch_and_creates_no_delivery_action(self):
        _work, _plan, workspace, remote, _record, _checkpoint = (
            self._push_review_workspace()
        )
        approval = self._create_push_approval(workspace, remote)
        calls = []

        def push_fake(_workspace, args, check=True):
            calls.append(args)
            if args == ["fetch", "--no-tags", "--prune", remote.name]:
                return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
            if args == ["ls-remote", "--heads", "--tags", remote.name]:
                pushed = any(call and call[0] == "push" for call in calls)
                output = (
                    "%s\trefs/heads/%s\n"
                    % (approval.commit_sha, approval.remote_branch)
                    if pushed
                    else ""
                )
                return SimpleNamespace(
                    returncode=0, stdout=output.encode(), stderr=b""
                )
            if args and args[0] == "push":
                return SimpleNamespace(returncode=0, stdout=b"ok\n", stderr=b"")
            raise AssertionError("Unexpected exact Push call: %r" % (args,))

        main = {"branch": "main", "head": "a" * 40, "digest": "0" * 64}
        with patch.object(
            type(workspace), "_assert_push_approval_current", autospec=True, return_value=True
        ), patch.object(
            type(workspace), "_run_push_git", autospec=True, side_effect=push_fake
        ), patch.object(
            type(workspace), "_validate_physical", autospec=True, return_value=True
        ), patch.object(
            type(workspace), "_main_snapshot", autospec=True, return_value=main
        ):
            record = workspace.with_user(self.commit_manager).execute_approved_push(
                approval
            )
        push_calls = [call for call in calls if call and call[0] == "push"]
        self.assertEqual(
            push_calls,
            [
                [
                    "push",
                    "--porcelain",
                    remote.name,
                    "refs/heads/%s:refs/heads/%s"
                    % (workspace.execution_branch, workspace.execution_branch),
                ]
            ],
        )
        flattened = " ".join(" ".join(call) for call in push_calls)
        for forbidden in ("--force", "--all", "--tags", "merge", "deploy", "pull-request"):
            self.assertNotIn(forbidden, flattened)
        self.assertEqual(workspace.state, "pushed_reviewed")
        self.assertEqual(record.remote_head_after, workspace.committed_sha)
        self.assertEqual(record.result, "success")
        self.assertEqual(approval.approval_state, "consumed")

    def _verified_pr_metadata(self, approval, number=42):
        return {
            "number": number,
            "html_url": "https://github.com/%s/pull/%s"
            % (approval.github_repository, number),
            "state": "open",
            "title": approval.pr_title,
            "head": {
                "ref": approval.source_branch,
                "sha": approval.source_commit_sha,
            },
            "base": {"ref": approval.target_branch},
            "merged": False,
            "auto_merge": None,
        }

    def test_pr_target_policy_rejects_arbitrary_and_protected_targets(self):
        _work, _plan, _workspace, remote, target, _record, _checkpoint = (
            self._pr_review_workspace()
        )
        invalid = (
            (
                {"github_repository": "https://github.com/example/devhub-uat"},
                ValidationError,
            ),
            (
                {"github_repository": "example/devhub-uat?token=secret"},
                ValidationError,
            ),
            (
                {
                    "target_branch": "main",
                    "allowed_target_branches": "main\nstaging",
                },
                AccessError,
            ),
            (
                {
                    "target_branch": "release/1.0",
                    "allowed_target_branches": "release/1.0\nstaging",
                },
                AccessError,
            ),
            (
                {
                    "credential_profile_reference": "token=NEVER_STORE",
                    "github_repository": "example/devhub-uat-other",
                },
                ValidationError,
            ),
            (
                {
                    "github_repository": "example/restriction-mismatch",
                    "credential_repository_restriction": "example/devhub-uat",
                },
                ValidationError,
            ),
            (
                {
                    "github_repository": "example/excessive-permissions",
                    "credential_repository_restriction": (
                        "example/excessive-permissions"
                    ),
                    "credential_permission_summary": (
                        "administration:write\ncontents:read\nmetadata:read\n"
                        "pull_requests:write"
                    ),
                },
                ValidationError,
            ),
            (
                {
                    "github_repository": "example/unsafe-broker",
                    "credential_repository_restriction": "example/unsafe-broker",
                    "credential_broker_reference": "/tmp/mint-token",
                },
                ValidationError,
            ),
        )
        for values, expected_error in invalid:
            with self.subTest(values=values), self.assertRaises(expected_error):
                target.copy({**values, "name": uuid.uuid4().hex})
        self.assertFalse(
            self.env["dev.git.pr.target"].search(
                [("github_repository", "ilike", "token=")]
            )
        )
        with self.assertRaises(ValidationError):
            self.env["dev.git.pr.target"].create(
                {
                    "name": "Arbitrary URL",
                    "repository_id": self.repository.id,
                    "source_remote_id": remote.id,
                    "target_repository_id": self.repository.id,
                    "github_repository": "https://evil.invalid/repository",
                    "target_branch": "staging",
                    "credential_profile_reference": "/safe/profile",
                    "credential_broker_reference": (
                        "/srv/devhub/credentials/github/mint-token"
                    ),
                    "github_app_slug": "devhub-pr-uat",
                    "github_app_id": 1001,
                    "github_installation_id": 2001,
                    "credential_repository_restriction": (
                        "https://evil.invalid/repository"
                    ),
                }
            )

    def test_pr_requires_human_approval_and_verified_push(self):
        _work, _plan, workspace, _remote, target, _record, _checkpoint = (
            self._pr_review_workspace()
        )
        with self.assertRaises(AccessError):
            workspace.with_user(self.commit_manager).execute_approved_pr(False)
        ordinary = new_test_user(
            self.env,
            login="pr-non-manager-%s" % uuid.uuid4().hex,
            groups="dev_session_hub.group_dev_hub_user",
        )
        self.dev_project.write({"member_ids": [(4, ordinary.id)]})
        with self.assertRaises(AccessError):
            workspace.with_user(ordinary).create_pr_approval(
                target, "[DW] denied", "Denied non-manager attempt."
            )
        workspace._internal_write({"state": "committed_reviewed"})
        patches = self._pr_base_patches(workspace)
        with patches[0], patches[1], patches[2], patches[3], patches[4], self.assertRaises(
            AccessError
        ):
            workspace.with_user(self.commit_manager)._assert_pr_base(target)
        workspace._internal_write(
            {"state": "pushed_reviewed", "push_record_id": False}
        )
        patches = self._pr_base_patches(workspace)
        with patches[0], patches[1], patches[2], patches[3], patches[4], self.assertRaises(
            AccessError
        ):
            workspace.with_user(self.commit_manager)._assert_pr_base(target)

    def test_pr_approval_is_immutable_and_all_bound_drift_is_denied(self):
        drift_cases = (
            ("pr_title_preview", "changed title"),
            ("pr_body_preview", "changed body"),
            ("execution_branch", "devhub/changed-source"),
            ("committed_sha", "c" * 40),
            ("policy_hash", "d" * 64),
            ("execution_contract_hash", "e" * 64),
            ("approved_plan_hash", "f" * 64),
        )
        for field_name, changed in drift_cases:
            with self.subTest(field_name=field_name):
                _work, _plan, workspace, _remote, target, _record, _checkpoint = (
                    self._pr_review_workspace()
                )
                approval = self._create_pr_approval(workspace, target)
                workspace._internal_write({field_name: changed})
                patches = self._pr_base_patches(workspace)
                with patches[0], patches[1], patches[2], patches[3], patches[4], patch.object(
                    type(workspace),
                    "_github_json",
                    autospec=True,
                    return_value={"ref": "refs/heads/staging"},
                ), self.assertRaises(AccessError):
                    workspace.with_user(
                        self.commit_manager
                    )._assert_pr_approval_current(approval)
        with self.assertRaises(AccessError):
            approval.write({"pr_title": "Mutated"})
        with self.assertRaises(AccessError):
            approval.unlink()
        _work, _plan, workspace, _remote, target, _record, _checkpoint = (
            self._pr_review_workspace()
        )
        approval = self._create_pr_approval(workspace, target)
        target.write({"target_branch": "test"})
        patches = self._pr_base_patches(workspace)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patch.object(
            type(workspace),
            "_github_json",
            autospec=True,
            return_value={"ref": "refs/heads/test"},
        ), self.assertRaises(AccessError):
            workspace.with_user(
                self.commit_manager
            )._assert_pr_approval_current(approval)
        with self.assertRaises(AccessError):
            approval.copy()

    def test_pr_denies_active_writer_and_uncertain_push_state(self):
        _work, _plan, workspace, _remote, target, _record, _checkpoint = (
            self._pr_review_workspace()
        )
        workspace._internal_write(
            {
                "lease_token": "active-writer",
                "lease_expires_at": fields.Datetime.add(
                    fields.Datetime.now(), minutes=5
                ),
            }
        )
        with self.assertRaises(AccessError):
            self._create_pr_approval(workspace, target)
        workspace._internal_write(
            {
                "lease_token": False,
                "lease_expires_at": False,
                "state": "uncertain_remote_state",
            }
        )
        with self.assertRaises(AccessError):
            self._create_pr_approval(workspace, target)

    def test_pr_duplicate_is_fail_closed_before_creation(self):
        _work, _plan, workspace, _remote, target, _record, _checkpoint = (
            self._pr_review_workspace()
        )
        approval = self._create_pr_approval(workspace, target)
        existing = [self._verified_pr_metadata(approval)]
        with patch.object(
            type(workspace),
            "_assert_pr_approval_current",
            autospec=True,
            return_value=True,
        ), patch.object(
            type(workspace),
            "_matching_open_prs",
            autospec=True,
            return_value=existing,
        ), patch.object(
            type(workspace), "_run_gh", autospec=True
        ) as run_gh, self.assertRaises(AccessError):
            workspace.with_user(self.commit_manager).execute_approved_pr(approval)
        run_gh.assert_not_called()
        self.assertFalse(workspace.pr_record_id)

    def test_exact_pr_creation_verifies_open_unmerged_without_auto_merge(self):
        _work, _plan, workspace, _remote, target, _record, _checkpoint = (
            self._pr_review_workspace()
        )
        approval = self._create_pr_approval(workspace, target)
        metadata = self._verified_pr_metadata(approval)
        calls = []

        def gh_call(_workspace, _target, args, input_payload=None, check=True):
            calls.append((args, input_payload))
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps({"number": metadata["number"]}).encode(),
                stderr=b"",
            )

        with patch.object(
            type(workspace),
            "_assert_pr_approval_current",
            autospec=True,
            return_value=True,
        ), patch.object(
            type(workspace),
            "_matching_open_prs",
            autospec=True,
            return_value=[],
        ), patch.object(
            type(workspace), "_run_gh", autospec=True, side_effect=gh_call
        ), patch.object(
            type(workspace), "_github_json", autospec=True, return_value=metadata
        ):
            record = workspace.with_user(
                self.commit_manager
            ).execute_approved_pr(approval)
        self.assertEqual(record.result_state, "created")
        self.assertEqual(workspace.state, "pr_created_reviewed")
        self.assertEqual(record.pr_number, metadata["number"])
        self.assertIn("/pull/%s" % metadata["number"], record.pr_url_reference)
        self.assertEqual(len(calls), 1)
        args, payload = calls[0]
        self.assertEqual(
            args,
            [
                "-X",
                "POST",
                "repos/example/devhub-uat/pulls",
                "--input",
                "-",
            ],
        )
        self.assertEqual(payload["head"], approval.source_branch)
        self.assertEqual(payload["base"], "staging")
        self.assertFalse(payload["draft"])
        self.assertFalse(payload["maintainer_can_modify"])
        serialized = json.dumps({"args": args, "payload": payload}).casefold()
        for forbidden in (
            "merge",
            "auto_merge",
            "deployment",
            "delete",
            "branch protection",
        ):
            self.assertNotIn(forbidden, serialized)
        self.assertEqual(approval.approval_state, "consumed")
        with self.assertRaises(AccessError):
            record.copy()
        with self.assertRaises(AccessError):
            record.write({"verification_result": "mutated"})
        with self.assertRaises(AccessError):
            record.unlink()
        event = approval.event_ids[:1]
        with self.assertRaises(AccessError):
            event.write({"summary": "mutated"})
        with self.assertRaises(AccessError):
            event.unlink()

    def test_pr_failure_reconciliation_and_retry_gate(self):
        scenarios = (
            ("existing", "reconciled_existing", "pr_created_reviewed"),
            ("absent", "creation_failed_review", "pr_creation_failed_review"),
            ("unknown", "uncertain_remote_state", "pr_uncertain_state"),
        )
        for label, result_state, workspace_state in scenarios:
            with self.subTest(label=label):
                _work, _plan, workspace, _remote, target, _record, _checkpoint = (
                    self._pr_review_workspace()
                )
                approval = self._create_pr_approval(workspace, target)
                metadata = self._verified_pr_metadata(approval)
                failed = SimpleNamespace(
                    returncode=1, stdout=b"", stderr=b"sanitized API failure"
                )
                if label == "existing":
                    lookups = [[], [metadata]]
                elif label == "absent":
                    lookups = [[], []]
                else:
                    lookups = [[], UserError("GitHub state unavailable")]

                def lookup(_workspace, _target, _approval=None):
                    result = lookups.pop(0)
                    if isinstance(result, Exception):
                        raise result
                    return result

                with patch.object(
                    type(workspace),
                    "_assert_pr_approval_current",
                    autospec=True,
                    return_value=True,
                ), patch.object(
                    type(workspace),
                    "_matching_open_prs",
                    autospec=True,
                    side_effect=lookup,
                ), patch.object(
                    type(workspace), "_run_gh", autospec=True, return_value=failed
                ), patch.object(
                    type(workspace),
                    "_github_json",
                    autospec=True,
                    return_value=metadata,
                ):
                    record = workspace.with_user(
                        self.commit_manager
                    ).execute_approved_pr(approval)
                self.assertEqual(record.result_state, result_state)
                self.assertEqual(workspace.state, workspace_state)
                if result_state != "reconciled_existing":
                    with self.assertRaises(AccessError):
                        self._create_pr_approval(workspace, target)

    def test_pr_github_runner_is_api_scoped_and_uses_stdin(self):
        _work, _plan, workspace, _remote, target, _record, _checkpoint = (
            self._pr_review_workspace()
        )
        forbidden = (
            ["repos/example/devhub-uat/merges"],
            ["repos/example/devhub-uat/pulls/1/merge"],
            ["repos/other/repository/pulls"],
        )
        with patch(
            "odoo.addons.dev_session_hub.models.dev_git_pr.subprocess.run"
        ) as subprocess_run:
            for args in forbidden:
                with self.subTest(args=args), self.assertRaises(AccessError):
                    workspace._run_gh(target, args)
            subprocess_run.assert_not_called()
        with patch(
            "odoo.addons.dev_session_hub.models.dev_git_pr.subprocess.run",
            return_value=SimpleNamespace(returncode=0, stdout=b"{}", stderr=b""),
        ) as subprocess_run:
            workspace._run_gh(
                target,
                [
                    "-X",
                    "POST",
                    "repos/example/devhub-uat/pulls",
                    "--input",
                    "-",
                ],
                input_payload={
                    "title": "safe",
                    "head": workspace.execution_branch,
                    "base": target.target_branch,
                    "body": "safe body",
                    "draft": False,
                    "maintainer_can_modify": False,
                },
            )
        command = subprocess_run.call_args.args[0]
        self.assertNotIn("safe body", " ".join(command))
        self.assertNotIn("token", " ".join(command).casefold())
        self.assertNotIn("stdin", subprocess_run.call_args.kwargs)
        self.assertTrue(subprocess_run.call_args.kwargs["input"])
        broker_metadata = {
            "credential_type": "github_app_installation",
            "app_id": target.github_app_id,
            "installation_id": target.github_installation_id,
            "repositories": [target.github_repository],
            "permissions": {
                "contents": "read",
                "metadata": "read",
                "pull_requests": "write",
            },
            "expires_at": fields.Datetime.to_string(
                fields.Datetime.add(fields.Datetime.now(), minutes=50)
            ).replace(" ", "T")
            + "Z",
        }
        with patch(
            "odoo.addons.dev_session_hub.models.dev_git_pr.subprocess.run",
            return_value=SimpleNamespace(
                returncode=0,
                stdout=json.dumps(broker_metadata).encode(),
                stderr=b"",
            ),
        ) as broker_run:
            self.assertTrue(
                workspace._prepare_github_app_credential(target)
            )
        self.assertEqual(
            broker_run.call_args.args[0],
            [target.credential_broker_reference],
        )
        broker_environment = broker_run.call_args.kwargs["env"]
        self.assertNotIn("GH_TOKEN", broker_environment)
        self.assertNotIn("GITHUB_TOKEN", broker_environment)
        serialized_environment = json.dumps(broker_environment)
        self.assertNotIn("ghs_", serialized_environment)
        self.assertNotIn("Bearer ", serialized_environment)
        broad = SimpleNamespace(
            returncode=0,
            stdout=b"HTTP/2 200\r\nX-Oauth-Scopes: repo, admin:public_key\r\n\r\n{}",
            stderr=b"",
        )
        expires_at = fields.Datetime.add(fields.Datetime.now(), minutes=50)
        with patch.object(
            type(workspace), "_run_gh", autospec=True, return_value=broad
        ), patch.object(
            type(workspace),
            "_prepare_github_app_credential",
            autospec=True,
            return_value=expires_at,
        ), self.assertRaises(AccessError):
            workspace._assert_scoped_github_identity(target)
        scoped = SimpleNamespace(
            returncode=0,
            stdout=b"HTTP/2 200\r\nX-GitHub-Request-Id: SAFE\r\n\r\n{}",
            stderr=b"",
        )
        app_metadata = {
            "id": target.github_app_id,
            "slug": target.github_app_slug,
            "permissions": {
                "contents": "read",
                "metadata": "read",
                "pull_requests": "write",
            },
        }
        installation = {
            "total_count": 1,
            "repositories": [{"full_name": target.github_repository}],
        }
        with patch.object(
            type(workspace), "_run_gh", autospec=True, return_value=scoped
        ), patch.object(
            type(workspace),
            "_prepare_github_app_credential",
            autospec=True,
            return_value=expires_at,
        ), patch.object(
            type(workspace),
            "_github_json",
            autospec=True,
            side_effect=[app_metadata, installation],
        ):
            self.assertTrue(workspace._assert_scoped_github_identity(target))
        self.assertTrue(target.credential_validated_at)
        self.assertTrue(target.credential_validation_digest)
        excessive = {
            **app_metadata,
            "permissions": {
                **app_metadata["permissions"],
                "administration": "write",
            },
        }
        with patch.object(
            type(workspace), "_run_gh", autospec=True, return_value=scoped
        ), patch.object(
            type(workspace),
            "_prepare_github_app_credential",
            autospec=True,
            return_value=expires_at,
        ), patch.object(
            type(workspace),
            "_github_json",
            autospec=True,
            side_effect=[excessive, installation],
        ), self.assertRaises(AccessError):
            workspace._assert_scoped_github_identity(target)
        multiple_repositories = {
            "total_count": 2,
            "repositories": [
                {"full_name": target.github_repository},
                {"full_name": "example/other"},
            ],
        }
        with patch.object(
            type(workspace), "_run_gh", autospec=True, return_value=scoped
        ), patch.object(
            type(workspace),
            "_prepare_github_app_credential",
            autospec=True,
            return_value=expires_at,
        ), patch.object(
            type(workspace),
            "_github_json",
            autospec=True,
            side_effect=[app_metadata, multiple_repositories],
        ), self.assertRaises(AccessError):
            workspace._assert_scoped_github_identity(target)
        target.write({"credential_type": "fine_grained_pat"})
        with self.assertRaises(AccessError):
            workspace._assert_scoped_github_identity(target)

    def test_isolated_session_derives_workspace_and_never_falls_back(self):
        work = self._work()
        self._approved_plan(work)
        workspace = self._workspace_proposal(work)
        workspace._internal_write({"state": "ready"})
        session = self.env["dev.session"].create(
            {
                "client_id": self.windows.id,
                "work_item_id": work.id,
                "execution_workspace_id": workspace.id,
            }
        )
        self.assertEqual(session.session_type, "isolated_execution_workspace")
        self.assertEqual(session.working_directory, workspace.worktree_path)
        self.assertNotEqual(session.working_directory, self.repository.working_directory)
        with self.assertRaises(ValidationError):
            self.env["dev.session"].create(
                {
                    "client_id": self.windows.id,
                    "work_item_id": work.id,
                    "execution_workspace_id": workspace.id,
                    "working_directory": self.repository.working_directory,
                }
            )

    def test_missing_or_dirty_workspace_fails_closed(self):
        work = self._work()
        self._approved_plan(work)
        workspace = self._workspace_proposal(work)
        workspace._internal_write({"state": "ready"})
        with self.assertRaises(UserError):
            workspace.action_validate()
        workspace._internal_write({"state": "paused"})
        with self.assertRaises(UserError):
            workspace.action_resume()
        workspace._internal_write({"state": "released", "dirty_summary": "changed=1"})
        with patch.object(
            type(workspace), "_validate_physical", autospec=True, return_value=True
        ):
            with self.assertRaises(UserError):
                workspace.action_request_cleanup()

    def test_workspace_preparation_never_commits_pushes_merges_or_deploys(self):
        work = self._work()
        self._approved_plan(work)
        self._execution_repository()
        model = self.env["dev.execution.workspace"]
        snapshot = {
            "branch": "feature/manual-work",
            "head": "b" * 40,
            "dirty": "staged=0; unstaged=0; untracked=0; conflicts=0",
            "digest": "0" * 64,
        }
        with patch.object(
            type(model), "_main_snapshot", autospec=True, return_value=snapshot
        ), patch.object(type(model), "_git", autospec=True) as git_call:
            workspace = model.create_proposal(work)
        self.assertEqual(workspace.state, "pending_confirmation")
        git_call.assert_not_called()
        for command in (
            ["commit", "-am", "forbidden"],
            ["push", "origin", "HEAD"],
            ["merge", "main"],
            ["reset", "--hard"],
            ["clean", "-fd"],
            ["checkout", "main"],
            ["stash"],
        ):
            with self.assertRaises(AccessError):
                model._git(command)

    def _merge_review_workspace(self):
        work, plan, workspace, _remote, pr_target, _commit, checkpoint = (
            self._pr_review_workspace()
        )
        pr_approval = self._create_pr_approval(workspace, pr_target)
        now = fields.Datetime.now()
        pr_number = 42
        pr_record = (
            self.env["dev.git.pr.record"]
            .sudo()
            .with_context(dev_git_pr_record=True)
            .create(
                {
                    "work_item_id": work.id,
                    "workspace_id": workspace.id,
                    "approval_id": pr_approval.id,
                    "target_id": pr_target.id,
                    "github_repository": pr_target.github_repository,
                    "source_branch": workspace.execution_branch,
                    "source_sha": workspace.committed_sha,
                    "target_branch": "staging",
                    "credential_type": pr_target.credential_type,
                    "credential_owner_reference": (
                        pr_target.credential_owner_reference
                    ),
                    "github_app_id": pr_target.github_app_id,
                    "github_installation_id": pr_target.github_installation_id,
                    "credential_validation_digest": (
                        pr_target.credential_validation_digest
                    ),
                    "pr_title": pr_approval.pr_title,
                    "pr_body_digest": pr_approval.pr_body_digest,
                    "pr_number": pr_number,
                    "pr_url_reference": (
                        "https://github.com/%s/pull/%s"
                        % (pr_target.github_repository, pr_number)
                    ),
                    "approver_id": self.commit_manager.id,
                    "created_at": now,
                    "result_state": "created",
                    "verification_result": "open; unmerged; auto-merge disabled",
                    "idempotency_key": pr_approval.idempotency_key,
                    "api_correlation_reference": "corr-pr-42",
                    "audit_hash": "pending",
                }
            )
        )
        requester = new_test_user(
            self.env,
            login="devhub-merge-requester-%s" % uuid.uuid4().hex,
            groups="dev_session_hub.group_dev_hub_user",
        )
        self.dev_project.write({"member_ids": [(4, requester.id)]})
        target = self.env["dev.git.merge.target"].create(
            {
                "name": "Controlled staging squash %s" % uuid.uuid4().hex[:8],
                "repository_id": self.repository.id,
                "pr_target_id": pr_target.id,
                "github_repository": pr_target.github_repository,
                "base_branch": "staging",
                "merge_method": "squash",
                "requester_user_id": requester.id,
                "required_check_name": "GitGuardian Security Checks",
                "required_check_app_id": 46505,
                "credential_profile_reference": (
                    "/srv/devhub/credentials/github/merge-profile"
                ),
                "credential_broker_reference": (
                    "/srv/devhub/credentials/github/mint-devhub-merge-token"
                ),
                "github_app_slug": "sabry-uat-merge-agent",
                "github_app_id": 3001,
                "github_installation_id": 4001,
                "credential_repository_restriction": (
                    pr_target.github_repository
                ),
                "credential_permission_summary": (
                    "checks:read\ncontents:write\nmetadata:read\n"
                    "pull_requests:read\nstatuses:read"
                ),
                "credential_validation_digest": "7" * 64,
                "approved": True,
                "non_production": True,
            }
        )
        workspace._internal_write(
            {
                "state": "pr_created_reviewed",
                "pr_record_id": pr_record.id,
                "pr_number": pr_number,
                "pr_url_reference": pr_record.pr_url_reference,
                "pr_created_at": now,
                "merge_request_work_item_id": work.id,
                "merge_target_id": target.id,
                "merge_requester_id": requester.id,
                "merge_requested_at": now,
            }
        )
        return work, plan, workspace, target, requester, pr_record, checkpoint

    def _merge_snapshot(self, workspace):
        return {
            "repository": "example/devhub-uat",
            "number": 42,
            "url": "https://github.com/example/devhub-uat/pull/42",
            "head_branch": workspace.execution_branch,
            "head_sha": workspace.committed_sha,
            "base_branch": "staging",
            "base_sha": "d" * 40,
            "pr_metadata_digest": "1" * 64,
            "checks_digest": "2" * 64,
            "checks_summary": json.dumps(
                [
                    {
                        "name": "GitGuardian Security Checks",
                        "app_id": 46505,
                        "status": "completed",
                        "conclusion": "success",
                    }
                ],
                sort_keys=True,
            ),
        }

    def _create_merge_approval(self, workspace, target, snapshot=None):
        workspace = workspace.with_user(self.commit_manager)
        snapshot = snapshot or self._merge_snapshot(workspace)
        with patch.object(
            type(workspace), "_merge_preflight", autospec=True, return_value=snapshot
        ):
            return workspace.create_merge_approval(target)

    def test_merge_target_policy_is_exact_and_separate(self):
        _work, _plan, _workspace, target, _requester, _record, _checkpoint = (
            self._merge_review_workspace()
        )
        invalid = (
            {"github_app_slug": "devhub-pr-uat"},
            {"credential_permission_summary": "contents:write"},
            {"base_branch": "main"},
            {"github_repository": "example/other"},
            {"credential_broker_reference": "/tmp/broker"},
            {"requester_user_id": self.commit_manager.id},
        )
        for values in invalid:
            with self.subTest(values=values), self.env.cr.savepoint(), self.assertRaises(
                ValidationError
            ):
                target.write(values)
            target.invalidate_recordset()

    def test_merge_requires_dedicated_distinct_current_approval(self):
        _work, _plan, workspace, target, requester, _record, _checkpoint = (
            self._merge_review_workspace()
        )
        workspace._internal_write(
            {
                "merge_target_id": False,
                "merge_requester_id": False,
                "merge_requested_at": False,
            }
        )
        with self.assertRaises(AccessError):
            workspace.with_user(self.commit_manager).action_request_merge_review()
        workspace.with_user(requester).action_request_merge_review()
        self.assertEqual(workspace.merge_requester_id, requester)
        self.assertTrue(workspace.merge_requested_at)
        with self.assertRaises(AccessError):
            workspace.execute_approved_merge(False)
        with self.assertRaises(AccessError):
            workspace.execute_approved_merge(workspace.pr_approval_id)
        with self.assertRaises(AccessError):
            workspace.with_user(requester).create_merge_approval(target)
        self.env.cr.execute(
            "UPDATE dev_git_merge_target SET requester_user_id = %s WHERE id = %s",
            [self.commit_manager.id, target.id],
        )
        target.invalidate_recordset(["requester_user_id"])
        with self.assertRaises(AccessError):
            self._create_merge_approval(workspace, target)
        self.env.cr.execute(
            "UPDATE dev_git_merge_target SET requester_user_id = %s WHERE id = %s",
            [requester.id, target.id],
        )
        target.invalidate_recordset(["requester_user_id"])
        approval = self._create_merge_approval(workspace, target)
        self.assertNotEqual(approval.requester_id, approval.approver_id)
        self.assertEqual(approval.merge_method, "squash")
        self.assertNotEqual(approval.id, workspace.pr_approval_id.id)
        with self.assertRaises(AccessError):
            approval.write({"head_sha": "e" * 40})
        with self.assertRaises(AccessError):
            approval.unlink()
        with self.assertRaises(AccessError):
            approval.copy()

    def test_merge_approval_rejects_head_base_check_and_policy_drift(self):
        _work, _plan, workspace, target, _requester, _record, _checkpoint = (
            self._merge_review_workspace()
        )
        snapshot = self._merge_snapshot(workspace)
        approval = self._create_merge_approval(workspace, target, snapshot)
        drift_cases = (
            ("head_sha", "e" * 40),
            ("base_sha", "f" * 40),
            ("checks_digest", "3" * 64),
            ("pr_metadata_digest", "4" * 64),
        )
        for name, value in drift_cases:
            changed = {**snapshot, name: value}
            with self.subTest(name=name), patch.object(
                type(workspace),
                "_merge_preflight",
                autospec=True,
                return_value=changed,
            ), self.assertRaises(AccessError):
                workspace.with_user(self.commit_manager)._assert_merge_approval_current(
                    approval
                )

    def test_merge_preflight_rejects_ineligible_pr_and_checks(self):
        _work, _plan, workspace, target, _requester, _record, _checkpoint = (
            self._merge_review_workspace()
        )
        metadata = {
            "html_url": "https://github.com/example/devhub-uat/pull/42",
            "state": "open",
            "merged": False,
            "draft": False,
            "auto_merge": None,
            "head": {
                "ref": workspace.execution_branch,
                "sha": workspace.committed_sha,
                "repo": {"full_name": target.github_repository},
            },
            "base": {
                "ref": "staging",
                "repo": {"full_name": target.github_repository},
            },
            "mergeable": True,
            "mergeable_state": "clean",
        }
        base = {"object": {"sha": "d" * 40}}
        checks = {
            "total_count": 1,
            "check_runs": [
                {
                    "name": target.required_check_name,
                    "app": {"id": target.required_check_app_id},
                    "status": "completed",
                    "conclusion": "success",
                }
            ],
        }
        status = {"statuses": [{"context": "required", "state": "success"}]}
        scenarios = (
            ({**metadata, "draft": True}, checks, status),
            ({**metadata, "state": "closed"}, checks, status),
            ({**metadata, "merged": True}, checks, status),
            ({**metadata, "mergeable": False}, checks, status),
            ({**metadata, "mergeable_state": "dirty"}, checks, status),
            (
                {
                    **metadata,
                    "head": {**metadata["head"], "sha": "e" * 40},
                },
                checks,
                status,
            ),
            (
                {
                    **metadata,
                    "base": {**metadata["base"], "ref": "main"},
                },
                checks,
                status,
            ),
            (
                {
                    **metadata,
                    "head": {
                        **metadata["head"],
                        "repo": {"full_name": "example/other"},
                    },
                },
                checks,
                status,
            ),
            (
                metadata,
                {
                    "total_count": 1,
                    "check_runs": [
                        {
                            **checks["check_runs"][0],
                            "conclusion": "failure",
                        }
                    ],
                },
                status,
            ),
            (
                metadata,
                {
                    "total_count": 1,
                    "check_runs": [
                        {
                            **checks["check_runs"][0],
                            "status": "in_progress",
                            "conclusion": None,
                        }
                    ],
                },
                status,
            ),
            (metadata, checks, {"statuses": [{"state": "pending"}]}),
        )
        for pr_data, check_data, status_data in scenarios:
            with self.subTest(pr=pr_data, checks=check_data), patch.object(
                type(workspace),
                "_assert_merge_identity",
                autospec=True,
                return_value=True,
            ), patch.object(
                type(workspace),
                "_assert_plan_unchanged",
                autospec=True,
                return_value=True,
            ), patch.object(
                type(workspace),
                "_merge_json",
                autospec=True,
                side_effect=[pr_data, base, [], check_data, status_data],
            ), self.assertRaises(AccessError):
                workspace.with_user(self.commit_manager)._merge_preflight(target)

    def test_merge_preflight_accepts_exact_successful_remote_state(self):
        _work, _plan, workspace, target, _requester, _record, _checkpoint = (
            self._merge_review_workspace()
        )
        metadata = {
            "html_url": "https://github.com/example/devhub-uat/pull/42",
            "state": "open",
            "merged": False,
            "draft": False,
            "auto_merge": None,
            "head": {
                "ref": workspace.execution_branch,
                "sha": workspace.committed_sha,
                "repo": {"full_name": target.github_repository},
            },
            "base": {
                "ref": "staging",
                "repo": {"full_name": target.github_repository},
            },
            "mergeable": True,
            "mergeable_state": "clean",
        }
        checks = {
            "total_count": 1,
            "check_runs": [
                {
                    "name": target.required_check_name,
                    "app": {"id": target.required_check_app_id},
                    "status": "completed",
                    "conclusion": "success",
                }
            ],
        }
        with patch.object(
            type(workspace),
            "_assert_merge_identity",
            autospec=True,
            return_value=True,
        ), patch.object(
            type(workspace),
            "_assert_plan_unchanged",
            autospec=True,
            return_value=True,
        ), patch.object(
            type(workspace),
            "_merge_json",
            autospec=True,
            side_effect=[
                metadata,
                {"object": {"sha": "d" * 40}},
                [],
                checks,
                {"statuses": [{"state": "success"}]},
            ],
        ):
            result = workspace.with_user(self.commit_manager)._merge_preflight(target)
        self.assertEqual(result["head_sha"], workspace.committed_sha)
        self.assertEqual(result["base_branch"], "staging")

    def test_merge_runner_allows_only_exact_squash_put_via_stdin(self):
        _work, _plan, workspace, target, _requester, _record, _checkpoint = (
            self._merge_review_workspace()
        )
        forbidden = (
            ["repos/example/devhub-uat/pulls/42/merge"],
            ["-X", "DELETE", "repos/example/devhub-uat/pulls/42/merge"],
            ["-X", "PUT", "repos/example/other/pulls/42/merge", "--input", "-"],
        )
        with patch(
            "odoo.addons.dev_session_hub.models.dev_git_merge.subprocess.run"
        ) as subprocess_run:
            for args in forbidden:
                with self.subTest(args=args), self.assertRaises(AccessError):
                    workspace._run_merge_gh(target, args, input_payload={})
            with self.assertRaises(AccessError):
                workspace._run_merge_gh(
                    target,
                    [
                        "-X",
                        "PUT",
                        "repos/example/devhub-uat/pulls/42/merge",
                        "--input",
                        "-",
                    ],
                    input_payload={
                        "sha": workspace.committed_sha,
                        "merge_method": "merge",
                        "commit_title": "forbidden",
                        "commit_message": "forbidden",
                    },
                )
            subprocess_run.assert_not_called()
        payload = {
            "sha": workspace.committed_sha,
            "merge_method": "squash",
            "commit_title": "controlled",
            "commit_message": "safe",
        }
        with patch(
            "odoo.addons.dev_session_hub.models.dev_git_merge.subprocess.run",
            return_value=SimpleNamespace(returncode=0, stdout=b"{}", stderr=b""),
        ) as subprocess_run:
            workspace._run_merge_gh(
                target,
                [
                    "-X",
                    "PUT",
                    "repos/example/devhub-uat/pulls/42/merge",
                    "--input",
                    "-",
                ],
                input_payload=payload,
            )
        command = subprocess_run.call_args.args[0]
        self.assertNotIn("safe", " ".join(command))
        self.assertNotIn("token", " ".join(command).casefold())
        self.assertTrue(subprocess_run.call_args.kwargs["input"])
        self.assertNotIn("deploy", " ".join(command).casefold())

    def test_merge_success_creates_exactly_one_terminal_audit_no_deploy(self):
        _work, _plan, workspace, target, _requester, _record, _checkpoint = (
            self._merge_review_workspace()
        )
        approval = self._create_merge_approval(workspace, target)
        merge_sha = "9" * 40
        put_result = SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"merged": True, "sha": merge_sha}).encode(),
            stderr=b"",
        )
        metadata = {
            "state": "closed",
            "merged": True,
            "merge_commit_sha": merge_sha,
            "head": {"sha": approval.head_sha},
            "base": {"ref": "staging"},
        }
        before = self.env["dev.git.merge.record"].sudo().search_count([])
        with patch.object(
            type(workspace),
            "_assert_merge_approval_current",
            autospec=True,
            return_value=True,
        ), patch.object(
            type(workspace),
            "_run_merge_gh",
            autospec=True,
            return_value=put_result,
        ) as api_call, patch.object(
            type(workspace),
            "_merge_json",
            autospec=True,
            side_effect=[metadata, {"object": {"sha": merge_sha}}],
        ):
            result = workspace.with_user(self.commit_manager).execute_approved_merge(
                approval
            )
        self.assertEqual(result.result_state, "merged")
        self.assertEqual(result.merge_sha, merge_sha)
        self.assertEqual(workspace.state, "merged_reviewed")
        self.assertEqual(
            self.env["dev.git.merge.record"].sudo().search_count([]), before + 1
        )
        payload = api_call.call_args.kwargs["input_payload"]
        self.assertEqual(payload["sha"], approval.head_sha)
        self.assertEqual(payload["merge_method"], "squash")
        self.assertNotIn("deploy", json.dumps(payload).casefold())
        with self.assertRaises(AccessError):
            workspace.with_user(self.commit_manager).execute_approved_merge(approval)

    def _assert_failed_merge_reconciliation(
        self, remote, expected_result, expected_state
    ):
        _work, _plan, workspace, target, _requester, _record, _checkpoint = (
            self._merge_review_workspace()
        )
        approval = self._create_merge_approval(workspace, target)
        if remote:
            remote["head"]["sha"] = approval.head_sha
        put_result = SimpleNamespace(returncode=1, stdout=b"", stderr=b"safe")
        side_effect = [remote] if remote else UserError("unavailable")
        with patch.object(
            type(workspace),
            "_assert_merge_approval_current",
            autospec=True,
            return_value=True,
        ), patch.object(
            type(workspace),
            "_run_merge_gh",
            autospec=True,
            return_value=put_result,
        ), patch.object(
            type(workspace),
            "_merge_json",
            autospec=True,
            side_effect=side_effect,
        ):
            result = workspace.with_user(self.commit_manager).execute_approved_merge(
                approval
            )
        self.assertEqual(result.result_state, expected_result)
        self.assertEqual(workspace.state, expected_state)
        with self.assertRaises(AccessError):
            workspace.with_user(self.commit_manager).execute_approved_merge(approval)

    def test_merge_api_failure_reconciles_success_without_retry(self):
        self._assert_failed_merge_reconciliation(
            {
                "state": "closed",
                "merged": True,
                "merge_commit_sha": "8" * 40,
                "head": {"sha": None},
                "base": {"ref": "staging"},
            },
            "reconciled_success",
            "merged_reviewed",
        )

    def test_merge_api_failure_requires_human_review_without_retry(self):
        self._assert_failed_merge_reconciliation(
            {"state": "open", "merged": False, "head": {"sha": None}},
            "merge_failed_review",
            "merge_failed_review",
        )

    def test_merge_api_failure_unknown_state_blocks_retry(self):
        self._assert_failed_merge_reconciliation(
            None, "uncertain_remote_state", "merge_uncertain_state"
        )
