# Dev Hub Isolated Worktree UAT Scenario

## Scenario

**Name:** PetSpot Isolation UAT — exact-plan worker workspace  
**Business purpose:** Prove that a realistic Dev Hub Work Item can be prepared,
opened, paused, resumed, reviewed, and released in a worker-owned Git worktree
without changing Sabry's main worktree or crossing any production boundary.

This scenario is designed before execution. It must fail closed during
preflight if a genuine non-production execution machine and restricted worker
identity are not available. The production-bearing `master-ts` record must not
be relabelled or bypassed.

## Actors

- **Actor A — Sabry/manual developer:** owns and may continue using the main
  fixture worktree. Reviews and confirms Dev Hub UI actions.
- **Actor B — restricted devworker:** owns the dedicated bare repository and
  task worktree. It has no sudo, Docker group/socket, production SSH keys,
  production database credentials, secret-store access, or access to Sabry's
  production worktrees.

## Preconditions

1. A dedicated non-production execution machine is registered as
   `trusted_dev`, `production = false`, with pinned SSH identity.
2. `devworker` exists on that machine and passes UID/group/access checks.
3. The worker-owned roots exist:
   - `/srv/devhub-uat/repos/`
   - `/srv/devhub-uat/worktrees/`
4. A dedicated bare fixture repository is owned by `devworker`; it contains no
   production runtime files, ignored secrets, filestore, logs, backups, or
   Docker volumes.
5. A separate manual fixture clone exists for Actor A. No production or Test
   service executes from either fixture worktree.
6. A disposable Odoo database and isolated HTTP port host the UAT UI.
7. Playwright Chromium is installed. Screenshots contain no credentials.
8. The Dev Hub repository is classified `safe_for_isolated_worktree` and
   explicitly allows agent execution only for this fixture.
9. The execution policy denies production and deployment, requires
   confirmation, and allows bounded development/test actions only.

## Test data

- **Project:** PetSpot Isolation UAT
- **Work Item:** `Isolation UAT: verify dedicated branch and worktree`
- **Environment:** Isolation UAT Test (`test`, non-production)
- **Repository:** worker-owned PetSpot fixture
- **Main worktree:** `/srv/devhub-uat/manual/petspot-uat`
- **Worker Git common directory:** `/srv/devhub-uat/repos/petspot-uat.git`
- **Execution worktree:** `/srv/devhub-uat/worktrees/petspot-uat/DW-<id>`
- **Execution branch:** `devhub/DW-<id>-isolation-uat-verify-dedicated-branch-and-worktree`
- **Worker identity:** `devworker`
- **Harmless change:** untracked `UAT_ISOLATION_MARKER.txt` containing a
  timestamp-free fixed test marker; never commit it.

### Accepted analysis

The UAT must prove independent physical worktrees, exact-plan and policy
binding, main-worktree invariants, same-worktree resume, fenced concurrent
writers, and human-controlled review/cleanup. Production, deployment,
communication, and autonomous business-code implementation are out of scope.

### Plan revision 1

Create a complete five-step plan, submit it, then supersede it without
approval. It must not remain executable.

### Exact approved plan revision 2

1. **P1 — Validate isolation boundaries:** verify repository, environment,
   worker identity, Base HEAD, generated branch/path, policy hash, and contract
   hash.
2. **P2 — Create harmless fixture marker:** create the untracked marker only in
   the isolated worker worktree.
3. **P3 — Prove main-worktree invariants:** verify Actor A branch, HEAD, dirty
   digest, and marker absence.
4. **P4 — Prove lifecycle fencing:** pause/checkpoint, resume the same worktree,
   reject a concurrent writer, stale lease, and policy/contract drift.
5. **P5 — Human review and release:** reach `review_required`, prove no
   commit/push/merge/deploy, release, and prove dirty cleanup denial.

Revision 2 alone is submitted and approved against its exact SHA-256 plan hash.

## Test actions, expected results, and evidence

| # | Action | Expected result | Required evidence |
|---|---|---|---|
| 1 | Create the disposable project, repository, environment, policy, and Work Item. | Work Item is `received` on a non-production fixture only. | `01_work_item_before.png` |
| 2 | Triage/register, create Analysis revision 1, and accept it. | Analysis status is `accepted`; its hash is visible. | `02_analysis_accepted.png` |
| 3 | Create complete Plan revision 1 with five steps, then create a new revision. | Revision 1 is `superseded`; it cannot authorize execution. | UI assertion and audit log |
| 4 | Edit Plan revision 2 only as required, submit, and approve its exact hash. | Revision 2 is `approved`; immutable approval stores the same revision/hash. | `03_plan_revision_2_approved.png`, `04_exact_plan_hash_approval.png` |
| 5 | Assert workspace preparation eligibility. | Work Item phase is `approved`; accepted Analysis and exact approved Plan are current. | Playwright assertions |
| 6 | Capture Actor A branch, HEAD, porcelain-status counts, and status digest. | Sanitized before-snapshot is stored; no file content is captured. | `08_main_worktree_before.png`, `git_main_before.txt` |
| 7 | Open the Work Item and click **Prepare Execution Workspace**. | No Git write occurs; one `pending_confirmation` proposal opens. | `05_prepare_workspace_confirmation.png` |
| 8 | Review repository, Base Branch/HEAD, plan revision/hash, policy hash, contract hash, branch, path, identity, and production policy. | Every displayed value matches registered records and generated policy. | Playwright field assertions |
| 9 | Confirm preparation as Actor A. | Only the worker-owned helper may create the exact branch/worktree; state becomes `ready`. | `06_workspace_created.png` |
| 10 | Validate the Execution Workspace section. | Correct repository, Base HEAD, branch, path, worker, policy/contract hashes, and `ready` state. | `07_execution_workspace_details.png`, `09_workspace_validation.png` |
| 11 | Re-capture Actor A branch, HEAD, dirty digest. | All equal the before-snapshot. | `10_main_worktree_unchanged.png`, `git_main_after.txt` |
| 12 | Resolve **Open in Cursor** target without launching an autonomous worker. | URI targets the isolated worktree, never the main worktree. | Playwright/backend assertion |
| 13 | As `devworker`, create the harmless untracked marker. | Marker exists only under the execution worktree; isolated dirty count becomes one. | `11_isolated_change_only.png`, `git_worker_after_marker.txt` |
| 14 | Verify marker absence from Actor A worktree. | Main worktree remains unchanged. | Filesystem assertion |
| 15 | Mark P1, P2, and P3 done; mark P4 current. | Plan progress is 3/5 and P4 is current. | `12_plan_progress_3_of_5.png` |
| 16 | Start a manual isolated session, then Pause. | Workspace/session are paused; an immutable checkpoint is created. | `13_pause_state.png` |
| 17 | Open checkpoint detail. | It binds workspace, branch, Base/current HEAD, dirty digest, completed P1–P3, current P4, and next action. | `14_checkpoint_detail.png` |
| 18 | Resume. | Resume Brief opens and references the exact same worktree, branch, plan revision/hash, policy hash, and current step. | `15_resume_brief.png`, `16_resume_same_worktree.png` |
| 19 | Attempt a second active writer/session for the same workspace. | Concurrent writer is rejected; first ownership remains authoritative. | `17_concurrent_writer_rejected.png` |
| 20 | Attempt a stale lease token/version. | Fencing rejects it without changing workspace state. | Backend assertion/log |
| 21 | In a transaction-safe negative fixture, change the effective policy after proposal. | Validation/resume fails closed on policy hash mismatch. | `18_policy_contract_drift_rejected.png` |
| 22 | In a transaction-safe negative fixture, present a mismatched execution-contract hash. | Validation fails closed; no launcher or Git write occurs. | UI/backend assertion |
| 23 | Complete P4 and P5, then mark workspace `review_required`. | Human review is required; no downstream Git/deployment action is triggered. | `19_review_required.png` |
| 24 | Verify local refs, remote refs, Git log, and deployment records. | No automatic commit, push, PR, merge, deployment, restart, or Docker action exists. | `20_no_automatic_git_or_deploy.png`, sanitized verification files |
| 25 | Release workspace. | State is `released`; branch/worktree remain present for audit. | `21_release_state.png` |
| 26 | Request cleanup while marker remains uncommitted. | Cleanup is denied as dirty; no worktree/branch removal occurs. | `22_cleanup_dirty_blocked.png` |
| 27 | Open Work Item audit/history. | Preparation, validation, pause, resume, review, and release events are preserved. | `23_final_audit.png` |

## Required negative matrix

The Playwright scenario covers the major visible failures; dedicated Odoo tests
and backend assertions cover all remaining fail-closed cases:

1. no approved plan;
2. superseded approval;
3. production environment;
4. production-bearing execution target;
5. unsafe/path-traversal/symlink path;
6. existing branch collision;
7. existing worktree collision;
8. concurrent writer;
9. stale lease;
10. policy hash mismatch;
11. execution-contract hash mismatch;
12. missing worktree on Resume;
13. dirty cleanup;
14. automatic commit denied;
15. automatic push denied;
16. automatic merge denied;
17. deployment denied.

## Pass criteria

The UAT passes only if:

- all 27 actions produce the expected result;
- all required Playwright assertions pass;
- all 23 screenshots exist and are readable;
- backend, Git, ownership, and filesystem evidence agrees with the UI;
- Actor A branch, HEAD, and dirty digest are identical before/after preparation;
- the marker exists only in the worker worktree;
- policy and execution-contract hashes remain exact;
- all negative tests fail closed;
- the full module and dedicated security tests finish with zero failures/errors;
- no production path/service, commit, push, PR, merge, deployment, restart,
  Docker action, or external communication occurs.

Any missing prerequisite, screenshot, assertion, or cross-boundary ambiguity is
a UAT failure, not a waiver.

## Rollback and cleanup

1. Stop only the disposable UAT Odoo process; do not restart managed services.
2. Preserve the dirty worktree, branch, workspace IDs, and sanitized evidence
   until the report is reviewed.
3. After separate human cleanup approval, remove the marker or preserve it as
   evidence, verify no active session/lease, then remove the fixture worktree
   without force.
4. Delete the fixture branch only after confirming it has no required commits
   and obtaining separate human approval.
5. Drop only the disposable UAT database.
6. Never alter Production/Test service definitions, Production data, or the
   production-bearing main checkout as part of cleanup.
