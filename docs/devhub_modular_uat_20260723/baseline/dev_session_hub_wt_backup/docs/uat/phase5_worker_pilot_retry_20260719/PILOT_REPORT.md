# Phase 5 Dev Worker Defect Fix and Re-Attempt Report

## Result

**PASS.** The new bounded worker reached `review_required`, revoked its lease,
and stopped for human review. No autonomous capability was added.

DW-4 and Workspace 8 remain blocked, unchanged historical evidence.

## 1. Exact DW-4 root cause

DW-4 produced valid porcelain v1 `-z` records:

- `?? tests/__init__.py`
- `?? tests/test_fixture_readme.py`

The first harness compared the complete status records, including their two
status columns and separator, to path-only allowlist entries. The actual
filesystem scope was correct, but the representation comparison caused a
false-positive rejection.

## 2. Parser implementation

The fix retains `git status --porcelain=v1 -z --untracked-files=all` and adds a
strict byte parser. It:

- parses the two XY status columns explicitly;
- requires the documented space separator and terminal NUL;
- treats rename/copy destination as the first path and source as the following
  NUL record;
- decodes paths using strict UTF-8;
- returns repository-relative path values separately from status metadata;
- retains an escaped, sanitized status audit summary;
- rejects malformed, unknown, non-terminated, or undecodable records.

No broad `strip`, slicing, regular-expression filename extraction, or policy
relaxation is used.

## 3. Supported status formats

- untracked `??`
- ignored `!!` when supplied
- index/worktree modified, including `M `, ` M`, and `MM`
- added `A `
- index/worktree deleted, including `D ` and ` D`
- type changed
- renamed
- copied
- all documented unmerged combinations: `DD`, `AU`, `UD`, `UA`, `DU`, `AA`,
  and `UU`

Unknown status combinations fail closed.

## 4. Path normalization and safety

The policy engine receives only canonical repository-relative paths.

It rejects:

- empty or absolute paths;
- empty, `.` or `..` components;
- traversal and repository-root escape;
- symlink-resolved escape;
- invalid UTF-8;
- malformed records;
- any destination outside the exact allowlist.

Rename/copy source and destination are both validated and both must be
allowlisted for this worker policy.

## 5. Tests added

A dedicated 15-test matrix covers all requested status prefixes, ignored
records, rename/copy directions, conflicts, spaces, unusual valid names,
nested paths, traversal, absolute paths, symlink escape, malformed records,
undecodable records, disallowed paths, and mixed allowed/disallowed changes.

The explicit regression
`test_dw4_first_phase5_pilot_untracked_allowlist_regression` reproduces the two
DW-4 `??` records and verifies exact normalized paths pass.

The separate
`test_mixed_allowed_and_disallowed_changes_fail_closed` fixture supplies an
allowed Test path plus `deploy/disallowed.conf`; it verifies rejection before
the successful pilot workspace is touched.

## 6. Pre-attempt test results

- Parser/allowlist and DW-4 regression: **15/15 passed**
- Phase 5 worker lease/fencing control: **1/1 passed**
- Full Dev Hub module suite: **68/68 passed**
- Isolation/security suite: **12/12 passed**
- Failures/errors: **0**

The new pilot was not started until all suites passed.

## 7. New pilot identity

- Work Item: **DW-5**
- Analysis: ID 3, accepted
- Approved Plan: ID 4, five steps
- Plan hash:
  `8d1849f4866cef4a56b7d39ff7fef302255bf056ea0fe735968be82a7e95b734`
- Workspace: **ID 9**
- Policy hash:
  `25554346d432bc2c0c8287db2a3859d589bc17dfe4c5ebf1e2f238088e6348a9`
- Execution contract hash:
  `8b82cff8fc927a34c738d5952bf153a8aaf0fb0ec8ed3deb36af483aa8280170`
- Branch:
  `devhub/DW-5-phase5-retry-add-fixture-readme-contract-test`
- Worktree: `/srv/devhub-uat/worktrees/petspot-uat/DW-5`
- Worker: `devworker`, UID/GID `1001:1001`
- Base/current HEAD:
  `5a7f1e1404dbbc1efeacc1a1bcaea3021d7cd7ae`

## 8. Worker execution

All five exact Plan steps completed:

1. P1 validated identity, controlled references, Plan/policy/contract hashes,
   branch, path, Base HEAD, and README.
2. P2 created exactly two files and passed strict normalized scope validation.
3. P3 ran targeted tests: **2/2 passed**.
4. P4 paused, created an immutable checkpoint, fenced lease version 1,
   resumed the same worktree under lease version 2, and rejected a second
   writer.
5. P5 ran regression discovery: **2/2 passed**, verified main-worktree
   isolation, and produced the Review Handoff.

Worker-changed files:

- `tests/__init__.py`
- `tests/test_fixture_readme_retry.py`

Raw status categories were `??`, `??`; normalized policy paths exactly matched
the allowlist.

## 9. Isolation and negative controls

- Mixed allowed/disallowed parser fixture: rejected.
- Concurrent writer against Workspace 9: rejected.
- Main worktree branch, HEAD, and clean digest: unchanged.
- DW-3: preserved.
- DW-4 Work Item, Workspace 8, branch, dirty files, and blocked state:
  preserved.
- Worker sudo: denied.
- Docker socket: denied.
- Production access: none.
- Commits ahead of Base HEAD: 0.
- Push/PR/merge/deployment/external messages/cleanup: none.

## 10. Review gate

- Workspace 9 state: `review_required`
- Worker status: `stopped_at_review_required`
- Work Item phase: `ready_for_review`
- Lease: revoked and token cleared
- Secure retry lease state file: removed
- Final checkpoint: agent handoff, tests **4/4 passed**
- Completion report: `ready_review`
- Deployment status: `not_deployed`

## 11. Playwright and evidence

The lifecycle execution completed all worker stages and captured screenshots
1–12. Its final assertion initially looked for `worker_status` while the field
was hidden on another notebook tab, after the worker had already stopped at
`review_required`. The selector was corrected to open the Validation and Lease
tab.

A separate read-only final Playwright validation then passed **1/1**, verified
the lifecycle/events/checkpoints/Git invariants, and captured screenshot 13.
No worker action or workspace mutation was repeated.

- Screenshots: **13**
- Evidence:
  `dev_session_hub/docs/uat/phase5_worker_pilot_retry_20260719/`
- Final Playwright validation: **PASS**

## 12. Remaining blockers

No blocker remains for this bounded implementation pilot. Human review of the
two uncommitted Test files is still mandatory.

The only recommended next capability is **Human-approved Git Commit**. It is
the smallest next increment because it preserves an explicit human gate before
creating repository history. It has not been implemented or exercised.

Did the Phase 5 Dev Worker re-attempt safely reach Review Required: YES
