# -*- coding: utf-8 -*-
import base64
import json
import socket
from unittest.mock import Mock, patch

from psycopg2.errors import UniqueViolation

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestDevSessionHub(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = cls.env.ref("dev_session_hub.dev_project_petspot")
        cls.seed_repository = cls.env.ref("dev_session_hub.dev_repository_petspot")
        cls.repository = cls.seed_repository
        cls.environment = cls.env.ref("dev_session_hub.dev_environment_petspot_test")
        cls.production_machine = cls.env.ref("dev_session_hub.dev_machine_master")
        cls.machine = cls.env["dev.machine"].create(
            {
                "name": "Dedicated Non-Production Test Target",
                "hostname": socket.gethostname(),
                "tailscale_name": "dev-target.tailcf9988.ts.net",
                "tailscale_ip_reference": "100.64.0.99",
                "tailscale_destination_verified": True,
                "tailscale_verified_at": "2026-07-18 16:20:00",
                "pinned_host_key_fingerprint": (
                    "SHA256:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
                ),
                "ssh_alias": "petspot-dev-ts",
                "role": "Automated test-only dedicated target",
                "trust_zone": "trusted_dev",
                "production": False,
                "allowed_path_prefixes": cls.repository.working_directory,
            }
        )
        cls.environment.machine_id = cls.machine
        cls.windows = cls.env.ref("dev_session_hub.dev_client_windows_desktop")
        cls.ubuntu = cls.env.ref("dev_session_hub.dev_client_ubuntu_precision")
        cls.task = cls.env.ref("dev_session_hub.dev_task_petspot_wp337")
        cls.dev_user = cls.env["res.users"].with_context(no_reset_password=True).create(
            {
                "name": "Authorized Dev Hub User",
                "login": "devhub-authorized-test",
                "group_ids": [
                    (
                        6,
                        0,
                        [cls.env.ref("dev_session_hub.group_dev_hub_user").id],
                    )
                ],
            }
        )
        cls.outsider = cls.env["res.users"].with_context(no_reset_password=True).create(
            {
                "name": "Unauthorized Dev Hub User",
                "login": "devhub-unauthorized-test",
                "group_ids": [
                    (
                        6,
                        0,
                        [cls.env.ref("dev_session_hub.group_dev_hub_user").id],
                    )
                ],
            }
        )
        cls.project.member_ids = [(4, cls.dev_user.id)]
        cls.snapshot = {
            "branch": "feature/resume-portability-candidates",
            "head": "efe1ba2f31aae160e8d43f81f45d24ff144d9ed2",
            "dirty": "staged=1; unstaged=45; untracked=314; conflicts=0; digest=test",
            "captured_at": "2026-07-18 16:20:00",
        }

    def setUp(self):
        super().setUp()
        launcher_patch = patch.object(
            type(self.env["dev.session"]),
            "_pin_enforced_launcher_available",
            autospec=True,
            return_value=True,
        )
        launcher_patch.start()
        self.addCleanup(launcher_patch.stop)
        open_launcher_patch = patch.object(
            type(self.env["dev.session"]),
            "_open_launcher",
            autospec=True,
            return_value={"type": "disabled-launcher-test-double"},
        )
        open_launcher_patch.start()
        self.addCleanup(open_launcher_patch.stop)

    def _session(self, client=None):
        return self.env["dev.session"].create(
            {
                "client_id": (client or self.windows).id,
                "project_id": self.project.id,
                "environment_id": self.environment.id,
                "machine_id": self.machine.id,
                "repository_id": self.repository.id,
                "working_directory": self.repository.working_directory,
                "task_link_id": self.task.id,
            }
        )

    def _mock_snapshot(self, snapshot=None):
        return patch.object(
            type(self.env["dev.session"]),
            "_capture_git_snapshot",
            autospec=True,
            return_value=snapshot or self.snapshot,
        )

    def test_start_manifest_is_sanitized_with_launcher_test_double(self):
        session = self._session()
        with self._mock_snapshot():
            session.action_start()

        self.assertEqual(session.state, "started")
        self.assertEqual(session.git_head_snapshot, self.snapshot["head"])
        self.assertEqual(len(session.event_ids), 1)
        manifest = json.loads(session.manifest_json)
        self.assertEqual(manifest["environment"], "PetSpot Test")
        self.assertEqual(manifest["database"], "pet_spot_elsahel_test")
        self.assertEqual(manifest["port"], 8028)
        self.assertFalse(manifest["production"])
        self.assertFalse(manifest["capabilities"]["deploy_allowed"])
        serialized = session.manifest_json.lower()
        for forbidden in ("password", "private_key", "bearer", "api_key", ".env"):
            self.assertNotIn(forbidden, serialized)

        with self._mock_snapshot():
            session.action_abandon()

    def test_valid_lifecycle_and_events(self):
        session = self._session()
        with self._mock_snapshot():
            session.action_start()
            session.action_mark_in_progress()
            session.action_pause()
            session.write({"client_id": self.ubuntu.id})
            session.action_resume()
            session.action_complete()

        self.assertEqual(session.state, "completed")
        self.assertEqual(session.active_client_id, self.env["dev.client"])
        self.assertEqual(len(session.event_ids), 5)
        self.assertTrue(session.completed_at)
        transitions = set(session.event_ids.mapped("state_transition"))
        self.assertIn("paused → resumed", transitions)
        self.assertIn("resumed → completed", transitions)

    def test_invalid_transition_and_direct_state_write_are_blocked(self):
        session = self._session()
        with self.assertRaises(UserError):
            session.action_complete()
        with self.assertRaises(AccessError):
            session.write({"state": "completed"})

    def test_resume_reports_git_drift_without_fixing_it(self):
        session = self._session()
        with self._mock_snapshot():
            session.action_start()
            session.action_pause()
        changed = dict(self.snapshot)
        changed.update(
            branch="other-branch",
            head="1111111111111111111111111111111111111111",
            dirty="staged=0; unstaged=1; untracked=0; conflicts=0; digest=changed",
        )
        session.write({"client_id": self.ubuntu.id})
        with self._mock_snapshot(changed):
            session.action_resume()

        self.assertIn("branch saved=", session.drift_warning)
        self.assertIn("HEAD saved=", session.drift_warning)
        self.assertIn("dirty-state summary changed", session.drift_warning)
        self.assertEqual(session.git_branch_snapshot, "other-branch")
        with self._mock_snapshot():
            session.action_abandon()

    def test_concurrent_writer_on_same_worktree_is_blocked(self):
        first = self._session()
        second = self._session(client=self.ubuntu)
        with self._mock_snapshot():
            first.action_start()
            with self.assertRaises(UserError):
                second.action_start()
            first.action_abandon()
        self.assertEqual(second.state, "draft")

    def test_duplicate_canonical_worktree_registration_is_blocked(self):
        with self.assertRaises(UniqueViolation):
            self.env["dev.repository"].create(
                {
                    "name": "Duplicate Worktree",
                    "project_id": self.project.id,
                    "git_remote": self.repository.git_remote,
                    "canonical_remote_path": self.repository.canonical_remote_path,
                    "working_directory": self.repository.working_directory,
                    "default_branch": "test-only",
                    "repository_role": "primary",
                }
            )

    def test_production_environment_cannot_launch(self):
        production = self.env["dev.environment"].create(
            {
                "name": "Blocked Production Fixture",
                "project_id": self.project.id,
                "environment_type": "production",
                "machine_id": self.machine.id,
                "database_identifier": "redacted-production-fixture",
                "port": 9999,
                "config_reference": "/unresolved/production.conf",
                "service_container_reference": "unresolved",
                "data_sensitivity": "production",
                "production_guard_policy": "Launch disabled.",
            }
        )
        session = self.env["dev.session"].create(
            {
                "client_id": self.windows.id,
                "project_id": self.project.id,
                "environment_id": production.id,
                "machine_id": self.machine.id,
                "repository_id": self.repository.id,
                "working_directory": self.repository.working_directory,
            }
        )
        with self.assertRaises(UserError):
            session.action_start()
        self.assertEqual(session.state, "draft")

    def test_production_bearing_machine_cannot_launch(self):
        environment = self.env["dev.environment"].create(
            {
                "name": "Production-bearing Machine Fixture",
                "project_id": self.project.id,
                "environment_type": "test",
                "machine_id": self.production_machine.id,
                "database_identifier": "nonproduction-fixture",
                "port": 9998,
                "config_reference": "/unresolved/test.conf",
                "service_container_reference": "unresolved",
                "data_sensitivity": "internal_test",
                "production_guard_policy": "Launch disabled on production host.",
            }
        )
        self.env["dev.policy"].create(
            {
                "name": "Mixed host non-production fallback policy",
                "project_id": self.project.id,
                "environment_id": environment.id,
                "production_access_policy": "denied",
                "allowed_operations": "Open registered test workspace",
                "branch_rules": "No automatic mutation",
                "development_allowed": True,
                "launch_allowed": True,
                "deploy_permission": False,
            }
        )
        session = self.env["dev.session"].create(
            {
                "client_id": self.windows.id,
                "project_id": self.project.id,
                "environment_id": environment.id,
                "machine_id": self.production_machine.id,
                "repository_id": self.repository.id,
                "working_directory": self.repository.working_directory,
            }
        )
        with self.assertRaises(UserError), self._mock_snapshot():
            session.action_start()
        self.assertEqual(session.state, "draft")

    def test_explicit_workspace_fallback_does_not_require_managed_helper(self):
        session = self._session()
        with patch.object(
            type(self.env["dev.session"]),
            "_pin_enforced_launcher_available",
            return_value=False,
        ), self._mock_snapshot():
            session.action_start()
            self.assertFalse(session._pin_enforced_launcher_available())
        self.assertEqual(session.state, "started")

    def test_exact_canonical_path_binding_rejects_substitution(self):
        session = self._session()
        with self.assertRaises(ValidationError):
            session.working_directory = (
                self.repository.working_directory + "-substitute"
            )
        self.assertEqual(session.state, "draft")

    def test_git_subprocess_has_fixed_environment_and_safe_options(self):
        completed = Mock(stdout="clean\n")
        with patch(
            "odoo.addons.dev_session_hub.models.dev_session.subprocess.run",
            return_value=completed,
        ) as run:
            output = self.env["dev.session"]._run_git("/tmp", "status")
        self.assertEqual(output, "clean")
        command = run.call_args.args[0]
        self.assertEqual(command[0], "/usr/bin/git")
        self.assertIn("core.fsmonitor=false", command)
        self.assertIn("core.hooksPath=/dev/null", command)
        self.assertEqual(run.call_args.kwargs["env"]["HOME"], "/nonexistent")
        self.assertNotIn("GIT_CONFIG_COUNT", run.call_args.kwargs["env"])

    def test_git_repository_identity_must_match_registry(self):
        session = self._session()
        path = self.repository.working_directory
        with patch.object(
            type(self.env["dev.session"]),
            "_run_git",
            autospec=True,
            side_effect=[
                path,
                path + "/.git",
                "https://attacker.invalid/replaced.git",
            ],
        ):
            with self.assertRaises(UserError):
                session._capture_git_snapshot()

    def test_project_membership_blocks_registry_and_session_targets(self):
        outsider_env = self.env["dev.environment"].with_user(self.outsider)
        self.assertFalse(outsider_env.search([("id", "=", self.environment.id)]))
        with self.assertRaises(AccessError):
            self.env["dev.session"].with_user(self.outsider).create(
                {
                    "client_id": self.windows.id,
                    "project_id": self.project.id,
                    "environment_id": self.environment.id,
                    "machine_id": self.machine.id,
                    "repository_id": self.repository.id,
                    "working_directory": self.repository.working_directory,
                }
            )
        member_session = self.env["dev.session"].with_user(self.dev_user).create(
            {
                "client_id": self.windows.id,
                "project_id": self.project.id,
                "environment_id": self.environment.id,
                "machine_id": self.machine.id,
                "repository_id": self.repository.id,
                "working_directory": self.repository.working_directory,
            }
        )
        self.assertEqual(member_session.user_id, self.dev_user)

    def test_exact_policy_precedes_generic_and_scope_is_unique(self):
        generic = self.env["dev.policy"].create(
            {
                "name": "Generic deny fallback",
                "project_id": self.project.id,
                "production_access_policy": "denied",
                "allowed_operations": "None",
                "branch_rules": "No mutation",
                "development_allowed": False,
                "launch_allowed": False,
            }
        )
        session = self._session()
        self.assertEqual(session._policy(), self.env.ref("dev_session_hub.dev_policy_petspot_test"))
        self.env.ref("dev_session_hub.dev_policy_petspot_test").active = False
        self.assertEqual(session._policy(), generic)
        with self.assertRaises(ValidationError):
            self.env["dev.policy"].create(
                {
                    "name": "Duplicate generic",
                    "project_id": self.project.id,
                    "production_access_policy": "denied",
                    "allowed_operations": "None",
                    "branch_rules": "No mutation",
                }
            )

    def test_launcher_fallback_is_structured_and_forgery_is_rejected(self):
        session = self._session()
        with self._mock_snapshot():
            session.action_start()
        with self.assertRaises(AccessError):
            self.env["dev.launch.wizard"].create(
                {
                    "session_id": session.id,
                    "command_linux": "touch /tmp/forged",
                }
            )
        with self.assertRaises(AccessError):
            self.env["dev.launch.wizard"].create({"session_id": session.id})
        wizard = self.env["dev.launch.wizard"].create_from_session(session)
        workspace = json.loads(base64.b64decode(wizard.workspace_file))
        self.assertEqual(len(workspace["folders"]), 1)
        self.assertIn("vscode-remote://ssh-remote+", workspace["folders"][0]["uri"])
        self.assertNotIn("touch ", wizard.command_linux)
        self.assertIn("managed one-click helper remains disabled", wizard.safety_note)
        self.assertEqual(wizard.action_download_workspace()["type"], "ir.actions.act_url")
        with self._mock_snapshot():
            session.action_abandon()

    def test_terminal_transitions_survive_snapshot_failure(self):
        session = self._session()
        with self._mock_snapshot():
            session.action_start()
        with patch.object(
            type(self.env["dev.session"]),
            "_capture_git_snapshot",
            autospec=True,
            side_effect=UserError("unavailable target"),
        ):
            session.action_mark_in_progress()
            session.action_complete()
        self.assertEqual(session.state, "completed")
        self.assertIn("Git snapshot unavailable", session.event_ids[0].git_snapshot)

    def test_hostile_manifest_strings_are_sanitized(self):
        session = self._session()
        session.write({"name": "bad$(touch /tmp/x)\n`cmd`"})
        self.task.cached_task_title = "hostile\n$(cmd) \"quoted\""
        with self._mock_snapshot():
            session.action_start()
        serialized = session.manifest_json
        for hostile in ("$", "`", "\n$(cmd)", '"quoted"'):
            self.assertNotIn(hostile, serialized)
        with self._mock_snapshot():
            session.action_abandon()

    def test_manifest_redacts_colon_and_json_style_credentials(self):
        for value in (
            "password: exposed",
            '"token": "exposed"',
            "secret : exposed",
            '"api_key": "exposed"',
            "Authorization=Basic exposed",
            "pwd=exposed",
            "postgresql://user:password@host/database",
            "-----BEGIN OPENSSH PRIVATE KEY-----",
            "-----BEGIN ENCRYPTED PRIVATE KEY-----",
        ):
            self.assertEqual(
                self.env["dev.session"]._sanitize_manifest_value(value),
                "[redacted]",
            )

    def test_event_is_append_only(self):
        session = self._session()
        with self._mock_snapshot():
            session.action_start()
        event = session.event_ids.sudo()
        with self.assertRaises(AccessError):
            event.write({"reason": "tampered"})
        with self.assertRaises(AccessError):
            event.unlink()
        with self._mock_snapshot():
            session.action_abandon()

    def test_sensitive_note_is_rejected(self):
        with self.assertRaises(ValidationError):
            self._session().write({"last_note": "token=do-not-store"})
