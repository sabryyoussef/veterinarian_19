# Remote Development / Cursor Dev Hub MVP — Implementation Report

**Date:** 2026-07-18
**Scope:** P0–P4 only
**Database changed:** `pet_spot_elsahel_test` only
**Production changes:** none

**Security review result:** the initial implementation **FAILED** review. The
findings listed in the remediation request were addressed in this revision.
The automated suite now passes, but MVP manual launch acceptance is
intentionally blocked: the currently registered `master` machine truthfully
has `production=true`, so no launch artifact can be generated until a genuinely
dedicated non-production canonical target is registered and verified.

## 1. Files and module

Created the standalone Odoo 19 application `dev_session_hub`. It does not
reuse or modify either outreach-oriented `developer_hub` module.

Module contents:

- manifest and package initialization;
- registry, policy, session, event, dashboard, and launcher models;
- Odoo 19 privilege groups, access controls, and record rules;
- sanitized PetSpot Test seed data;
- dashboard, Recent Work, registry, policy, and launcher views;
- automated transaction tests;
- this report and module README.

## 2. Database models

Persistent models:

- `dev.machine`
- `dev.client`
- `dev.project`
- `dev.repository`
- `dev.environment`
- `dev.task.link`
- `dev.policy`
- `dev.session`
- `dev.session.event`
- `dev.dashboard`

Transient launcher model:

- `dev.launch.wizard`

## 3. Seeded MVP registry

Registered metadata (not an eligible launch target):

- machine `master`;
- Tailscale name and IP reference;
- Tailscale SSH alias `master-ts`;
- exact PetSpot repository/worktree path;
- verified Tailscale destination metadata and pinned ED25519 host-key
  fingerprint;
- Git remote, current branch, and initial HEAD from the original inventory;
- PetSpot Test, database `pet_spot_elsahel_test`, port `8028`, Odoo 19;
- Windows Desktop client, Cursor `3.5.38`;
- Ubuntu Dell Precision client, Cursor `3.12.17`;
- Remote SSH extension `1.1.11` on both clients;
- OpenProject project `28`, test work package `337`;
- PetSpot Test policy: development/tests allowed, production/deployment denied.

Unknown Cursor Agent versions, helper versions, and repository default branch
are explicitly unresolved rather than guessed.

## 4. Menus, views, and actions

App: **Dev Hub**

- Dashboard
- Recent Work
- Active Sessions
- Paused Sessions
- Registry
  - Projects
  - Environments
  - Repositories
  - Task Links
  - Machines
  - Development Clients
- Configuration
  - Policies

Session form actions:

- Start & Launch
- Mark In Progress
- Pause
- Resume & Launch
- Open Launcher
- Complete
- Block
- Abandon

## 5. Security

- Odoo 19 privilege groups: Dev Hub User and Dev Hub Manager.
- Users can read only owner/member-authorized project registry records and
  manage only their own authorized sessions; create/write checks repeat the
  authorization server-side.
- Managers can manage registry and policy records and see all sessions.
- Session events are immutable even through superuser calls and restrict
  deletion of their parent sessions.
- Session lifecycle/snapshot/manifest fields cannot be written directly.
- Target fields are editable only while Draft.
- The active client can change only before start or while paused/blocked.
- Launch rejects production-bearing machines, non-`trusted_dev` zones,
  production/restricted/confidential data, inactive targets, and unverified
  Tailscale destinations or missing pinned host keys.
- Session working paths must match both repository paths exactly by realpath.
- Exact environment policy is selected before generic fallback; duplicate and
  cross-project policy scopes are rejected.
- Session rows and worktrees are serialized with PostgreSQL row and
  transaction advisory locks, then state is re-read before transition checks.
- Launcher RPC create values cannot supply artifacts; all artifacts are
  server-derived from an authorized active session and protected from writes.
- Non-launch/terminal transitions remain available when policy, path, or Git
  is unavailable; a generic snapshot-failure marker is retained.
- No Docker socket, restart, deploy, SSH key, database password, MCP token,
  `.env` value, arbitrary command, transcript, prompt, diff, or file content is
  stored or executed.

## 6. State machine

Implemented:

`draft → started → in_progress → paused → resumed → completed`

Also supported:

- active/paused/resumed → `blocked`
- non-terminal states → `abandoned`
- `blocked → resumed`

Invalid transitions raise a user-facing error. Each accepted transition stores
an append-only event with actor, client, timestamp, reason, correlation ID, and
sanitized Git snapshot.

## 7. Git snapshot and drift behavior

Fixed, non-shell Git reads collect:

- current branch;
- current HEAD;
- counts of staged, unstaged, untracked, and conflicted entries;
- a short digest used only for dirty-state comparison.

Git runs with a fixed minimal environment and explicit command-scope options
that disable fsmonitor, hooks, credential helpers, external diffs, pagers,
external attributes, and file transport. No repository cache/sudo write
occurs. No file names, contents, or diffs are stored.

Resume compares the saved branch, HEAD, and dirty summary with current values
and displays a warning. It does not repair drift.

## 8. Manifest schema

Schema ID: `dev-session-hub.manifest.v1`

All manifest string values are recursively allowlist-sanitized. Safe fields
include session/project/environment identifiers, SSH/Tailscale identity and
pinned host-key reference, canonical path, database identifier, port, Odoo
version, service reference, Git aggregate metadata, task reference, client,
capabilities, drift warning, and fixed guardrails.

The manifest explicitly reports `production: false` and
`deploy_allowed: false`.

## 9. Launcher method

Stage A launcher status: **disabled / fail-closed**.

A local known-host preflight followed by a separate Cursor invocation does not
prove that Cursor uses the same SSH configuration and pinned key. Therefore no
remote-folder launcher artifact is available. The downloadable safety
workspace has no remote folder, and the JSON manifest is generated only inside
unit tests that explicitly substitute the unavailable helper capability.

Stage B is now a security prerequisite: a managed local helper must own the
complete SSH connection, enforce the exact host-key pin, and then invoke
Cursor. No custom URI handler, endpoint, launch token, or helper is currently
deployed.

## 10. Test results

### Automated Odoo tests

Result: **PASS after remediation**

- 20 test methods
- 0 failures
- 0 errors

Coverage includes exact path and Git identity binding, duplicate canonical
worktree denial, hardened Git options/environment, unauthorized project/session
denial, production-bearing machine denial, policy precedence/uniqueness, forged
wizard denial, terminal closure after snapshot failure, lifecycle/drift,
path-keyed worktree concurrency, hostile and credential-bearing manifest
strings, unavailable-helper denial, superuser event immutability, and
sensitive-note rejection.

### Real test-database lifecycle

Historical pre-review result: **SUPERSEDED / NOT ACCEPTED**

The initial implementation created a real session in `pet_spot_elsahel_test`
and executed:

`Started → Paused → Resumed on Ubuntu client → In Progress → Completed`

That run does not satisfy the remediated acceptance criteria because `master`
hosts production. The remediated launcher now denies that same target.

### Windows client

Verified remotely:

- reachable through the registered SSH alias;
- Cursor `3.5.38`;
- Remote SSH `1.1.11`;
- client-side `master-ts` alias resolves to the correct user and Tailscale host.

Manual GUI opening: **BLOCKED** until an eligible dedicated non-production
target replaces `master` for launch.

### Ubuntu client

Verified remotely:

- reachable through the registered SSH alias;
- Cursor `3.12.17`;
- Remote SSH `1.1.11`;
- client-side `master-ts` alias resolves to the correct user and Tailscale host.

Manual GUI opening: **BLOCKED** for the same production-target reason.

## 11. MVP acceptance result

Backend fail-closed security regression suite: **PASS**

- registry and policy;
- non-production enforcement;
- mocked lifecycle and cross-client marker logic;
- Git snapshot and drift logic under explicit test doubles;
- concurrency protection;
- append-only audit;
- sanitized manifest logic;
- launcher creation/download denial;
- no Git mutation, service restart, Docker action, deploy, commit/push, or
  OpenProject/GitHub write.

Functional backend Start/Resume acceptance: **BLOCKED** until Stage B.

Full device-to-GUI scenario: **BLOCKED**

No manual launcher artifact should be generated for the current shared
production-bearing `master`. Acceptance requires registering a genuinely
dedicated non-production machine/worktree with trusted-dev classification,
active records, verified Tailscale destination, pinned host-key metadata, and a
managed helper that enforces that pin end-to-end. No unsafe bypass was added.

## 12. Known limitations

- No automatic OpenProject refresh; task link is a verified manual cache.
- No local helper or one-time token flow.
- No baseline enforcement; client compliance is report-only.
- Cursor Agent versions and thread portability remain unresolved.
- The existing PetSpot working tree is heavily dirty; the session records only
  aggregate state and does not attempt cleanup.
- The only current canonical target is `master`, which truthfully hosts
  production workloads; strict fail-closed launch therefore blocks MVP manual
  acceptance.
- The launcher is disabled because a separate preflight cannot enforce which
  SSH configuration Cursor subsequently uses. A managed pin-enforcing helper
  is required.
- PostgreSQL locking is exercised by lifecycle/concurrency tests, but a
  separate multi-process stress test remains advisable before broader rollout.
- Existing infrastructure warnings outside this module remain in Odoo logs,
  including unrelated `ai.embedding`, legacy SQL-constraint, and pet-field
  dependency warnings.

## 13. Residual security prerequisites

Before any Stage B helper or launcher endpoint:

- remove/rotate known literal secrets and stop credential propagation into
  OpenProject descriptions;
- restore TLS verification in affected integration clients;
- verify effective UFW, SSH, and Tailscale ACL policy;
- remove public Funnel exposure from any future Dev Hub/helper route;
- define signed, one-time, audience-bound launch references;
- prove off-host backup completeness and restore;
- isolate the development identity/worktree from production controls.

## 14. Recommended next phase

Provision and independently verify a dedicated non-production canonical target
first. Only then perform the two manual client GUI checks. Build a local helper
only if the manual fallback is operationally insufficient and after the token,
Tailscale-only HTTPS, URI ownership, allowlist, and compatibility design is
approved.
