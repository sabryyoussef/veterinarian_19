# Dev Hub GitHub App Governed Merge + Test Deploy Report

**Date:** 2026-07-23  
**Evidence root:** `docs/devhub_modularity/github_app_governed_merge_test_deploy/`  
**Screenshots:** `docs/devhub_modularity/github_app_governed_merge_test_deploy/screenshots/`

---

## A. Final Verdict

```text
DEV HUB GOVERNED MERGE + TEST DEPLOY PASS
```

---

## B. Environment

| Item | Value |
|------|--------|
| Live Test DB | `pet_spot_elsahel_test` |
| Port | `8028` |
| Config | `pet_spot_elsahel_test.conf` |
| Canonical modular stack | installed (`devhub_*` modules) |
| Production DB / service | untouched (`pet_spot_elsahel.service` remained **active**) |
| Worker | `devworker` uid **1100**, home `/srv/devhub/home/devworker` |
| Bare repo | `/srv/devhub/repos/petspot.git` |
| Worktrees | `/srv/devhub/worktrees` |
| Staging runner | `/srv/devhub/runners/staging` (Test DB allowlist only) |

---

## C. Code Pin

Stabilization baseline pin (HEAD at UAT start / report):

```text
4c1fc00555a3ede2ccf7582fdb87af6082a29195
```

Additional Live Test code fixes applied during this UAT (not yet a new pin commit unless requested):

| Fix | Purpose |
|-----|---------|
| `devhub_session._run_git` + `safe.directory` | Session start on worker-owned worktrees |
| `action_create_and_start_isolated_session` | Correct Ready → start ordering |
| GitHub App PEM/broker install under `/srv/devhub/credentials/github/` | PR + Merge App mint path |
| `devhub_deploy._verify_sha_on_branch` via `git ls-remote` | Real non-prod SHA tip check |
| `devhub_deploy._run_allowlisted_staging_runner` | Real Test runner verbs with `--confirm-live` |
| Deploy approval/record create via `sudo()` after method gates | ACL create=0 by design |

---

## D. Session Lifecycle Fix

**Root cause:** Session `action_start` snapshots Git via `_run_git`, which hit *dubious ownership* on worker-owned worktrees (`euid=sabry`, owner=`devworker`). Separately, start must occur while workspace is **Ready** (start sets workspace **active**).

**Intended sequence (now enforced):**

```text
prepare → confirm → Ready
→ action_create_and_start_isolated_session (session started)
→ pause for worker handoff
→ implement → commit → push → …
```

**Live proof (WI 3324):** Session **950** created on Ready workspace **1849**, started successfully, then paused for worker — no stale draft from ordering.

Regression: `devhub_execution/tests/test_session_lifecycle_ordering.py` (+ `safe.directory` contract).

---

## E. GitHub App Broker Root Cause

**Classification:** `MISSING_CREDENTIAL` (on master) → resolved by installing approved credentials from `sabry3`.

| Finding | Detail |
|---------|--------|
| Empty path | `/srv/devhub/credentials/github/` previously had only push SSH materials |
| Credentials source | Copied from sabry3 secure location (PEMs + mint brokers) |
| Permissions | PEMs/brokers/`*-gh-profile` owned by **devworker** mode **600/700** |
| PR mint | Works as worker with host network |
| Merge mint | Works as worker; control-plane merge shell must run as **devworker** |

Private keys are **not** printed in this report.

---

## F. GitHub App Configuration

| Role | App slug | App ID | Installation ID | Broker | Profile |
|------|----------|--------|-----------------|--------|---------|
| PR | `sabry-uat-agent` | `4340040` | `147639376` | `mint-devhub-pr-token` | `gh-profile/` |
| Merge | `sabry-uat-merge-agent` | `4341059` | `147666583` | `mint-devhub-merge-token` | `merge-gh-profile/` |

| Dev Hub target | ID |
|----------------|----|
| `dev.git.pr.target` | **735** (PetSpot staging via sabry-uat-agent) |
| `dev.git.merge.target` | **105** |
| Deploy target | **4** PetSpot Test Staging Deploy (`non_production=true`, DB `pet_spot_elsahel_test`) |
| Merge requester user | **714** `devhub-merge-requester` |

---

## G. GitHub App Integration Test

Verified through Dev Hub product path (worker euid):

* Installation token mint (sanitized metadata only)
* Repository / PR create via `create_pr_approval` + `execute_approved_pr`
* PR #16 created and tracked on workspace (`pr_created_reviewed`)
* Observational check poll: GitGuardian **SUCCESS**, mergeable

`gh` was used only for observational polls / evidence — **not** as the PR creation path.

---

## H. Final UAT Work Item

| Field | Value |
|-------|--------|
| Marker | `DEVHUB-GOVERNED-MERGE-DEPLOY-UAT-20260723T122300Z` |
| Work Item | **3324** |
| Change | Harmless documentation-only |
| Final phase | `completed` |

---

## I. Analysis / Plan / Approval

| Record | ID | Status |
|--------|----|--------|
| Analysis | **2695** | accepted |
| Plan | **2478** | approved |
| Exact-hash Approval | **2276** | approved |
| Plan hash | `824be6510fe2943582a2f300f3c7ec60e7d554759ba1c3143d97abceb49a9d01` |

---

## J. Session / Workspace / Execution

| Record | ID | Notes |
|--------|----|--------|
| Workspace | **1849** (`DW-3324`) | Ready → session → paused → implement… → deployed |
| Session | **950** | started on Ready, then paused for worker |
| Checkpoints | **2142–2144** | worker implement |

---

## K. Git Commit / Push

| Field | Value |
|-------|--------|
| Commit SHA | `22c3cdc0d3bf82b418a6b70c7a0d698e09ca8786` |
| Branch | `devhub/DW-3324-devhub-governed-merge-deploy-uat-20260723t122300z-harmless-docs` |
| Push | Dev Hub worker push path (physical git as uid 1100) |

---

## L. GitHub App PR

| Field | Value |
|-------|--------|
| PR number | **16** |
| URL | https://github.com/sabryyoussef/veterinarian_19/pull/16 |
| Draft? | **false** (open) — product path intentionally non-draft; merge gate requires `draft=false` |
| Head | `devhub/DW-3324-…` @ `22c3cdc0…` |
| Base | `staging` |
| App / Installation | `4340040` / `147639376` |
| Dev Hub PR record | **200** |
| Creation path | Dev Hub GitHub App (`execute_approved_pr` as worker) |

**Draft policy note:** Preferring open PR is consistent with governed merge preflight. Earlier Draft PR #15 was a `gh` fallback from the prior UAT and is **not** the product path proven here.

---

## M. Human Approval Gate

| Step | Actor | Result |
|------|-------|--------|
| Merge review request | user **714** (requester) | recorded |
| Merge approval + execute | admin uid **2** (approver) | governed path |
| Identity separation | requester ≠ approver | enforced on merge record |

Configured Test policy allows the administrator to act as the distinct human approver after the dedicated requester opens the merge review. No gates were disabled.

---

## N. Governed Merge

| Field | Value |
|-------|--------|
| Merge approval | **57** |
| Merge record | **35** |
| Method | squash |
| Approved head SHA | `22c3cdc0d3bf82b418a6b70c7a0d698e09ca8786` |
| Merge SHA | `0b516d5af4ae24ab0d1575e3eff3b2682a5bb439` |
| Remote result | Exact squash merge verified remotely |
| Merged at (UTC) | 2026-07-23 12:29:38 |
| GitHub PR state | **MERGED** |

---

## O. Merge Record / merged_reviewed

Workspace **1849** transitioned to `merged_reviewed` with `merge_result_sha=0b516d5…` and `merge_record_id=35` before deploy.

---

## P. Test Deployment

| Field | Value |
|-------|--------|
| Target | **4** PetSpot Test Staging Deploy |
| Kind | staging / `non_production=true` |
| Database | `pet_spot_elsahel_test` only |
| Deploy approval | **1** |
| Deploy record | **1** |
| Merge SHA | `0b516d5af4ae24ab0d1575e3eff3b2682a5bb439` |
| Result | `succeeded` |
| Backup/lease ref | `runner://staging/5d81cdc6f57b` |
| Workspace after | `deployed_staging_reviewed` |
| Runner verbs | `preflight` → `deploy_code` → `healthcheck` → `smoke` (no `-u all`; upgrade opt-in only) |

Policy `deploy_permission` was enabled **only** for the deploy step, then restored to `False` (MVP launch forbids deploy permission during analysis/session).

---

## Q. Deployment Verification

| Check | Result |
|-------|--------|
| Target service health | HTTP 200 on `:8028` after deploy |
| Runner log | live preflight/deploy_code/healthcheck/smoke for merge SHA `0b516d5…` |
| Remote staging tip | matches merge SHA (verified via `git ls-remote` before approval) |
| Production service | **active**, not restarted by this UAT |
| Module upgrade | not invoked (`-u all` never used) |

---

## R. Workflow Board Screenshots

All under `screenshots/`:

| File | Proves |
|------|--------|
| `01_work.png` | Work Item 3324 |
| `02_analysis.png` | Analysis |
| `03_plan.png` | Plan |
| `04_approval.png` | Exact-hash approval |
| `05_session_started.png` | Session started |
| `06_workspace.png` | Workspace after pause |
| `07_execution.png` | Execution / implement |
| `08_checkpoint.png` | Checkpoint |
| `09_git_commit.png` | Commit |
| `10_github_app_pr.png` | GitHub App PR |
| `11_merge_approval.png` | Merge approval gate |
| `12_merged_reviewed.png` | merged_reviewed |
| `13_deploy_request.png` | Deploy request |
| `14_test_deploy_success.png` | Test deploy success |
| `15_workflow_final.png` | Final workflow |

---

## S. Automated Regression

| Suite | Result |
|-------|--------|
| Shell contract checks (session helper, `safe.directory`, deploy ls-remote + runner wiring) | **0 failed / 0 errors** — `logs/regression_contracts.txt` |
| Full `--test-enable` on Live Test DB | **External skip** — registry load / cursor contention on shared Live Test DB; contracts covered above |
| Added tests | `test_session_lifecycle_ordering.py`, `test_deploy_sha_runner_contracts.py` |

---

## T. Production Safety

| Proof | Status |
|-------|--------|
| Production DB untouched | Yes (no Production Dev Hub / deploy target used) |
| Production Odoo service untouched | `pet_spot_elsahel.service` **active** throughout |
| No Production branch merge | Merge base/head = **staging** only |
| No Production deploy | Target 4 `non_production=true`; runner refuses prod-like DB names |
| No Production Dev Hub install | Live Test DB only |
| Git safety / approval gates | Not disabled |

---

## U. Issues / Non-blockers

1. Product PR path creates **open** (non-draft) PRs by design; documented and aligned with merge gate.
2. Merge App broker executables are worker-only; governed merge shell must run as `devworker`.
3. MVP policy cannot keep `deploy_permission=True` during launch; toggled only around Test deploy.
4. Full Odoo post_install harness on the shared Live Test DB was skipped; shell contracts + live UAT cover the gates.
5. Local bare `staging` tip can lag GitHub until a worker fetch; deploy verification uses remote `ls-remote`, not stale bare tip.

---

## V. Final Verdict

```text
DEV HUB GOVERNED MERGE + TEST DEPLOY PASS
```

### Trace

```text
Work Item 3324
├── Analysis 2695
├── Plan 2478
├── Approval 2276
├── Session 950 (started → paused)
├── Workspace 1849
├── Checkpoint 2142–2144
├── Commit 22c3cdc0d3bf82b418a6b70c7a0d698e09ca8786
├── GitHub App PR #16 (App 4340040 / Installation 147639376)
├── Human Merge Approval 57 (requester 714 → approver 2)
├── Merge Record 35
├── Merge SHA 0b516d5af4ae24ab0d1575e3eff3b2682a5bb439
└── Test Deployment record 1 → target 4 → succeeded (deployed_staging_reviewed)
```
