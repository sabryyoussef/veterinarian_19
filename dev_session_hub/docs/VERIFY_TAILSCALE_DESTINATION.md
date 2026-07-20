# Verify Tailscale Destination — design & threat model

## Trust boundary

- The Odoo application process invokes **local** allowlisted binaries (`/usr/bin/ssh`,
  `/usr/bin/ssh-keyscan`, `/usr/bin/ssh-keygen`, `/usr/bin/tailscale`) via
  `subprocess.run([...], shell=False)`.
- Destination identity comes **only** from the `dev.machine` record fields
  (`ssh_alias`, `tailscale_name`, `tailscale_ip_reference`,
  `pinned_host_key_fingerprint`, `hostname`). Callers cannot supply an arbitrary
  hostname or remote command.
- Eligible targets are `active`, `production=False`, `trust_zone=trusted_dev`.
- Remote command is fixed: `hostname` (argument vector, never shell-interpolated).

## Threats and mitigations

| Threat | Mitigation |
|--------|------------|
| Command / shell injection | argv arrays only; `shell=False`; alias/DNS/IP validated by regex before use |
| Malicious SSH config | `ssh -G` inspected for ProxyCommand/ProxyJump/LocalCommand/forwards; CLI forces ProxyCommand=none, ClearAllForwardings=yes, PermitLocalCommand=no, IdentityAgent=none, etc. |
| DNS substitution | Compare `ssh -G` resolved HostName to registered FQDN or Tailscale IP; Tailscale status DNS+IP must uniquely match |
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
