# Dev Hub Isolated Execution Architecture

## Security decision

Dev Hub does not share the main developer worktree's `.git` directory with the
restricted worker identity. Linked worktrees require writes to their Git common
directory; granting that access would allow the worker to mutate branch and
worktree metadata used by Sabry's main Cursor workspace.

Each approved project therefore uses:

- a dedicated bare Git common repository under `/srv/devhub/repos/<project>.git`;
- physical task worktrees under `/srv/devhub/worktrees/<project>/DW-<id>`;
- deterministic branches named `devhub/DW-<id>-<bounded-slug>`;
- a restricted `devworker` account on a non-production machine;
- a constrained provisioning helper running as the same `devworker` UID.

The bare repository contains Git history and Dev Hub task branches only. It is
not a production runtime path, Docker volume, backup path, secret location, or
Sabry's main repository metadata. Odoo does not receive cross-user write access
to it: physical Git preparation must execute through the worker-owned helper.
Updating its base refs is a separate, human-controlled repository
synchronization operation.

## Human-controlled preparation

`Prepare Execution Workspace` performs a read-only preflight and records a
`pending_confirmation` proposal. It verifies the current exact plan approval,
the canonical hash of the reviewed execution policy, non-production policy,
repository classification, Base HEAD, branch name, generated path, and a
metadata-only snapshot of the main worktree. These values form an immutable
execution-contract hash.

A Dev Hub Manager must review and confirm the proposal. The restricted
worker-owned provisioning helper then permits only two bounded Git writes:

1. create the proposed branch at the exact Base HEAD;
2. add the proposed physical worktree for that branch.

The Git wrapper rejects commit, push, merge, reset, clean, checkout, stash,
worktree removal, and branch deletion. A collision is never reset or
overwritten. Main-worktree branch, HEAD, dirty counts, and dirty digest must be
identical before and after preparation.

## Canonical context and resume

An isolated `dev.session` derives its Work Item, project, repository,
environment, machine, branch, and physical directory from
`dev.execution.workspace`. Checkpoints store the workspace, Base HEAD, current
HEAD, dirty digest, changed-file summary, plan step, test evidence, and
blockers. Resume validates and reopens the same physical worktree; a missing or
mismatched worktree fails closed.

Manual developer sessions remain supported, but must be explicitly identified
as `manual_developer_session`. They continue to use the registered main
worktree. Agent-related sessions cannot accept an arbitrary path.

## Concurrency and cleanup

The workspace stores an active session marker plus a bounded worker lease with
owner, client, expiry, monotonic version, and UUID fencing token. A second
writer is denied while a lease is active; stale tokens are rejected.

Release retains the worktree and branch. Cleanup is a separate request and no
removal is implemented in this sprint. Dirty worktrees, active sessions, and
active leases block cleanup. No branch is force-deleted and no unmerged branch
is deleted automatically.

## Current PetSpot classification

The registered PetSpot repository is `production_coupled` and is not approved
for agent execution:

- Production and Test load addons directly from the main worktree.
- Proxy and operational service definitions reference paths inside it.
- Backup automation references the same repository.
- The main worktree has extensive existing staged and unstaged work.
- `master-ts` is explicitly registered as production-bearing.
- no `devworker` account or dedicated `/srv/devhub` repository exists.

Consequently, physical workspace creation and Test-only UAT must not run on
`master-ts`. The next infrastructure step is to provision a separate
non-production execution machine, create the restricted identity there, create
the dedicated bare repository and worktree roots, and register that machine and
environment before enabling `agent_execution_allowed`.
