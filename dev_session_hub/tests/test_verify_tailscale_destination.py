# -*- coding: utf-8 -*-
import json
import os
import socket
import tempfile
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged

from odoo.addons.dev_session_hub.models import dev_machine_verification as verify_mod
from odoo.addons.dev_session_hub.tests.common import (
    ensure_dev_hub_safe_policy,
    find_dev_policy,
    snapshot_dev_policy,
)


PIN = "SHA256:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
FQDN = "dev-target.tailcf9988.ts.net"
IP = "100.64.0.99"


@tagged("post_install", "-at_install")
class TestVerifyTailscaleDestination(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = cls.env.ref("dev_session_hub.dev_project_petspot")
        cls.repository = cls.env.ref("dev_session_hub.dev_repository_petspot")
        cls.environment = cls.env.ref("dev_session_hub.dev_environment_petspot_test")
        cls.windows = cls.env.ref("dev_session_hub.dev_client_windows_desktop")
        cls.manager = cls.env.ref("base.user_admin")
        cls.ordinary = (
            cls.env["res.users"]
            .with_context(no_reset_password=True)
            .create(
                {
                    "name": "Verify Ordinary User",
                    "login": "devhub-verify-ordinary",
                    "group_ids": [
                        (
                            6,
                            0,
                            [cls.env.ref("dev_session_hub.group_dev_hub_user").id],
                        )
                    ],
                }
            )
        )
        cls.project.member_ids = [(4, cls.ordinary.id)]

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
        self.machine = self.env["dev.machine"].create(
            {
                "name": "Verify Target",
                "hostname": "verify-host",
                "tailscale_name": FQDN,
                "tailscale_ip_reference": IP,
                "tailscale_destination_verified": False,
                "pinned_host_key_fingerprint": PIN,
                "ssh_alias": "verify-target-ts",
                "role": "verification-test",
                "trust_zone": "trusted_dev",
                "production": False,
                "allowed_path_prefixes": self.repository.working_directory,
            }
        )
        self.environment.machine_id = self.machine
        self._policy = find_dev_policy(self.env, self.project, self.environment)
        self._original_policy = snapshot_dev_policy(self._policy)
        ensure_dev_hub_safe_policy(self._policy)
        self.addCleanup(lambda: self._policy.write(self._original_policy))

    def _manager_machine(self):
        return self.machine.with_user(self.manager)

    def _patch_success_stack(self):
        patches = [
            patch.object(
                type(self.machine),
                "_ssh_resolve_alias",
                return_value={"hostname": FQDN, "user": "sabry3"},
            ),
            patch.object(
                type(self.machine),
                "_assert_tailscale_peer_current",
                return_value=None,
            ),
            patch.object(
                type(self.machine),
                "_observe_ed25519_fingerprint",
                return_value=(f"{FQDN} ssh-ed25519 AAAATEST", PIN),
            ),
            patch.object(
                type(self.machine),
                "_ssh_strict_hostname_probe",
                return_value="verify-host",
            ),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def test_authorized_success_sets_verified_and_timestamp(self):
        self._patch_success_stack()
        before = fields.Datetime.now()
        self._manager_machine().action_verify_tailscale_destination()
        self.machine.invalidate_recordset()
        self.assertTrue(self.machine.tailscale_destination_verified)
        self.assertTrue(self.machine.tailscale_verified_at)
        self.assertGreaterEqual(self.machine.tailscale_verified_at, before)
        self.assertEqual(self.machine.last_reachability_status, "reachable")
        events = self.env["dev.machine.verification.event"].search(
            [("machine_id", "=", self.machine.id), ("success", "=", True)]
        )
        self.assertTrue(events)
        self.assertEqual(events[0].reason_code, "verified")
        self.assertEqual(events[0].fingerprint_ref, PIN)

    def test_ordinary_user_denied_server_side(self):
        with self.assertRaises(AccessError):
            self.machine.with_user(self.ordinary).action_verify_tailscale_destination()
        self.assertFalse(self.machine.tailscale_destination_verified)
        self.assertFalse(self.machine.tailscale_verified_at)

    def test_production_refused(self):
        self.machine.production = True
        with self.assertRaises(UserError) as err:
            self._manager_machine().action_verify_tailscale_destination()
        self.assertIn("Production-bearing", str(err.exception))
        self.assertFalse(self.machine.tailscale_verified_at)

    def test_inactive_refused(self):
        self.machine.active = False
        with self.assertRaises(UserError):
            self._manager_machine().action_verify_tailscale_destination()
        self.assertFalse(self.machine.tailscale_verified_at)

    def test_wrong_trust_zone_refused(self):
        self.machine.trust_zone = "restricted"
        with self.assertRaises(UserError):
            self._manager_machine().action_verify_tailscale_destination()

    def test_invalid_ssh_alias_refused(self):
        bad = self.env["dev.machine"].create(
            {
                "name": "Bad Alias",
                "hostname": "verify-host",
                "tailscale_name": FQDN,
                "tailscale_ip_reference": IP,
                "pinned_host_key_fingerprint": PIN,
                "ssh_alias": "bad;alias",
                "role": "verification-test",
                "trust_zone": "trusted_dev",
                "production": False,
                "allowed_path_prefixes": self.repository.working_directory,
            }
        )
        with self.assertRaises(UserError) as err:
            bad.with_user(self.manager).action_verify_tailscale_destination()
        self.assertIn("SSH alias", str(err.exception))

    def test_non_ts_net_destination_refused(self):
        short = self.env["dev.machine"].create(
            {
                "name": "Short Name Like Machine 77",
                "hostname": "sabry3-Precision-5540",
                "tailscale_name": "sabry3-Precision-5540",
                "tailscale_ip_reference": IP,
                "pinned_host_key_fingerprint": PIN,
                "ssh_alias": "short-name-ts",
                "role": "verification-test",
                "trust_zone": "trusted_dev",
                "production": False,
                "allowed_path_prefixes": self.repository.working_directory,
            }
        )
        with self.assertRaises(UserError) as err:
            short.with_user(self.manager).action_verify_tailscale_destination()
        self.assertIn(".ts.net", str(err.exception))
        self.assertFalse(short.tailscale_verified_at)

    def test_missing_tailscale_ip_refused(self):
        self.machine.tailscale_ip_reference = False
        with self.assertRaises(UserError):
            self._manager_machine().action_verify_tailscale_destination()

    def test_malformed_fingerprint_refused(self):
        self.machine.pinned_host_key_fingerprint = "not-a-fingerprint"
        with self.assertRaises(UserError):
            self._manager_machine().action_verify_tailscale_destination()

    def test_host_key_failure_no_timestamp(self):
        with patch.object(
            type(self.machine),
            "_ssh_resolve_alias",
            return_value={"hostname": FQDN},
        ), patch.object(
            type(self.machine), "_assert_tailscale_peer_current"
        ), patch.object(
            type(self.machine),
            "_observe_ed25519_fingerprint",
            side_effect=lambda *_a, **_k: self.machine._raise_with_reason("host_key"),
        ):
            with self.assertRaises(UserError):
                self._manager_machine().action_verify_tailscale_destination()
        self.assertFalse(self.machine.tailscale_verified_at)
        self.assertFalse(self.machine.tailscale_destination_verified)

    def test_fingerprint_mismatch_no_timestamp(self):
        with patch.object(
            type(self.machine),
            "_ssh_resolve_alias",
            return_value={"hostname": FQDN},
        ), patch.object(
            type(self.machine), "_assert_tailscale_peer_current"
        ), patch.object(
            type(self.machine),
            "_observe_ed25519_fingerprint",
            return_value=(
                f"{FQDN} ssh-ed25519 AAAATEST",
                "SHA256:BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB",
            ),
        ):
            with self.assertRaises(UserError) as err:
                self._manager_machine().action_verify_tailscale_destination()
        self.assertIn("fingerprint", str(err.exception).lower())
        self.assertFalse(self.machine.tailscale_verified_at)

    def test_hostname_mismatch_no_timestamp(self):
        with patch.object(
            type(self.machine),
            "_ssh_resolve_alias",
            return_value={"hostname": FQDN},
        ), patch.object(
            type(self.machine), "_assert_tailscale_peer_current"
        ), patch.object(
            type(self.machine),
            "_observe_ed25519_fingerprint",
            return_value=(f"{FQDN} ssh-ed25519 AAAATEST", PIN),
        ), patch.object(
            type(self.machine),
            "_ssh_strict_hostname_probe",
            return_value="other-host",
        ):
            with self.assertRaises(UserError):
                self._manager_machine().action_verify_tailscale_destination()
        self.assertFalse(self.machine.tailscale_verified_at)

    def test_tailscale_destination_mismatch_no_timestamp(self):
        with patch.object(
            type(self.machine),
            "_ssh_resolve_alias",
            return_value={"hostname": FQDN},
        ), patch.object(
            type(self.machine),
            "_assert_tailscale_peer_current",
            side_effect=lambda *_a, **_k: self.machine._raise_with_reason(
                "tailscale_mismatch"
            ),
        ):
            with self.assertRaises(UserError):
                self._manager_machine().action_verify_tailscale_destination()
        self.assertFalse(self.machine.tailscale_verified_at)

    def test_timeout_fails_closed(self):
        with patch.object(
            type(self.machine),
            "_ssh_resolve_alias",
            side_effect=lambda *_a, **_k: self.machine._raise_with_reason("timeout"),
        ):
            with self.assertRaises(UserError) as err:
                self._manager_machine().action_verify_tailscale_destination()
        self.assertIn("timed out", str(err.exception).lower())
        self.assertFalse(self.machine.tailscale_verified_at)

    def test_nonzero_ssh_return_fails_closed(self):
        with patch.object(
            type(self.machine),
            "_run_allowlisted",
            return_value=(1, "", "denied"),
        ):
            with self.assertRaises(UserError):
                self._manager_machine().action_verify_tailscale_destination()
        self.assertFalse(self.machine.tailscale_verified_at)

    def test_subprocess_never_shell_true(self):
        calls = []

        def fake_run(*args, **kwargs):
            calls.append(kwargs)
            raise verify_mod.subprocess.TimeoutExpired(cmd=args[0], timeout=1)

        with patch.object(verify_mod.subprocess, "run", side_effect=fake_run):
            with self.assertRaises(UserError):
                self._manager_machine().action_verify_tailscale_destination()
        self.assertTrue(calls)
        for kwargs in calls:
            self.assertIs(kwargs.get("shell"), False)

    def test_run_allowlisted_uses_argument_list(self):
        seen = []

        def fake_run(cmd, **kwargs):
            seen.append(cmd)

            class Result:
                returncode = 0
                stdout = "hostname verify-target-ts\n"
                stderr = ""

            return Result()

        with patch.object(verify_mod.subprocess, "run", side_effect=fake_run):
            code, _out, _err = self.machine._run_allowlisted(
                verify_mod.SSH_EXECUTABLE, ["-G", "verify-target-ts"], timeout=5
            )
            self.assertEqual(code, 0)
        self.assertEqual(seen[0][0], verify_mod.SSH_EXECUTABLE)
        self.assertIsInstance(seen[0], list)

    def test_no_arbitrary_remote_command_injection(self):
        self.assertEqual(verify_mod.REMOTE_HOSTNAME_ARGV, ("hostname",))
        with patch.object(
            type(self.machine),
            "_ssh_resolve_alias",
            return_value={"hostname": FQDN},
        ), patch.object(
            type(self.machine), "_assert_tailscale_peer_current"
        ), patch.object(
            type(self.machine),
            "_observe_ed25519_fingerprint",
            return_value=(f"{FQDN} ssh-ed25519 AAAATEST", PIN),
        ):
            captured = []

            def fake_run(executable, argv_tail, timeout, env=None):
                captured.append((executable, list(argv_tail)))
                if executable == verify_mod.SSH_EXECUTABLE and "hostname" in argv_tail:
                    return 0, "verify-host\n", ""
                return 0, "", ""

            with patch.object(type(self.machine), "_run_allowlisted", side_effect=fake_run):
                self._manager_machine().action_verify_tailscale_destination()
        remote_calls = [
            argv for exe, argv in captured if exe == verify_mod.SSH_EXECUTABLE and "hostname" in argv
        ]
        self.assertTrue(remote_calls)
        for argv in remote_calls:
            self.assertEqual(argv[-1], "hostname")
            self.assertNotIn(";", "".join(argv))
            self.assertNotIn("&&", "".join(argv))

    def test_identity_field_change_invalidates_verification(self):
        self._patch_success_stack()
        self._manager_machine().action_verify_tailscale_destination()
        self.assertTrue(self.machine.tailscale_destination_verified)
        self.machine.hostname = "changed-host"
        self.assertFalse(self.machine.tailscale_destination_verified)
        self.assertFalse(self.machine.tailscale_verified_at)

    def test_unrelated_field_preserves_verification(self):
        self._patch_success_stack()
        self._manager_machine().action_verify_tailscale_destination()
        stamp = self.machine.tailscale_verified_at
        self.machine.os_name = "Ubuntu Test"
        self.assertTrue(self.machine.tailscale_destination_verified)
        self.assertEqual(self.machine.tailscale_verified_at, stamp)

    def test_allowed_paths_change_preserves_verification(self):
        self._patch_success_stack()
        self._manager_machine().action_verify_tailscale_destination()
        stamp = self.machine.tailscale_verified_at
        self.machine.allowed_path_prefixes = self.repository.working_directory
        self.assertEqual(self.machine.tailscale_verified_at, stamp)

    def test_failure_writes_sanitized_audit(self):
        self.machine.production = True
        self.machine.flush_recordset()
        try:
            self._manager_machine().action_verify_tailscale_destination()
        except UserError:
            pass
        else:
            self.fail("expected UserError for production machine")
        self.env.invalidate_all()
        event = (
            self.env["dev.machine.verification.event"]
            .sudo()
            .search(
                [
                    ("machine_id", "=", self.machine.id),
                    ("reason_code", "=", "production"),
                ],
                limit=1,
            )
        )
        self.assertTrue(
            event,
            "eligibility failure must leave a sanitized audit row",
        )
        self.assertFalse(event.success)
        self.assertEqual(event.fingerprint_ref, PIN)
        self.assertNotIn("secret", (event.destination_ref or "").lower())

    def test_direct_verified_at_write_blocked(self):
        with self.assertRaises(AccessError):
            self.machine.tailscale_verified_at = fields.Datetime.now()

    def test_launch_still_fails_when_verified_at_missing(self):
        self.machine.hostname = socket.gethostname()
        self.assertFalse(self.machine.tailscale_destination_verified)
        self.assertFalse(self.machine.tailscale_verified_at)
        session = self.env["dev.session"].create(
            {
                "client_id": self.windows.id,
                "project_id": self.project.id,
                "environment_id": self.environment.id,
                "machine_id": self.machine.id,
                "repository_id": self.repository.id,
                "working_directory": self.repository.working_directory,
            }
        )
        with patch.object(
            type(session),
            "_capture_git_snapshot",
            return_value={
                "branch": "staging",
                "head": "b" * 40,
                "dirty": "clean",
                "captured_at": fields.Datetime.now(),
            },
        ):
            with self.assertRaises(UserError) as err:
                session.action_start()
        self.assertIn("verified Tailscale", str(err.exception))

    def test_launch_passes_timestamp_gate_after_verified_workflow(self):
        local_host = socket.gethostname()
        self.machine.hostname = local_host
        with patch.object(
            type(self.machine),
            "_ssh_resolve_alias",
            return_value={"hostname": FQDN},
        ), patch.object(
            type(self.machine), "_assert_tailscale_peer_current"
        ), patch.object(
            type(self.machine),
            "_observe_ed25519_fingerprint",
            return_value=(f"{FQDN} ssh-ed25519 AAAATEST", PIN),
        ), patch.object(
            type(self.machine),
            "_ssh_strict_hostname_probe",
            return_value=local_host,
        ):
            self._manager_machine().action_verify_tailscale_destination()
        self.assertTrue(self.machine.tailscale_verified_at)
        session = self.env["dev.session"].create(
            {
                "client_id": self.windows.id,
                "project_id": self.project.id,
                "environment_id": self.environment.id,
                "machine_id": self.machine.id,
                "repository_id": self.repository.id,
                "working_directory": self.repository.working_directory,
            }
        )
        with patch.object(
            type(session),
            "_capture_git_snapshot",
            return_value={
                "branch": "staging",
                "head": "b" * 40,
                "dirty": "clean",
                "captured_at": fields.Datetime.now(),
            },
        ):
            session.action_start()
        self.assertEqual(session.state, "started")

    def test_output_sanitized_in_user_errors(self):
        with patch.object(
            type(self.machine),
            "_run_allowlisted",
            return_value=(1, "secret-token-value\n", "key-/home/sabry/.ssh/id"),
        ):
            with self.assertRaises(UserError) as err:
                self._manager_machine().action_verify_tailscale_destination()
        message = str(err.exception)
        self.assertNotIn("secret-token", message)
        self.assertNotIn(".ssh/id", message)

    def test_forged_context_cannot_set_verification_fields(self):
        with self.assertRaises(AccessError):
            self.machine.with_context(dev_machine_verification_write=True).write(
                {
                    "tailscale_destination_verified": True,
                    "tailscale_verified_at": fields.Datetime.now(),
                }
            )
        self.assertFalse(self.machine.tailscale_destination_verified)
        self.assertFalse(self.machine.tailscale_verified_at)

    def test_dangerous_ssh_proxycommand_rejected(self):
        with self.assertRaises(UserError) as err:
            self.machine._assert_ssh_config_safe(
                {"hostname": FQDN, "proxycommand": "nc evil 22"}
            )
        self.assertIn("unsafe", str(err.exception).lower())

    def test_dangerous_ssh_localcommand_rejected(self):
        with self.assertRaises(UserError):
            self.machine._assert_ssh_config_safe(
                {
                    "hostname": FQDN,
                    "permitlocalcommand": "yes",
                    "localcommand": "touch /tmp/pwned",
                }
            )

    def test_dangerous_ssh_forwarding_rejected(self):
        with self.assertRaises(UserError):
            self.machine._assert_ssh_config_safe(
                {"hostname": FQDN, "localforward": "8080 localhost:80"}
            )
        with self.assertRaises(UserError):
            self.machine._assert_ssh_config_safe(
                {"hostname": FQDN, "forwardagent": "yes"}
            )

    def test_ambiguous_tailscale_peers_fail_closed(self):
        payload = {
            "Peer": {
                "a": {
                    "DNSName": FQDN + ".",
                    "HostName": "a",
                    "TailscaleIPs": [IP],
                    "Online": True,
                },
                "b": {
                    "DNSName": FQDN + ".",
                    "HostName": "b",
                    "TailscaleIPs": [IP],
                    "Online": True,
                },
            }
        }
        with patch.object(
            type(self.machine),
            "_run_allowlisted",
            return_value=(0, json.dumps(payload), ""),
        ):
            with self.assertRaises(UserError) as err:
                self.machine._assert_tailscale_peer_current(FQDN, IP)
        self.assertIn("Multiple", str(err.exception))

    def test_fqdn_trailing_dot_and_case_normalization(self):
        payload = {
            "Peer": {
                "a": {
                    "DNSName": "DEV-TARGET.TAILCF9988.TS.NET.",
                    "HostName": "dev-target",
                    "TailscaleIPs": [IP],
                    "Online": True,
                }
            }
        }
        with patch.object(
            type(self.machine),
            "_run_allowlisted",
            return_value=(0, json.dumps(payload), ""),
        ):
            self.machine._assert_tailscale_peer_current(FQDN, IP)

    def test_temp_known_hosts_mode_0600(self):
        import os
        import stat
        import tempfile

        from odoo.addons.dev_session_hub.models.dev_machine_verification import (
            _write_private_mode_0600,
        )

        directory = tempfile.mkdtemp(prefix="devhub-kh-test-")
        path = os.path.join(directory, "known_hosts")
        try:
            _write_private_mode_0600(path, "host ssh-ed25519 AAAATEST\n")
            mode = stat.S_IMODE(os.stat(path).st_mode)
            self.assertEqual(mode, 0o600)
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
            os.rmdir(directory)

    def test_temp_known_hosts_cleanup_on_ssh_failure(self):
        leftover = []
        real_mkdtemp = tempfile.mkdtemp

        def fake_mkdtemp(prefix="devhub-kh-"):
            path = real_mkdtemp(prefix=prefix)
            leftover.append(path)
            return path

        with patch.object(
            type(self.machine),
            "_ssh_resolve_alias",
            return_value={"hostname": FQDN, "proxycommand": "none"},
        ), patch.object(
            type(self.machine), "_assert_ssh_config_safe"
        ), patch.object(
            type(self.machine), "_assert_tailscale_peer_current"
        ), patch.object(
            type(self.machine),
            "_observe_ed25519_fingerprint",
            return_value=(f"{FQDN} ssh-ed25519 AAAATEST", PIN),
        ), patch(
            "odoo.addons.dev_session_hub.models.dev_machine_verification.tempfile.mkdtemp",
            side_effect=fake_mkdtemp,
        ), patch.object(
            type(self.machine),
            "_run_allowlisted",
            return_value=(1, "", "denied"),
        ):
            with self.assertRaises(UserError):
                self._manager_machine().action_verify_tailscale_destination()
        for path in leftover:
            self.assertFalse(os.path.isdir(path), path)

    def test_audit_events_immutable(self):
        self._patch_success_stack()
        self._manager_machine().action_verify_tailscale_destination()
        event = self.env["dev.machine.verification.event"].search(
            [("machine_id", "=", self.machine.id)], limit=1
        )
        with self.assertRaises(AccessError):
            event.write({"reason_code": "tampered"})
        with self.assertRaises(AccessError):
            event.unlink()

    def test_failed_verification_leaves_prior_verified_state(self):
        self._patch_success_stack()
        self._manager_machine().action_verify_tailscale_destination()
        stamp = self.machine.tailscale_verified_at
        with patch.object(
            type(self.machine),
            "_ssh_resolve_alias",
            side_effect=lambda *_a, **_k: self.machine._raise_with_reason("ssh_failed"),
        ):
            with self.assertRaises(UserError):
                self._manager_machine().action_verify_tailscale_destination()
        self.assertTrue(self.machine.tailscale_destination_verified)
        self.assertEqual(self.machine.tailscale_verified_at, stamp)

