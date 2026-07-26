# Dedicated Branch + Isolated Worktree UAT Report

**Execution date:** 2026-07-19  
**Result:** PASS  
**Phase 5 started:** No

## Executive result

The scenario was designed first in `UAT_SCENARIO.md`, then executed completely
against a disposable Odoo 19 database on a separate non-production Ubuntu host.
Playwright exercised the Odoo UI and captured every required major state.
Backend, Git, ownership, and filesystem checks independently agreed with the UI.

The UAT found four integration defects before the final pass:

1. guarded workspace-event creation was blocked by its immutable user ACL;
2. session snapshot validation assumed a normal `.git` directory rather than a
   linked-worktree `.git` file and worker-owned common directory;
3. the execution contract was stored but not recomputed during validation;
4. exact-plan revalidation incorrectly required the Work Item to remain in the
   pre-execution `approved` phase.

All four were corrected. The final Playwright, full-module, and dedicated
security reruns passed.

## Executed scenario

1. **Scenario:** PetSpot Isolation UAT — exact-plan worker workspace
2. **Work Item:** ID 3,
   `Isolation UAT: verify dedicated branch and worktree`
3. **Work Item UUID:** `f4939868-ea63-44a9-b166-731e765b972e`
4. **Analysis:** revision 1, accepted
5. **Plan revision 1:** superseded
6. **Plan revision 2:** approved against exact SHA-256
   `4a1c6a06b23a95135573b9bedc9679bcaebb5eaf428251d76e56cf1b1e31de01`
7. **Environment:** `Isolation UAT Test`, disposable, non-production,
   `trusted_dev`
8. **Execution host:** `sabry3-precision-5540.tailcf9988.ts.net`
9. **Main worktree:** `/srv/devhub-uat/manual/petspot-uat`
10. **Worker Git common directory:**
    `/srv/devhub-uat/repos/petspot-uat.git`
11. **Isolated worktree:**
    `/srv/devhub-uat/worktrees/petspot-uat/DW-3`
12. **Execution branch:**
    `devhub/DW-3-isolation-uat-verify-dedicated-branch-and-worktree`
13. **Worker identity:** `devworker`, UID/GID `1001:1001`, no supplementary
    groups, sudo denied, Docker socket denied
14. **Base and final HEAD:**
    `5a7f1e1404dbbc1efeacc1a1bcaea3021d7cd7ae`

## Required results

| Verification | Result |
|---|---|
| Scenario designed before execution | PASS |
| Exact approved Plan revision 2 | PASS |
| Workspace confirmation reviewed in UI | PASS |
| Worker-owned branch/worktree creation | PASS |
| Restricted identity | PASS |
| Policy hash | PASS — `25554346d432bc2c0c8287db2a3859d589bc17dfe4c5ebf1e2f238088e6348a9` |
| Execution contract hash | PASS — `3170741d4453ab791bf50cb455783a09336dcb0a66dbca4b41d18281ed913379` |
| Open-in-Cursor target resolution | PASS — manifest targeted the isolated path |
| Main branch unchanged | PASS — `main` before/after |
| Main HEAD unchanged | PASS |
| Main dirty digest unchanged | PASS |
| Marker exists only in isolated worktree | PASS |
| Plan progress P1–P3, current P4 | PASS |
| Pause | PASS |
| Immutable checkpoint | PASS |
| Resume Brief | PASS — same path, branch, Plan hash, and policy-bound workspace |
| Concurrent writer | PASS — denied |
| Stale lease | PASS — fenced |
| Policy drift | PASS — denied, then exact policy restored |
| Contract drift | PASS — denied, then exact contract restored |
| Review Required | PASS |
| Automatic commit | NONE |
| Automatic push / PR / merge | NONE |
| Deployment / restart / Docker | NONE |
| Release | PASS |
| Dirty cleanup request | PASS — denied; references preserved |
| Final workspace | `released`, `changed=1` |

## Git and filesystem result

Actor A's branch, HEAD, and SHA-256 status digest were byte-for-byte identical
before and after branch/worktree creation:

- branch: `main`
- HEAD: `5a7f1e1404dbbc1efeacc1a1bcaea3021d7cd7ae`
- dirty digest:
  `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`

The isolated branch remained at Base HEAD with zero commits after Base HEAD and
one untracked `UAT_ISOLATION_MARKER.txt`. The marker was absent from Actor A's
worktree. The worker worktree was owned by `devworker:devworker` with mode
`0770`; no path escaped `/srv/devhub-uat/worktrees`.

## Negative tests

All 17 requested negative cases passed. The mapping from each case to its UI or
automated evidence is in `NEGATIVE_TEST_MATRIX.md`. Important visible failures:

- concurrent writer: `17_concurrent_writer_rejected.png`;
- policy drift: `18a_policy_drift_rejected.png`;
- execution-contract drift: `18_policy_contract_drift_rejected.png`;
- dirty cleanup: `22_cleanup_dirty_blocked.png`.

## Automated results

- **Playwright:** 1 scenario passed in 2.4 minutes.
- **Full module suite:** 52 tests, 0 failures, 0 errors.
- **Dedicated isolation/security suite:** 11 tests, 0 failures, 0 errors.
- **IDE diagnostics:** no errors in changed Python/TypeScript files.

## Evidence

Evidence root:

`dev_session_hub/docs/uat/isolation_worktree_20260719/`

Contents include:

- `UAT_SCENARIO.md`
- `UAT_REPORT.md`
- `NEGATIVE_TEST_MATRIX.md`
- 24 PNG screenshots (the 23 required names plus one separate policy-drift image)
- `git_verification.txt`
- `filesystem_verification.txt`
- `backend_verification.txt`
- `git_main_before.txt`
- `git_main_after.txt`
- `git_worker_after_marker.txt`
- `no_automatic_git_or_deploy.txt`
- `playwright_uat.spec.ts`
- `playwright_execution.log`
- `module_test_execution.log`
- `security_test_execution.log`

The canonical 695-line Playwright source is
`tests/playwright/dev_hub_isolation_uat.spec.ts`, SHA-256
`f075ec0eecec18464da943c85e187e18081c496b35049b7cfde0069a4e7171f0`.

No secret, token, `.env`, private key, production payload, or file-content diff
is included.

## Remaining constraints

There is no blocker for the narrowly bounded Phase 5 pilot below. These
constraints remain mandatory:

1. `master-ts` remains production-bearing and forbidden for worker execution.
2. Use only the reviewed non-production Precision host and restricted
   `devworker`.
3. The managed one-click launcher remains disabled; use the explicit,
   hash-bound Cursor workspace target until a pinned helper receives separate
   review.
4. Keep commit, push, PR, merge, deployment, restart, Docker, and external
   communication under separate human approval.
5. Preserve the dirty UAT branch/worktree until this evidence is reviewed;
   cleanup was intentionally denied.

## Recommended Phase 5 pilot scope

Run exactly one low-risk, test-only Work Item on the same non-production host:

- one repository and one concurrent `devworker`;
- a newly approved five-step Plan with exact hashes;
- one dedicated `devhub/DW-*` branch/worktree;
- a harmless documentation or fixture-only change;
- pause/checkpoint/resume once;
- mandatory `review_required` handoff;
- no autonomous commit, push, PR, merge, deployment, restart, Docker action, or
  external message;
- stop the pilot immediately on path, identity, lease, plan, policy, contract,
  or main-worktree drift.

Do not start that pilot from this UAT task.

Is Dedicated Branch + Isolated Worktree execution fully UAT-validated and ready for the Phase 5 Dev Worker pilot: YES
