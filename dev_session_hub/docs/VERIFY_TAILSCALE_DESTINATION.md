# Verify Tailscale Destination — design & threat model

## Trust boundary

- The Odoo application process invokes **local** allowlisted binaries (`/usr/bin/ssh`,
  `/usr/bin/ssh-keyscan`, `/usr/bin/ssh-keygen`, `/usr/bin/tailscale`) via
  `subprocess.run([...], shell=False)`.
- Destination identity comes **only** from `dev.machine` registry fields
  (`tailscale_name`, `tailscale_ip_reference`, `pinned_host_key_fingerprint`,
  `hostname`, `verification_ssh_user`). Callers cannot supply an arbitrary
  hostname, SSH config path, or remote command.
- `ssh_alias` remains a registry / display / client-launch value. **Active
  server-side verification does not parse alias OpenSSH configuration.**
- Eligible targets are `active`, `production=False`, `trust_zone=trusted_dev`.
- Remote command is fixed: `hostname` (argument vector, never shell-interpolated).

## SSH invocation (config isolation)

Every active `ssh` call uses:

```text
["/usr/bin/ssh", "-F", "/dev/null", "-l", <verification_ssh_user>,
 -o <explicit safe options>..., "--", <validated .ts.net FQDN>, "hostname"]
```

`-F /dev/null` makes OpenSSH ignore both `~/.ssh/config` and `/etc/ssh/ssh_config`
(including `Include` and `Match exec`). CLI `-o` overrides alone do **not** prevent
`Match exec` evaluation when a config file is parsed — verified against OpenSSH
behavior; see the Match-exec regression test.

`ssh-keyscan` observes the host key for the validated FQDN only.
`ssh-keygen -lf` fingerprints a temporary known_hosts file only.
There is **no** `ssh -G` in the verification path.

### Credential reference

Default OpenSSH identity files under the process account may still be offered for
public-key auth. Verification never reads private-key content into Odoo and does
not accept a caller-supplied identity path. If a dedicated key is required later,
add an approved fixed path-reference field with ownership/permission checks.

## Threats and mitigations

| Threat | Mitigation |
|--------|------------|
| Command / shell injection | argv arrays only; `shell=False`; FQDN/IP/user validated by regex before use |
| Malicious SSH config / Match exec | `-F /dev/null`; no alias config parse; no `ssh -G` |
| Include / KnownHostsCommand / Proxy* | Null config + explicit `-o` disables |
| DNS substitution | Connect only to registered `.ts.net` FQDN; Tailscale status DNS+IP must uniquely match |
| Forgeable ORM context | Verification field writes use private `_write_verification_private()` → parent `write`; no context-key bypass |
| Changed host key | Observe ED25519 key, fingerprint must equal pin; then StrictHostKeyChecking against temp known_hosts containing only that key |
| Stale Tailscale identity | Require peer Online in `tailscale status --json` for registered FQDN/IP |
| Connecting to Production | Refuse `production=True` and non-`trusted_dev` before any network I/O |
| User-controlled known_hosts | Temp file owned by process; `GlobalKnownHostsFile=/dev/null`; never accept caller path |
| Hanging subprocess | Bounded ConnectTimeout + overall subprocess timeout |
| Secrets in logs / errors | Sanitized reason codes and UserError messages; no argv dumps; no stdout/stderr in audit |
| Unauthorized verification | Server-side `group_dev_hub_manager` check; AccessError for others |
| TOCTOU verify→launch | Launch re-checks verified flag, timestamp, pin, and identity; identity field writes invalidate verification |

## Authorization

- Button and server action: `dev_session_hub.group_dev_hub_manager` only.
- Ordinary Dev Hub users receive `AccessError` even if they can read the machine.
- Audit row create uses narrowly scoped `sudo()` after the authorization decision.

## Audit record

Immutable `dev.machine.verification.event` rows store: machine id, actor, timestamp,
success flag, reason code, destination FQDN reference, fingerprint reference
(SHA256 pin string already on the machine — not private key material). No credentials,
command lines, or raw SSH output.

## Re-verification and expiry

- There is **no automatic expiry** in this release. Operators re-run
  **Verify Tailscale Destination** when identity may have changed or periodically
  by policy.
- Successful re-verification refreshes `tailscale_verified_at`.
- Failed verification does **not** clear a prior successful `verified_at` unless an
  identity-critical field was changed (invalidation path). Reachability status may
  be set to `unreachable` on failure.

## Invalidation

Identity-critical writes clear verification (`verified=False`, `verified_at=False`):

- `hostname`
- `ssh_alias`
- `verification_ssh_user`
- `tailscale_name`
- `tailscale_ip_reference`
- `pinned_host_key_fingerprint`

**`allowed_path_prefixes` changes do not invalidate network verification** — path
allowlists are enforced separately at launch. Operators should still review path
changes carefully.

Direct writes to `tailscale_destination_verified` / `tailscale_verified_at` are
always rejected by `write()`. The verification action updates them only through
`_write_verification_private()`, which calls the parent `write` implementation
directly and cannot be forged via RPC context keys.

## Constraint

`_check_verified_destination` is unchanged and remains fail-closed.
