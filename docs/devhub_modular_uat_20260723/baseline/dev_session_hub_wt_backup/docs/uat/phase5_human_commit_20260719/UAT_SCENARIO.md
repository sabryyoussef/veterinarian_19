# Human-Approved Local Git Commit UAT

## Purpose

Validate exactly one new Phase 5 capability: a Dev Hub manager reviews an
isolated Test-only change, records an immutable exact-state approval, confirms
again, and creates one local commit. Push, PR, merge, deployment, Production,
branch deletion, and worktree cleanup remain prohibited.

## New bounded pilot

- New Work Item and Workspace; DW-3, DW-4, and DW-5 remain untouched.
- Worker: `devworker`, UID/GID `1001:1001`.
- Environment: disposable non-production `Isolation UAT Test`.
- Exact worker file allowlist:
  - `tests/__init__.py`
  - `tests/test_human_commit_contract.py`
- Commit author/committer: `Dev Worker <devworker@devhub.invalid>`.
- Human approver: Sabry/Administrator in Dev Hub.

## Worker plan

1. Inspect the fixture and controlled execution references.
2. Create exactly the two allowlisted Test files.
3. Run targeted tests.
4. Pause, checkpoint, resume the same worktree, and reject a concurrent writer.
5. Run regression tests, prepare Review Handoff, and stop at
   `review_required`.

## Human commit flow

1. Open `review_required`.
2. Click **Review Changes** and inspect normalized paths, Git status, tests,
   Plan/checkpoint progress, and handoff.
3. Click **Approve Git Commit**.
4. Review/edit the bounded commit message and exact binding.
5. Click **Record Exact-State Commit Approval**. No commit occurs.
6. Verify immutable approval record and `commit_approved`.
7. Click **Create Approved Commit**.
8. Recheck branch, HEAD, dirty digest, changed-files digest, message hash, and
   binding hash.
9. Click **Confirm and Create One Local Commit**.
10. Verify exactly one commit, exact parent/files, clean worktree, unchanged
    main worktree, and final `committed_reviewed`.
11. Stop. Do not push or perform any later lifecycle action.

## Negative controls

Automated tests deny commit without approval, outside `review_required`, after
HEAD/dirty/content/file-set/Plan/policy/contract drift, with an active lease or
concurrent writer, against Production, or when an unexpected path appears.
They also verify rejection invalidates approval and returns to implementation.

## Required screenshots

1. `01_review_required.png`
2. `02_review_changes.png`
3. `03_commit_approval.png`
4. `04_commit_confirmation.png`
5. `05_commit_success.png`
6. `06_commit_sha.png`
7. `07_post_commit_state.png`

## Pass criteria

- Approval is immutable and bound to exact reviewed state and message hash.
- Approval alone creates no commit.
- Final confirmation creates exactly one local commit with only reviewed files.
- Commit parent equals approved pre-commit HEAD.
- Worktree is clean; main worktree and prior UAT workspaces are unchanged.
- No push, PR, merge, deployment, Production access, service control, Docker,
  branch deletion, or cleanup occurs.
- Final state is `committed_reviewed`.
