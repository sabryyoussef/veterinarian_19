# Phase 6 Human-Approved Merge Stop-Gate Report

## Result

Implementation, automated controls, separate Merge App credential validation,
and the approval-only Playwright stop-gate passed. PR #2 remains open and
unmerged. Final confirmation was cancelled before any remote merge. No merge
record and no deployment were created.

## Credential

1. Protected PEM path: `/srv/devhub/credentials/github/merge-app-4341059.pem`
2. Mode/owner: `600` / `devworker:devworker`
3. Broker reference: `/srv/devhub/credentials/github/mint-devhub-merge-token`
4. Profile reference: `/srv/devhub/credentials/github/merge-gh-profile`
5. App slug / ID / installation: `sabry-uat-merge-agent` / `4341059` / `147666583`
6. Repository restriction: only `sabryyoussef/veterinarian_19`
7. Permissions: Metadata read, Pull requests read, Contents write, Checks read,
   Commit statuses (`statuses`) read
8. Temporary installation token revoked after validation
9. Raw private key never printed, logged, committed, or stored in Dev Hub

## Stop-gate outcomes

1. Workspace: `14` (DW-11 / merge readiness on existing PR #2 workspace)
2. State after cancel: `merge_approved`
3. Requester: `devhub-merge-requester` (non-Administrator)
4. Approver: `admin` (distinct Administrator)
5. Exact head SHA: `24c7eef5e169016a94794f8e30b6934e2aabd3b8`
6. Exact base: `staging` @ `66344b2e09e2049c39942114029253e919bc6709`
7. Method: `squash`
8. Required check: GitGuardian Security Checks (App `46505`) completed/success
9. Merge approval record: `1` with idempotency key bound
10. Terminal merge record count: `0`
11. Playwright: **1/1 passed** (~1.1 min on UAT localhost); **10 screenshots**
12. Automated tests: lifecycle **71/71**, security **20/20**, full module **106/106**
13. Remote PR #2: open, merged=false, auto_merge=null
14. Deployment: none

## Remaining blockers before live merge

1. Fresh Administrator authorization after a new remote preflight (stop-gate
   cancel is not live-merge authority).
2. Live execution must use the exact squash PUT path only; no re-run from a
   stale approval if head/base/checks/credential digests drift.
3. Implementation remains uncommitted by design for this readiness gate.

## Evidence

- `UAT_SCENARIO.md`
- `automated_test_results.txt`
- `playwright_execution.log`
- `sanitized_remote_preflight.txt`
- `sanitized_remote_verification.txt`
- `screenshots/01_…png` through `10_…png`
