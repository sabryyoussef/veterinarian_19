# First Controlled Phase 5 Dev Worker Pilot Report

## Result

**FAIL-CLOSED — did not reach `review_required`.**

The restricted worker safely started, acquired lease version 1, completed P1,
and created only the two explicitly allowlisted Test files during P2. The
mandatory post-write allowlist assertion then rejected the Git porcelain
representation of those files. The worker process stopped immediately. No
worker tests or subsequent Plan steps ran.

The workspace and files were preserved, an immutable failure checkpoint was
created, the Work Item and Workspace were moved to `blocked`, the lease was
revoked, and the secure token state file was removed. No retry was attempted.

## Pilot identity and contract

1. **Work Item:** DW-4, `Phase5 Pilot: add fixture README contract test`
2. **Analysis:** ID 2, accepted
3. **Approved Plan:** ID 3, revision 1, five bounded steps
4. **Approved Plan hash:** `9ce5023871eae4701c21a6cda32615a8b12cc6db2626acab73c272d518fefebc`
5. **Execution policy hash:** `25554346d432bc2c0c8287db2a3859d589bc17dfe4c5ebf1e2f238088e6348a9`
6. **Execution contract hash:** `bf887b91b6bab7badd367a596408f896445f71802ce4e82d7f49a9365f4f5d62`
7. **Execution Workspace:** ID 8
8. **Branch:** `devhub/DW-4-phase5-pilot-add-fixture-readme-contract-test`
9. **Worktree:** `/srv/devhub-uat/worktrees/petspot-uat/DW-4`
10. **Base/current HEAD:** `5a7f1e1404dbbc1efeacc1a1bcaea3021d7cd7ae`
11. **Worker:** `devworker`, effective UID/GID `1001:1001`
12. **Environment:** `Isolation UAT Test`, non-production

All Plan, policy, contract, repository, environment, identity, branch, path,
and Base HEAD checks passed before execution.

## Execution

### Completed

- Created a new Work Item, accepted Analysis, exact approved Plan, dedicated
  branch, and dedicated physical worktree.
- Verified the manual worktree snapshot before preparation.
- Started the bounded worker as `devworker`.
- Proved no sudo, Docker socket, Sabry-home, Production, or manual-worktree
  write access.
- Acquired exclusive lease version 1.
- P1 completed and checkpointed.
- P2 created:
  - `tests/__init__.py`
  - `tests/test_fixture_readme.py`
- Post-failure inspection independently proved these were the only changed
  files.

### Failure

The worker's allowlist contained path-only values:

- `tests/__init__.py`
- `tests/test_fixture_readme.py`

`dev.execution.workspace.changed_files_summary` intentionally stores Git
porcelain entries including status prefixes:

- `?? tests/__init__.py`
- `?? tests/test_fixture_readme.py`

The pilot harness compared the prefixed entries directly to the path-only
allowlist. The sets therefore differed even though the actual files were exact.
The P2 Odoo transaction rolled back to `pending`; filesystem writes remained
preserved, as expected for a fail-closed worker.

This was a worker-harness normalization defect, not an unauthorized file
change. It is still a blocking pilot failure because the approved Plan did not
authorize automatic recovery or retry.

### Fail-closed response

- Worker process stopped before tests.
- Immutable checkpoint ID 5 captured the failure.
- Workspace ID 8 moved to `blocked` with
  `worker_status=blocked_fail_closed`.
- Work Item DW-4 moved to `blocked`.
- Lease token was revoked and cleared.
- Secure lease state file was removed.
- Worktree and branch were preserved.
- No cleanup, reset, retry, commit, push, PR, merge, deployment, restart,
  Production access, Docker operation, sudo operation, external message, or
  OpenProject completion occurred.

## Plan-step and lifecycle results

| Step | Result |
|---|---|
| P1 — Inspect fixture contract | Done; checkpoint created |
| P2 — Implement test-only contract | Files created; control transaction rolled back to Pending after fail-closed assertion |
| P3 — Targeted test and Pause | Not run |
| P4 — Resume, concurrent-writer control, regression | Not run |
| P5 — Review handoff | Not run |

Pause/Resume, the live concurrent-writer negative control, worker test
execution, Review Handoff, and `review_required` were not reached.

## Isolation and Git results

- Manual branch before/after: `main` / `main`
- Manual HEAD before/after: unchanged
- Manual dirty digest before/after: unchanged
- Pilot worktree owner/mode: `devworker:devworker`, `1001:1001`, `770`
- Pilot commits ahead of Base HEAD: `0`
- Preserved UAT `DW-3`: unchanged
- Automatic commit/push/PR/merge/deployment: none
- Production access: none
- Policy violations: none

## UI and automated evidence

- Main Playwright pilot: **0/1 passed**; failed at the P2 allowlist boundary.
- Fail-closed evidence Playwright: **1/1 passed**.
- Screenshots: **12**, including preparation, exact hashes, active worker,
  blocked state, failure checkpoint, and final blocked audit.
- Dedicated worker-control unit test: **1/1 passed**, 0 failures, 0 errors.
- Full Dev Hub module suite: **53/53 passed**, 0 failures, 0 errors.
- Isolation/security suite: **12/12 passed**, 0 failures, 0 errors.
- Worker task targeted/regression tests: **not run** because fail-closed
  occurred first.

Evidence folder:

`dev_session_hub/docs/uat/phase5_worker_pilot_20260719/`

Key artifacts:

- `PILOT_SCENARIO.md`
- `sanitized_worker_log.txt`
- `sanitized_git_verification.txt`
- `sanitized_isolation_verification.txt`
- `playwright_execution.log`
- `failure_evidence_execution.log`
- `worker_control_test.log`
- `module_test_execution.log`
- `security_test_execution.log`
- `screenshots/`

## Blockers, in priority order

1. Normalize Git porcelain entries to canonical relative paths before
   allowlist comparison, while retaining status separately for audit.
2. Add worker-harness tests for untracked, modified, deleted, and renamed
   allowlisted files and explicit rejection of any extra path.
3. Obtain explicit human approval for a new controlled pilot attempt. Do not
   resume or reuse this blocked execution automatically.
4. The new attempt must still prove targeted/regression tests, Pause/Resume,
   concurrent-writer denial, Review Handoff, and the hard
   `review_required` stop.

No next autonomy capability is recommended because the first implementation
pilot did not pass.

Did the first Phase 5 Dev Worker pilot safely reach Review Required: NO
