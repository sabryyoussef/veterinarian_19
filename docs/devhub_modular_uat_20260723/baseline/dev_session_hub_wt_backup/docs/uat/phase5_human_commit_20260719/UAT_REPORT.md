# Human-Approved Git Commit UAT Report

## Result

**PASS.** One exact-state human approval produced exactly one local commit in
the registered isolated worktree. Execution stopped at `committed_reviewed`.
No Push, PR, Merge, Deployment, Production access, branch deletion, or
worktree cleanup occurred.

## 1. Work Item and Workspace

- Work Item: **DW-6**, `Add human-approved commit contract test`
- Workspace: **ID 10**
- Branch: `devhub/DW-6-add-human-approved-commit-contract-test`
- Worktree: `/srv/devhub-uat/worktrees/petspot-uat/DW-6`
- Worker: `devworker`, UID/GID `1001:1001`
- Environment: disposable non-production `Isolation UAT Test`

The worker completed P1–P5, targeted tests **2/2**, regression tests **2/2**,
Pause/Resume, concurrent-writer rejection, and stopped at `review_required`.

## 2. Human Review

The Review Changes UI showed:

- exact Work Item, Workspace, branch, Base/current HEAD;
- normalized changed files and sanitized Git status;
- dirty and content-aware changed-files digests;
- Plan/checkpoint progress;
- tests and results;
- worker Review Handoff.

Reviewed files:

- `tests/__init__.py`
- `tests/test_human_commit_contract.py`

No unrestricted file contents or secrets were displayed.

## 3. Exact-State Approval

- Approval record: **ID 1**
- Approver: **Administrator** (`res.users` ID 2)
- Approved at: `2026-07-19 13:20:45 UTC`
- Pre-commit HEAD:
  `5a7f1e1404dbbc1efeacc1a1bcaea3021d7cd7ae`
- Dirty digest:
  `c599a77bd1eb570193dc529f0d8fba2661e5fe3c6b89e7d939cf6ec4cb61a321`
- Changed-files/content digest:
  `67729be729cf0eca64c71d1e438042727babd2adb22908358632a546c082e080`
- Commit-message hash:
  `1f84377cda69cc7fc8b7c05acd536cc08346ff31c9379fe68fce8d0c29312dfd`
- Approval binding hash:
  `bd6b1af97db6fba18aec76e4d40b6cc9278bc1e74490500f1a30bb92613e685d`

The immutable record also binds Plan ID/hash, policy hash, execution contract
hash, branch, approver, timestamp, checkpoint, tests, and main-worktree
snapshot.

Recording approval moved the Workspace to `commit_approved` but created no
commit. A separate final confirmation wizard revalidated the complete binding.

## 4. Commit Message and Identity

Commit message:

```text
[DW-6] Add human commit contract test

Work Item: DW-6
Approved Plan revision: 1
Tests: targeted 2/2 and regression 2/2 passed.
```

- Author/committer: `Dev Worker <devworker@devhub.invalid>`
- Human approver: Administrator, recorded separately in the immutable approval
  and commit audit record.
- No authorship was attributed to the approver.

## 5. Commit Result

- Commit SHA:
  `764a9ff0e10b3ff096860d9dc6c0424597152a85`
- Parent SHA:
  `5a7f1e1404dbbc1efeacc1a1bcaea3021d7cd7ae`
- Commit time: `2026-07-19 13:20:57 UTC`
- Commits created: **exactly 1**
- Files committed:
  - `tests/__init__.py`
  - `tests/test_human_commit_contract.py`
- Worktree after commit: clean
- Commits ahead of Base HEAD: 1
- Immutable commit record: ID 1
- Commit audit hash:
  `e12724f528fb836ba6965a538f245a0349d84f649cdc6e91d16319861d932779`
- Approval state: consumed by the recorded commit
- Final Workspace state: `committed_reviewed`
- Work Item remains `ready_for_review`; it was not marked completed, merged, or
  deployed.

Exact staging used `git add -- <reviewed paths>`. `git add -A` was not used.
The staged paths and staged content digest were rechecked before commit.

## 6. Main and Prior Workspace Protection

- Main worktree branch before/after: `main`
- Main HEAD before/after:
  `5a7f1e1404dbbc1efeacc1a1bcaea3021d7cd7ae`
- Main dirty digest before/after:
  `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`
- DW-3: preserved
- Workspace 8 / DW-4: remained `blocked`, dirty evidence unchanged
- Workspace 9 / DW-5: remained `review_required`, dirty evidence unchanged

## 7. Negative Tests

All required commit controls passed:

1. Commit without approval: denied.
2. Commit outside `review_required`: denied.
3. Dirty digest drift: denied.
4. HEAD drift: denied.
5. Changed-files/content drift: denied.
6. Plan hash drift: denied.
7. Policy hash drift: denied.
8. Execution contract hash drift: denied.
9. Concurrent writer: denied.
10. Active worker lease: denied.
11. Production environment: denied.
12. Unexpected file: denied.
13. Main worktree: unchanged.
14. Push: none.
15. PR creation: none.
16. Merge: none.
17. Deployment: none.

The rejection test also verified that human rejection appends an immutable
approval event, creates a checkpoint, clears the current approval, and returns
the Workspace to implementation.

## 8. Automated and Playwright Results

- Parser/allowlist: **15/15 passed**
- Worker controls: **1/1 passed**
- Human commit controls: **9/9 passed**
- Full module: **77/77 passed**
- Combined security: **21/21 passed**
- Final human approval/commit Playwright: **1/1 passed**
- Screenshots: **7**

The initial lifecycle script safely completed the worker and reached
`review_required`, then encountered a read-only form/tab navigation race before
approval. A first continuation attempt selected the commit-message field before
opening its notebook tab; it timed out with no approval or commit. The corrected
continuation passed and performed the only approval and commit. These UI
selector failures caused no Git mutation.

## 9. No Remote or External Actions

- Git remotes in the isolated worktree: none
- Remote-ref digest before/after: unchanged
- Push: none
- PR: none
- Merge: none
- Deployment: none
- Production access: none
- External outbox count: unchanged
- Branch/worktree deletion or cleanup: none

## 10. Evidence

Evidence folder:

`dev_session_hub/docs/uat/phase5_human_commit_20260719/`

Includes scenario, report, seven screenshots, sanitized worker log, Git
before/after evidence, commit metadata, parser/worker/commit/module/security
test logs, Playwright logs, and canonical Playwright test hashes.

## 11. Remaining Blockers and Next Capability

No blocker remains for Human-Approved Git Commit.

The only recommended next capability is **Human-approved Push**. It was not
implemented or exercised.

Is Human-Approved Git Commit safely validated: YES
