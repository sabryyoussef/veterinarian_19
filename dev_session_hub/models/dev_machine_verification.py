# -*- coding: utf-8 -*-
"""Active Tailscale / SSH destination verification for ``dev.machine``."""

from __future__ import annotations

import ipaddress
import json
import os
import re
import subprocess
import tempfile
import uuid
from pathlib import Path

from odoo import fields, models
from odoo.exceptions import AccessError, UserError

from .dev_registry import HOST_KEY_FINGERPRINT, TAILSCALE_DNS_NAME

SSH_EXECUTABLE = "/usr/bin/ssh"
SSH_KEYSCAN_EXECUTABLE = "/usr/bin/ssh-keyscan"
SSH_KEYGEN_EXECUTABLE = "/usr/bin/ssh-keygen"
TAILSCALE_EXECUTABLE = "/usr/bin/tailscale"

SSH_ALIAS_SAFE = re.compile(r"^[A-Za-z0-9._-]+$")
HOSTNAME_SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,253}$")
# Tailscale CGNAT 100.64.0.0/10
TAILSCALE_IPV4 = re.compile(
    r"^100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.(?:\d{1,3})\.(?:\d{1,3})$"
)

IDENTITY_INVALIDATION_FIELDS = frozenset(
    {
        "hostname",
        "ssh_alias",
        "tailscale_name",
        "tailscale_ip_reference",
        "pinned_host_key_fingerprint",
    }
)
VERIFICATION_STATE_FIELDS = frozenset(
    {
        "tailscale_destination_verified",
        "tailscale_verified_at",
    }
)

SSH_CONNECT_TIMEOUT = 8
SUBPROCESS_TIMEOUT = 15
KEYSCAN_TIMEOUT = 10
OUTPUT_BYTE_LIMIT = 1024 * 1024

# Fixed remote identity probe — never accept caller-supplied commands.
REMOTE_HOSTNAME_ARGV = ("hostname",)

REASON_MESSAGES = {
    "not_manager": "Only Dev Hub managers may verify Tailscale destinations.",
    "multi_record": "Verify exactly one machine at a time.",
    "inactive": "Inactive machines cannot be verified.",
    "production": "Production-bearing machines cannot be verified for launch.",
    "trust_zone": "Verification requires trust zone trusted_dev.",
    "ssh_alias": "The SSH alias is missing or not allowlisted.",
    "tailscale_fqdn": (
        "The Tailscale name must be a canonical DNS name ending in .ts.net. "
        "Correct the field before verifying; it is not rewritten automatically."
    ),
    "tailscale_ip": "A valid Tailscale IP reference (100.64.0.0/10) is required.",
    "fingerprint": "A pinned SHA256 SSH host-key fingerprint is required.",
    "paths": "Allowed path prefixes must already be valid.",
    "alias_resolve": "The SSH alias does not resolve to the registered Tailscale destination.",
    "tailscale_offline": "The Tailscale destination is not currently online.",
    "tailscale_mismatch": "Tailscale status does not match the registered destination.",
    "host_key": "Strict host-key verification failed.",
    "fingerprint_mismatch": "Observed host-key fingerprint does not match the pin.",
    "hostname_mismatch": "Remote hostname does not match the registered machine hostname.",
    "ssh_failed": "SSH identity check failed.",
    "timeout": "Verification timed out.",
    "tooling": "Required local verification tooling is unavailable.",
    "output": "Remote identity output was empty or unsafe.",
}


def _sanitize_text(value, limit=200):
    text = re.sub(r"[\x00-\x1f\x7f]", "", str(value or "")).strip()
    return text[:limit]


def _is_tailscale_ipv4(value):
    if not TAILSCALE_IPV4.fullmatch(value or ""):
        return False
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return address in ipaddress.ip_network("100.64.0.0/10")


class DevMachineVerificationEvent(models.Model):
    _name = "dev.machine.verification.event"
    _description = "Machine Tailscale Verification Audit Event"
    _order = "timestamp desc, id desc"

    machine_id = fields.Many2one(
        "dev.machine", required=True, ondelete="restrict", index=True, readonly=True
    )
    actor_id = fields.Many2one(
        "res.users", required=True, ondelete="restrict", readonly=True
    )
    timestamp = fields.Datetime(required=True, readonly=True, index=True)
    success = fields.Boolean(required=True, readonly=True)
    reason_code = fields.Char(required=True, readonly=True)
    destination_ref = fields.Char(readonly=True)
    fingerprint_ref = fields.Char(readonly=True)
    correlation_id = fields.Char(required=True, readonly=True, index=True)
    dry_run = fields.Boolean(readonly=True)

    def write(self, vals):
        raise AccessError("Machine verification events are immutable.")

    def unlink(self):
        raise AccessError("Machine verification events are immutable.")


class DevMachine(models.Model):
    _inherit = "dev.machine"

    verification_event_ids = fields.One2many(
        "dev.machine.verification.event",
        "machine_id",
        string="Verification Audit Events",
        readonly=True,
    )

    def write(self, vals):
        vals = dict(vals)
        if VERIFICATION_STATE_FIELDS.intersection(vals) and not self.env.context.get(
            "dev_machine_verification_write"
        ):
            raise AccessError(
                "Verification state changes only through Verify Tailscale Destination."
            )
        if IDENTITY_INVALIDATION_FIELDS.intersection(vals):
            vals["tailscale_destination_verified"] = False
            vals["tailscale_verified_at"] = False
            return super(
                DevMachine, self.with_context(dev_machine_verification_write=True)
            ).write(vals)
        return super().write(vals)

    def action_verify_tailscale_destination(self, dry_run=False):
        """Actively verify the registered Tailscale/SSH destination."""
        if not self.env.user.has_group("dev_session_hub.group_dev_hub_manager"):
            self._audit_verification(
                success=False,
                reason_code="not_manager",
                dry_run=dry_run,
                raise_access=True,
            )
        if len(self) != 1:
            raise UserError(REASON_MESSAGES["multi_record"])
        self.ensure_one()

        reason = self._verification_eligibility_reason()
        if reason:
            self._record_verification_outcome(
                success=False, reason_code=reason, dry_run=dry_run
            )
            raise UserError(REASON_MESSAGES[reason])

        try:
            self._perform_active_verification()
        except UserError as exc:
            reason_code = getattr(exc, "reason_code", None)
            if reason_code not in REASON_MESSAGES:
                message = exc.args[0] if exc.args else ""
                reason_code = next(
                    (
                        key
                        for key, value in REASON_MESSAGES.items()
                        if value == message
                    ),
                    "ssh_failed",
                )
            self._record_verification_outcome(
                success=False,
                reason_code=reason_code,
                dry_run=dry_run,
                mark_unreachable=True,
            )
            raise UserError(REASON_MESSAGES.get(reason_code, REASON_MESSAGES["ssh_failed"])) from None
        except subprocess.TimeoutExpired:
            self._record_verification_outcome(
                success=False,
                reason_code="timeout",
                dry_run=dry_run,
                mark_unreachable=True,
            )
            raise UserError(REASON_MESSAGES["timeout"]) from None

        if dry_run:
            self._record_verification_outcome(
                success=True, reason_code="dry_run_ok", dry_run=True
            )
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": "Dry-run verification succeeded",
                    "message": (
                        "Active checks passed. Verification state was not written."
                    ),
                    "type": "success",
                    "sticky": False,
                },
            }

        now = fields.Datetime.now()
        self.with_context(dev_machine_verification_write=True).write(
            {
                "tailscale_destination_verified": True,
                "tailscale_verified_at": now,
                "last_reachability_status": "reachable",
                "last_checked_at": now,
            }
        )
        self._record_verification_outcome(
            success=True, reason_code="verified", dry_run=False
        )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Tailscale destination verified",
                "message": "Active SSH and Tailscale identity checks passed.",
                "type": "success",
                "sticky": False,
            },
        }

    def _verification_eligibility_reason(self):
        self.ensure_one()
        if not self.active:
            return "inactive"
        if self.production:
            return "production"
        if self.trust_zone != "trusted_dev":
            return "trust_zone"
        if not SSH_ALIAS_SAFE.fullmatch(self.ssh_alias or ""):
            return "ssh_alias"
        if not TAILSCALE_DNS_NAME.fullmatch(self.tailscale_name or ""):
            return "tailscale_fqdn"
        if not _is_tailscale_ipv4(self.tailscale_ip_reference or ""):
            return "tailscale_ip"
        if not HOST_KEY_FINGERPRINT.fullmatch(self.pinned_host_key_fingerprint or ""):
            return "fingerprint"
        try:
            self._check_allowed_paths()
        except Exception:
            return "paths"
        return None

    def _perform_active_verification(self):
        """Run network identity checks. Raises UserError with a sanitized message."""
        self.ensure_one()
        alias = self.ssh_alias
        fqdn = self.tailscale_name
        expected_ip = self.tailscale_ip_reference
        expected_host = self.hostname
        pin = self.pinned_host_key_fingerprint

        resolved = self._ssh_resolve_alias(alias)
        resolved_host = (resolved.get("hostname") or "").strip().lower()
        if resolved_host not in {fqdn.lower(), expected_ip}:
            self._raise_with_reason("alias_resolve")

        self._assert_tailscale_peer_current(fqdn, expected_ip)

        observed_key_line, observed_fp = self._observe_ed25519_fingerprint(fqdn)
        if observed_fp != pin:
            self._raise_with_reason("fingerprint_mismatch")

        remote_hostname = self._ssh_strict_hostname_probe(
            alias=alias,
            fqdn=fqdn,
            expected_ip=expected_ip,
            known_hosts_line=observed_key_line,
        )
        if remote_hostname != expected_host:
            self._raise_with_reason("hostname_mismatch")

    def _raise_with_reason(self, reason_code):
        err = UserError(REASON_MESSAGES[reason_code])
        err.reason_code = reason_code  # type: ignore[attr-defined]
        raise err

    def _run_allowlisted(self, executable, argv_tail, timeout, env=None):
        if executable not in {
            SSH_EXECUTABLE,
            SSH_KEYSCAN_EXECUTABLE,
            SSH_KEYGEN_EXECUTABLE,
            TAILSCALE_EXECUTABLE,
        }:
            self._raise_with_reason("tooling")
        if not os.path.isfile(executable) or not os.access(executable, os.X_OK):
            self._raise_with_reason("tooling")
        for part in argv_tail:
            if not isinstance(part, str) or "\x00" in part:
                self._raise_with_reason("tooling")
        controlled_env = {
            "PATH": "/usr/bin:/bin",
            "HOME": os.environ.get("HOME") or "/tmp",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
        }
        if env:
            controlled_env.update(env)
        try:
            completed = subprocess.run(
                [executable, *argv_tail],
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
                shell=False,
                env=controlled_env,
            )
        except FileNotFoundError:
            self._raise_with_reason("tooling")
        except subprocess.TimeoutExpired:
            self._raise_with_reason("timeout")
        stdout = (completed.stdout or "")[:OUTPUT_BYTE_LIMIT]
        stderr = (completed.stderr or "")[:OUTPUT_BYTE_LIMIT]
        return completed.returncode, stdout, stderr

    def _ssh_resolve_alias(self, alias):
        code, stdout, _stderr = self._run_allowlisted(
            SSH_EXECUTABLE,
            ["-G", alias],
            timeout=SUBPROCESS_TIMEOUT,
        )
        if code != 0:
            self._raise_with_reason("alias_resolve")
        resolved = {}
        for line in stdout.splitlines():
            if not line or " " not in line:
                continue
            key, value = line.split(" ", 1)
            key = key.strip().lower()
            if key in {"hostname", "user", "port"}:
                resolved[key] = value.strip()
        return resolved

    def _assert_tailscale_peer_current(self, fqdn, expected_ip):
        code, stdout, _stderr = self._run_allowlisted(
            TAILSCALE_EXECUTABLE,
            ["status", "--json"],
            timeout=SUBPROCESS_TIMEOUT,
        )
        if code != 0:
            self._raise_with_reason("tailscale_offline")
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            self._raise_with_reason("tailscale_mismatch")
        peers = payload.get("Peer") or {}
        if isinstance(peers, dict):
            peer_iter = peers.values()
        else:
            peer_iter = peers
        fqdn_l = fqdn.lower()
        for peer in peer_iter:
            if not isinstance(peer, dict):
                continue
            ips = [str(ip) for ip in (peer.get("TailscaleIPs") or [])]
            names = {
                (peer.get("DNSName") or "").rstrip(".").lower(),
                (peer.get("HostName") or "").rstrip(".").lower(),
            }
            if fqdn_l not in names:
                continue
            if expected_ip not in ips:
                self._raise_with_reason("tailscale_mismatch")
            if peer.get("Online") is False:
                self._raise_with_reason("tailscale_offline")
            return
        # Self node may appear under Self rather than Peer (local Dell).
        self_node = payload.get("Self") or {}
        if isinstance(self_node, dict):
            dns = (self_node.get("DNSName") or "").rstrip(".").lower()
            ips = [str(ip) for ip in (self_node.get("TailscaleIPs") or [])]
            if dns == fqdn_l:
                if expected_ip not in ips:
                    self._raise_with_reason("tailscale_mismatch")
                return
        self._raise_with_reason("tailscale_mismatch")

    def _observe_ed25519_fingerprint(self, fqdn):
        code, stdout, _stderr = self._run_allowlisted(
            SSH_KEYSCAN_EXECUTABLE,
            ["-t", "ed25519", "-T", str(KEYSCAN_TIMEOUT), fqdn],
            timeout=KEYSCAN_TIMEOUT + 5,
        )
        if code != 0:
            self._raise_with_reason("host_key")
        key_lines = [
            line.strip()
            for line in stdout.splitlines()
            if line.strip()
            and not line.startswith("#")
            and " ssh-ed25519 " in f" {line.strip()} "
        ]
        if not key_lines:
            self._raise_with_reason("host_key")
        key_line = key_lines[0]
        # Bound key line length
        if len(key_line) > 800 or "\x00" in key_line:
            self._raise_with_reason("host_key")
        parts = key_line.split()
        if len(parts) < 3 or parts[1] != "ssh-ed25519":
            self._raise_with_reason("host_key")
        # Normalize host token before fingerprinting.
        normalized = f"{fqdn} {parts[1]} {parts[2]}"
        with tempfile.NamedTemporaryFile("w+", delete=False) as handle:
            handle.write(normalized + "\n")
            handle.flush()
            temp_path = handle.name
        try:
            code, fp_out, _stderr = self._run_allowlisted(
                SSH_KEYGEN_EXECUTABLE,
                ["-lf", temp_path, "-E", "sha256"],
                timeout=SUBPROCESS_TIMEOUT,
            )
        finally:
            try:
                os.unlink(temp_path)
            except OSError:
                pass
        if code != 0:
            self._raise_with_reason("host_key")
        # Typical: "256 SHA256:xxxx host (ED25519)"
        match = re.search(r"(SHA256:[A-Za-z0-9+/]{43})", fp_out)
        if not match:
            self._raise_with_reason("host_key")
        return normalized, match.group(1)

    def _ssh_strict_hostname_probe(self, alias, fqdn, expected_ip, known_hosts_line):
        with tempfile.TemporaryDirectory(prefix="devhub-kh-") as tmp:
            known_hosts = Path(tmp) / "known_hosts"
            parts = known_hosts_line.split()
            if len(parts) < 3 or parts[1] != "ssh-ed25519":
                self._raise_with_reason("host_key")
            key_type, key_data = parts[1], parts[2]
            # Include alias because OpenSSH HostKeyAlias lookups use the alias token.
            host_tokens = []
            for token in (alias, fqdn, expected_ip):
                if token and token not in host_tokens:
                    host_tokens.append(token)
            known_hosts.write_text(
                "".join(f"{token} {key_type} {key_data}\n" for token in host_tokens),
                encoding="utf-8",
            )
            argv = [
                "-o",
                "BatchMode=yes",
                "-o",
                "StrictHostKeyChecking=yes",
                "-o",
                f"UserKnownHostsFile={known_hosts}",
                "-o",
                "GlobalKnownHostsFile=/dev/null",
                "-o",
                "PasswordAuthentication=no",
                "-o",
                "KbdInteractiveAuthentication=no",
                "-o",
                "PreferredAuthentications=publickey",
                "-o",
                "ForwardAgent=no",
                "-o",
                f"ConnectTimeout={SSH_CONNECT_TIMEOUT}",
                "-o",
                f"Hostname={fqdn}",
                "-o",
                "HostKeyAlgorithms=ssh-ed25519",
                alias,
                *REMOTE_HOSTNAME_ARGV,
            ]
            code, stdout, _stderr = self._run_allowlisted(
                SSH_EXECUTABLE, argv, timeout=SUBPROCESS_TIMEOUT
            )
            if code != 0:
                self._raise_with_reason("ssh_failed")
            remote = _sanitize_text(stdout.splitlines()[0] if stdout else "", 253)
            if not remote or not HOSTNAME_SAFE.fullmatch(remote):
                self._raise_with_reason("output")
            return remote

    def _record_verification_outcome(
        self, success, reason_code, dry_run=False, mark_unreachable=False
    ):
        for record in self:
            record._audit_verification(
                success=success,
                reason_code=reason_code,
                dry_run=dry_run,
            )
            if mark_unreachable and not dry_run:
                record.with_context(dev_machine_verification_write=True).write(
                    {
                        "last_reachability_status": "unreachable",
                        "last_checked_at": fields.Datetime.now(),
                    }
                )

    def _audit_verification(
        self, success, reason_code, dry_run=False, raise_access=False
    ):
        Event = self.env["dev.machine.verification.event"].sudo()
        for record in self:
            Event.create(
                {
                    "machine_id": record.id,
                    "actor_id": self.env.uid,
                    "timestamp": fields.Datetime.now(),
                    "success": bool(success),
                    "reason_code": _sanitize_text(reason_code, 64),
                    "destination_ref": _sanitize_text(record.tailscale_name, 253),
                    "fingerprint_ref": _sanitize_text(
                        record.pinned_host_key_fingerprint, 80
                    ),
                    "correlation_id": str(uuid.uuid4()),
                    "dry_run": bool(dry_run),
                }
            )
        self.env.flush_all()
        if raise_access:
            raise AccessError(REASON_MESSAGES["not_manager"])
