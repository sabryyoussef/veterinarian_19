# Development Session Hub (MVP)

`dev_session_hub` is an isolated Odoo 19 control-plane module for resuming a
registered development context across local Cursor clients.

## Security status and MVP boundary

- Initial security review: **FAILED**
- Remediation: implemented and covered by adversarial tests
- Registered target: `master` (hosts production; launch is therefore denied)
- Project: PetSpot
- Environment: PetSpot Test only
- Database: `pet_spot_elsahel_test`
- Port: `8028`
- Task source: read-only OpenProject link
- Launcher: disabled until a managed pin-enforcing helper exists

The module does **not** access production, change Git, restart services, control
Docker, deploy, commit/push, write to OpenProject/GitHub, or store credentials.
Strict launch acceptance is blocked until both a genuinely dedicated,
non-production canonical target and a managed pin-enforcing helper exist.

## Remediated controls

- Session paths must resolve exactly to both repository canonical path fields.
- Git reads use a fixed environment and command-scoped disabling of fsmonitor,
  hooks, credential helpers, external diffs, pagers, attributes and file
  protocol; snapshots verify the exact Git root, `.git` directory, and origin,
  and never write repository caches.
- Launch rejects production-bearing/non-trusted machines, sensitive or
  production data, inactive records, and destinations without verified
  Tailscale and pinned host-key metadata.
- Project owner/member authorization is enforced by record rules and server
  checks; managers retain full registry access.
- Canonical worktree paths are unique. Session and worktree transitions use
  path-keyed PostgreSQL row and transaction advisory locks, then re-read state.
- Exact environment policy wins; generic policy is used only when exact policy
  is absent, and duplicate/inconsistent scopes are rejected.
- Launcher creation and downloads are denied server-side; stale transient
  artifacts are purged during module initialization.
- Non-launch and terminal transitions use best-effort snapshots so target/Git
  failure cannot trap a session; failures are recorded without exception text.
- Manifest strings are recursively allowlist-sanitized. Events are immutable,
  including for superuser calls, and event/session deletion is restrictive.

## Workflow

1. Open **Dev Hub → Recent Work**.
2. Create a session and select client, PetSpot, PetSpot Test, and a task.
3. **Start & Launch** currently fails closed. The seeded `master` target hosts
   production, and Stage A cannot enforce the SSH pin after Cursor takes over.
4. A future managed helper must own the complete pinned SSH connection before
   launch artifacts are enabled.
5. **Pause**, select the second client, then **Resume & Launch**.
6. Review any branch/HEAD/dirty-state drift warning.
7. Mark In Progress and Complete.

Lifecycle events are immutable. Concurrent active sessions on the same
registered worktree are serialized and blocked.

## Launcher behavior

The browser does not execute local commands. A known-host preflight followed by
a separate Cursor invocation cannot guarantee that Cursor uses the same pin, so
the launcher is disabled. The safety workspace intentionally has no remote
folder. GUI acceptance requires a Stage B helper that enforces the pin for the
complete connection.

No custom URI handler or token exchange endpoint is exposed in this MVP.

## Test-only installation

The module is installed only on `pet_spot_elsahel_test`. Do not install it on
the PetSpot production database.

Automated coverage validates lifecycle transitions, exact path binding,
hardened Git invocation and identity, duplicate-worktree denial, membership
denial, production-bearing target denial, policy precedence, forged launcher
denial, terminal closure after snapshot failure, path-keyed concurrency
protection, credential/hostile manifest sanitization, immutable events, and
sensitive-note rejection.
