# First Controlled Phase 5 Dev Worker Pilot

## Purpose

Prove that one restricted Dev Worker can execute an exact approved, test-only
implementation in a dedicated worktree, with lease fencing and immutable
checkpoints, and stop at `review_required`.

This scenario was written before pilot execution. It does not authorize commit,
push, PR creation, merge, deployment, service restart, Docker control,
Production access, external messaging, OpenProject completion, or cleanup.

## Pilot task

Add a small Python `unittest` contract for the disposable PetSpot fixture
README. The test protects the fixture's explicit test-only identity and ensures
the expected title remains present. This is a real automated-test addition with
no Production/runtime behavior.

Explicit file allowlist:

- `tests/__init__.py`
- `tests/test_fixture_readme.py`

All other paths are denied. In particular: `.git`, `.env`, credentials,
deployment files, Docker files, SSH configuration, databases, backups, and
runtime/service configuration.

## Actors and target

- Human controller: Sabry/Administrator
- Restricted worker: OS identity `devworker`, UID/GID `1001:1001`
- Project: PetSpot Isolation UAT
- Repository: PetSpot worker-owned disposable fixture
- Environment: Isolation UAT Test, non-production
- Base branch: `main`
- Base HEAD: `5a7f1e1404dbbc1efeacc1a1bcaea3021d7cd7ae`
- Main/manual worktree: `/srv/devhub-uat/manual/petspot-uat`
- New worktree: `/srv/devhub-uat/worktrees/petspot-uat/DW-<new-id>`
- New branch: generated `devhub/DW-<new-id>-phase5-pilot-*`

The preserved dirty UAT workspace `DW-3` is out of scope and must remain
untouched.

## Approved five-step plan

1. **P1 — Inspect fixture contract:** inspect only `README.md`, confirm the
   registered workspace, branch, Base HEAD, identity, hashes, lease, and file
   allowlist.
2. **P2 — Implement test-only contract:** create exactly the two allowlisted
   test files.
3. **P3 — Run targeted test:** run
   `python3 -m unittest -v tests.test_fixture_readme`, record result, checkpoint,
   then Pause.
4. **P4 — Resume and run regression:** reacquire a fenced lease for the same
   worktree, reject a second writer, and run
   `python3 -m unittest discover -s tests -v`.
5. **P5 — Prepare human review:** validate changed files, main-worktree
   invariants, test evidence, and produce the review handoff.

Every step follows:

`validate lease → validate plan/policy/contract → validate workspace → execute
bounded step → capture result → update status → immutable checkpoint`.

## Preconditions

1. Work Item has an accepted Analysis and exact approved Plan revision.
2. Repository, environment, machine, worker identity, Base Branch/HEAD, policy,
   and execution contract pass existing isolation controls.
3. A new clean dedicated worktree is created; `DW-3` is not reused.
4. Manual worktree branch, HEAD, and status digest are captured.
5. Worker has no sudo, Docker socket, Production secret, or manual-worktree
   write access.
6. Lease token is held only in process memory and excluded from evidence.

## Execution and expected evidence

| Stage | Expected result | Screenshot |
|---|---|---|
| Work Item | New pilot Work Item is approved | `01_pilot_work_item.png` |
| Analysis | Analysis is accepted | `02_analysis_accepted.png` |
| Plan | Revision is exactly approved | `03_exact_approved_plan.png` |
| Preparation | New pending workspace shows exact target | `04_workspace_preparation.png` |
| Physical target | New branch/worktree is ready | `05_dedicated_branch_worktree.png` |
| Identity | `devworker` and restricted target are visible/verified | `06_worker_identity.png` |
| Policy | Stored policy hash matches recomputation | `07_policy_validation.png` |
| Contract | Stored contract hash matches recomputation | `08_contract_validation.png` |
| Lease | Exclusive lease is active; token is redacted | `09_worker_active.png` |
| Progress | P1–P3 complete, P4 current | `10_plan_progress.png` |
| Pause | Workspace is paused and prior lease fenced | `11_pause.png` |
| Checkpoint | Immutable P3 checkpoint contains branch/HEAD/digest/steps/tests | `12_checkpoint.png` |
| Resume brief | Same target and hashes are shown | `13_resume_brief.png` |
| Resume | Same worktree is active under a new fencing version | `14_resume.png` |
| Negative control | Second writer is denied | `15_concurrent_writer_rejected.png` |
| Tests | Targeted and regression tests pass | `16_tests_completed.png` |
| Handoff | Changed files, tests, and warnings are recorded | `17_review_handoff.png` |
| Stop gate | Workspace is `review_required`; worker is stopped | `18_review_required.png` |

## Pass criteria

- Worker effective identity and target are exact.
- Every worker mutation is preceded by lease, plan, policy, contract, and
  physical workspace validation.
- Only the two allowlisted test files change.
- Targeted and regression test commands pass.
- Pause creates a checkpoint; Resume uses the same worktree and new fencing
  version.
- Concurrent writer fails without modifying files or plan progress.
- Manual worktree branch, HEAD, and dirty digest remain unchanged.
- Worker creates no commit and performs no push, PR, merge, deployment,
  service restart, Docker operation, Production access, or external message.
- Final workspace is `review_required`, with branch/worktree retained.

Any boundary violation fails and blocks the pilot. No automatic repair or
cleanup is permitted.
