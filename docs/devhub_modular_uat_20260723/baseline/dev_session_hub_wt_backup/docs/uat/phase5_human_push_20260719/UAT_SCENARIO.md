# Phase 5 Human-Approved Git Push UAT

## Purpose

Validate one explicitly human-approved, normal non-force Push of one reviewed
commit on one dedicated `devhub/*` branch to one registered non-production
local bare Git remote. Stop after remote reconciliation.

## New pilot

- New Work Item: DW-7 (created by `setup_fixture.py`)
- New isolated workspace and branch
- Worker adds only `tests/__init__.py` and
  `tests/test_human_push_contract.py`
- Human-approved local commit precedes Push
- Registered remote: `devhub-uat`
- Remote root: `/srv/devhub-uat/remotes`

## Human flow

1. Worker reaches `review_required`.
2. Human reviews and creates one exact local commit.
3. Workspace reaches `committed_reviewed`.
4. Human reviews the registered Push target and remote state.
5. Human records immutable exact-Push approval.
6. Human confirms Push in a second wizard.
7. Dev Hub pushes one explicit branch refspec.
8. Dev Hub reconciles all remote heads and tags.
9. Workspace reaches `pushed_reviewed`; execution stops.

## Pass criteria

Remote target HEAD equals the reviewed local commit; no other branch or tag
changes; local and main worktrees remain unchanged; no PR, merge, deployment,
Production access, force Push, cleanup, or branch deletion occurs.
