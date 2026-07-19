# Phase 5 Dev Worker Defect Fix and Re-Attempt

## Scope

Correct only Git porcelain v1 `-z` path parsing and rerun one bounded,
non-production, Test-only worker pilot. DW-4 and Workspace 8 remain immutable
failed-pilot evidence.

## Parser acceptance

- Parse the two XY status columns and NUL-delimited paths.
- Decode paths strictly as UTF-8.
- For rename/copy, parse destination then the separate source record.
- Normalize policy inputs to repository-relative paths.
- Reject malformed records, unknown status codes, absolute paths, traversal,
  repository/symlink escapes, undecodable paths, and every path outside the
  exact allowlist.
- Require rename/copy source and destination to be allowlisted.
- Preserve a separately escaped Git-status audit summary.

The dedicated matrix and DW-4 regression tests must pass before creating the
new pilot.

## New pilot

- New Work Item and Workspace; do not reuse DW-4 or Workspace 8.
- Worker: `devworker`, UID/GID `1001:1001`.
- Environment: disposable `Isolation UAT Test`.
- Explicit allowlist:
  - `tests/__init__.py`
  - `tests/test_fixture_readme_retry.py`
- No Production, commit, push, PR, merge, deployment, service control, Docker,
  sudo, external messaging, or cleanup.

## Approved plan

1. P1 — Inspect target Test files and validate controlled references.
2. P2 — Add the allowlisted README retry contract and pass normalized scope
   validation.
3. P3 — Run the targeted unittest.
4. P4 — Pause, checkpoint, resume the same worktree under a new fencing
   version, and reject a concurrent writer.
5. P5 — Run regression checks, verify main-worktree isolation, prepare Review
   Handoff, and stop at `review_required`.

Every mutation requires valid lease, Plan hash, policy hash, execution contract
hash, identity, branch, and worktree checks.

## Separate negative control

The parser test fixture supplies one allowed path plus
`deploy/disallowed.conf`. The normalized parser must identify both and reject
the set before any real pilot execution. This fixture is separate from the
successful workspace.

## Pass criteria

- Parser matrix, DW-4 regression, worker controls, full module, and security
  suites pass before retry.
- Only the two exact retry files change.
- Targeted and regression tests pass.
- Pause/Resume and concurrent-writer rejection pass.
- Main worktree and DW-3/DW-4 evidence remain unchanged.
- Final Workspace is `review_required`, lease cleared, worker stopped.
- No prohibited action occurs.
