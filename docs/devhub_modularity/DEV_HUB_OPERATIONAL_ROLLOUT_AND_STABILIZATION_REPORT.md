# Dev Hub Operational Rollout & Stabilization Report

**Date:** 2026-07-23  
**Evidence:** `docs/devhub_modularity/operational_rollout_stabilization/`  
**Companion docs:** `OPERATIONAL_BASELINE.md`, `ARCHITECTURE.md`, `OPERATIONAL_RUNBOOK.md`

---

## A. Final Verdict

```text
DEV HUB OPERATIONAL CONTROL PLANE READY WITH NON-BLOCKERS
```

Live Test Dev Hub is formally stabilized as the operational development control plane. Implementation-phase delivery (through governed merge + Test deploy) is proven. Remaining items are classified non-blockers or deferred — none block day-to-day Test operation.

---

## B. Proven Code Pin

| Item | Value |
|------|--------|
| Branch | `feature/devhub-modularization-whatsapp` |
| HEAD | `4c1fc00555a3ede2ccf7582fdb87af6082a29195` |
| Proven merge SHA (Test deploy) | `0b516d5af4ae24ab0d1575e3eff3b2682a5bb439` |
| Proven PR head | `22c3cdc0d3bf82b418a6b70c7a0d698e09ca8786` |
| Dirty tree | Yes — modular `devhub_*` largely untracked vs pin; WhatsApp/OP/unrelated dirty preserved |

Authoritative freeze: `OPERATIONAL_BASELINE.md`.

---

## C. Live Test Runtime

| Item | Value |
|------|--------|
| DB | `pet_spot_elsahel_test` |
| Port | `8028` |
| Service | `pet_spot_elsahel_test.service` **active** |
| Config | `pet_spot_elsahel_test.conf` |
| addons_path | Community + Enterprise + `projects/pet_spot_elsahel` only (canonical) |
| Overlay shadowing | None on Live Test path |
| Health | HTTP 200 on `/web/login` |

---

## D. Module Versions

All listed modules **installed** on Live Test:

| Module | Version |
|--------|---------|
| devhub_core | 19.0.9.0.1 |
| devhub_work | 19.0.9.1.0 |
| devhub_analysis | 19.0.9.1.0 |
| devhub_plan | 19.0.9.1.0 |
| devhub_approval | 19.0.9.1.0 |
| devhub_generation | 19.0.9.1.0 |
| devhub_session | 19.0.9.0.0 |
| devhub_execution | 19.0.9.1.0 |
| devhub_git | 19.0.9.0.0 |
| devhub_github | 19.0.9.0.0 |
| devhub_deploy | 19.0.9.0.0 |
| devhub_outbox | 19.0.9.0.0 |
| devhub_openproject | 19.0.9.1.0 |
| devhub_whatsapp | 19.0.9.0.2 |
| devhub_workflow | 19.0.9.1.0 |
| devhub_code_analysis | 19.0.9.1.0 |
| devhub_odoo_runtime | 19.0.9.0.0 |
| devhub_infrastructure | 19.0.9.0.0 |
| **dev_session_hub** | **19.0.9.1.0** |

---

## E. Regression Results

### Shell contract suite (Live Test, safe)

File: `operational_rollout_stabilization/regression/shell_contracts.txt`

```text
RESULT 0 failed 0 errors
```

Covered:

* all modular modules installed
* `devhub_work` independent of OpenProject
* `devhub_whatsapp` depends on `whatsapp_hub` + `devhub_work`
* Workflow Board + 7 capabilities
* Session start helper + `safe.directory`
* Deploy ls-remote + staging runner wiring (no `-u all`)
* Proven UAT records intact (WI 3324, WS 1849 deployed, merge 35, deploy 1)
* Target 4 non-production
* PetSpot Test MVP `production_access_policy=denied`

### External skips (precise)

| Suite | Reason |
|-------|--------|
| Full `--test-enable` post_install on Live Test DB | Registry load / cursor contention on shared Live Test; abandoned previously; shell contracts + live UAT used instead |
| Ready-gate UserError fixture | No `pending_confirmation` workspace at freeze time — **SKIP** (helper still present; proven live on WI 3324) |
| Live re-run of commit/push/PR/merge/deploy | Already proven end-to-end on WI 3324; not re-executed during stabilization to avoid noise PRs |

---

## F. Known Non-Blockers

| Item | Classification | Notes |
|------|----------------|-------|
| Admin sees 44/45 work items (record rules) | **DOCUMENT** | Project membership rules; expected since D14 |
| Enterprise `ai.embedding` traceback | **DOCUMENT** | Unrelated autovacuum/GC noise |
| Dirty/untracked `devhub_*` paths vs pin | **SEPARATE FUTURE TASK** | Commit/PR modular tree when ready; do not discard |
| Historical D14 clone/runtime | **KEEP FOR ROLLBACK** / **ARCHIVE** | Evidence retained |
| Historical UAT worktrees `DW-3320/3323/3324` | **KEEP FOR AUDIT** | Cleanup later after retention policy |
| Incomplete WI 3319 (`analyzing`) | **CLOSE** (soft) / **KEEP FOR AUDIT** | Abandoned script; leave record, optional cancel later |
| Old overlay rollback refs | **KEEP FOR ROLLBACK** | See inactive runtime reference doc |
| Session draft ordering (WI 3320 era) | **FIX NOW** (done) | Fixed + proven on WI 3324 |
| GitHub App missing on master | **FIX NOW** (done) | Brokers installed |
| Product PR non-draft | **DOCUMENT** | Intentional; merge gate requires open PR |
| Local bare `staging` lag vs GitHub | **DOCUMENT** | Deploy verifies via `git ls-remote` |
| Deploy target id 3 “Bad staging” gate fixture | **DOCUMENT** | Test fixture; not Production |

No unrelated “cleanliness” edits were made.

---

## G. Workflow Board Operational Model

| Property | Value |
|----------|--------|
| Model | `dev.workflow.board` |
| Role | Orchestration only |
| Capabilities | Soft-discovers installed stages via `dev.workflow.capability` (7 installed) |
| Owns business data? | **No** |
| Default surface | Workflow menu / board form — standard operational entry |
| KPIs | work / analysis / plan / awaiting approval / execution counts + stage summary |

Lifecycle reflected by linking to capability models; board does not duplicate Analysis/Plan/Approval/Execution ownership.

---

## H. Standard Task Intake

| Source | Source record | Dedupe | WI rule | Project/Env | Initial phase | Evidence |
|--------|---------------|--------|---------|-------------|---------------|----------|
| Manual | Human create | Title/human | Direct `dev.work.item` | PetSpot Test + MVP policy | intake/work | Attachments / notes |
| OpenProject | OP WP via `devhub_openproject` | OP id | Link/create WI | Mapped project | work | OP sync refs |
| WhatsApp | `whatsapp_hub` → `devhub_whatsapp` | provider_message_id + index | Create WI from hub message | Mapped Test project | work | Source message snapshot |
| Future API | Deferred | TBD | TBD | TBD | TBD | TBD |

**Invariant:** `whatsapp_hub → devhub_whatsapp → dev.work.item` — no generic WhatsApp ownership inside Dev Hub.

---

## I. Human Approval Gates

### Plan Approval

```text
Plan → submit → exact-hash approval (hash must match)
```

Actors: Plan Approver / Manager.

### Merge Approval

```text
PR → requester requests merge review → distinct approver → approved head SHA → governed merge
```

Actors: requester user **714** vs approver (Manager/admin); enforced on merge record.

### Production Approval

```text
Separately gated (Production Approver group exists)
```

**Not enabled** in this stabilization. No Production deploy target activated for Dev Hub operations.

### Who can what (Live Test)

| Action | Group / actor |
|--------|----------------|
| Request merge | Dedicated merge requester (or scoped user) |
| Approve plan | Plan Approver / Manager |
| Approve merge | Distinct Manager/approver |
| Deploy Test | Deploy Approver / Manager (≠ deploy requester) |
| Approve Production | Production Approver — **unused** |

---

## J. GitHub App Architecture

```text
Dev Hub
 → GitHub App broker (mint-*-token)
 → installation token (short-lived)
 → PR create/read (PR App 4340040)
 → governed merge (Merge App 4341059)
```

| Rule | Status |
|------|--------|
| Canonical PR path | GitHub App |
| `gh` CLI | Manual diagnostic / emergency only |
| Credential perms | 600/700 `devworker` |
| Secrets in DB/code | No PAT embedded |
| Broker failure | Sanitized error; no key/token dump |

---

## K. Worker / Workspace Architecture

```text
Developer checkout  ≠  Dev Hub execution workspace

bare /srv/devhub/repos/petspot.git
 → clean main snapshot /srv/devhub/main-snapshots/petspot
 → isolated worktree /srv/devhub/worktrees/petspot/DW-<id>
 → worker OS user devworker (1100)
 → branch devhub/DW-<id>-…
 → commit / push
```

| Item | Standard |
|------|----------|
| Allowed base | `staging` (PetSpot Test) |
| Prohibited | Production branch mutation; dirty developer path as worktree |
| Naming | Workspace `DW-<wi>`; branch `devhub/DW-<wi>-…` |
| Retention | Keep successful UAT worktrees for audit; prune stale later under policy |
| Stale handling | Leave registered; do not auto-delete in this phase |

---

## L. Merge Architecture

```text
Open PR (GitHub App)
 → requester ≠ approver
 → checks (GitGuardian)
 → create_merge_approval
 → execute_approved_merge (Merge App / worker)
 → merge record + merge_sha
 → workspace merged_reviewed
```

Proven: Merge Approval **57**, Record **35**, SHA `0b516d5a…`, PR **#16 MERGED**.

---

## M. Deployment Architecture

```text
merged_reviewed
 → merge record
 → Test target 4
 → SHA tip verify (git ls-remote)
 → preflight → deploy_code → healthcheck → smoke
 → deploy record succeeded
 → deployed_staging_reviewed
```

| State | Meaning |
|-------|---------|
| DEPLOYMENT READY | `merged_reviewed` + merge record |
| DEPLOYING | deploy approval consumed / runner running |
| SUCCEEDED | `deployed_staging_reviewed` + record `succeeded` |
| FAILED | `failed_safely` — reconcile, no blind retry |

Rollback: runner destructive verbs refuse without separate gate; retain backup profile reference. Production deploy **not enabled**.

---

## N. Legacy Runtime Cleanup Status

| Asset | Classification | Action now |
|-------|----------------|------------|
| Live Test canonical conf :8028 | **ACTIVE_RUNTIME** | Keep |
| Production :8027 | **ACTIVE_RUNTIME** (non-DevHub) | Untouched |
| `releases/addons_overlay_*` | Not present under project `releases/` | N/A |
| Cutover inactive overlay refs | **ROLLBACK_REFERENCE** | Keep doc; do not delete |
| `pet_spot_elsahel_test_modular_mig` :8041 | **INACTIVE_RUNTIME** / acceptance leftover | **STOPPED** during stabilization (2026-07-23); DB/filestore retained |
| `resume` :8029 | Unrelated resume stack | Out of Dev Hub scope |
| `/srv/devhub/worktrees/...` UAT trees | **EVIDENCE_ONLY** | Keep |
| Historical confs (`devhub_func_matrix`, mig rehearsal, modular_mig) | **ARCHIVE_CANDIDATE** | Keep files; not on Live Test path |
| Filestore dirs `.filestore_*` | **EVIDENCE_ONLY** | Keep |

**Goal achieved:** zero accidental active shadowing on Live Test `addons_path`. No destructive deletion performed.

---

## O. Acceptance Environment Disposition

| Environment | Decision |
|-------------|----------|
| Live Test `pet_spot_elsahel_test` :8028 | **KEEP AS ACCEPTANCE** + operational control plane |
| `pet_spot_elsahel_test_modular_mig` :8041 | **STOPPED**; **KEEP AS ROLLBACK**/evidence DB |
| `devhub_func_matrix` conf/DB | **ARCHIVE**; stop if running |
| `devhub_modular_fresh` / mig rehearsal | **ARCHIVE** / **DELETE LATER** (manual) |
| Historical UAT workspaces in DB | **KEEP AS ACCEPTANCE** audit trail |

No automatic deletes.

---

## P. UAT Artifact Disposition

| Artifact | Disposition |
|----------|-------------|
| WI 3318 | **KEEP FOR AUDIT** (completed) |
| WI 3319 | **KEEP FOR AUDIT**; soft-close candidate (`analyzing` abandoned) |
| WI 3320 | **KEEP FOR AUDIT** (Draft PR path) |
| WI 3324 | **KEEP FOR AUDIT** (governed merge + deploy proof) |
| PR #15 Draft OPEN | **SAFE TO REMOVE LATER** — may close without merge if explicitly approved; **do not merge for cleanup** |
| PR #16 MERGED | **KEEP FOR AUDIT** |
| UAT branches / commits | **KEEP FOR AUDIT** |
| Worktrees DW-3320/3323/3324 | **KEEP FOR AUDIT** |
| Merge record 35 / Deploy record 1 | **KEEP FOR AUDIT** |
| Reports under `docs/devhub_modularity/` | **KEEP FOR AUDIT** |

---

## Q. Production Boundary

Verified 2026-07-23 against Production DB `pet_spot_elsahel` :8027:

| Check | Result |
|-------|--------|
| Modular `devhub_*` modules | All **uninstalled** |
| `dev_session_hub` | **uninstalled** |
| Production Dev Hub install | **None** |
| Production deploy via Dev Hub | **Not enabled** |
| Production service during stabilization | **active**, untouched |
| Config addons_path | Canonical project root (no Dev Hub-only overlay required) |

Architectural boundary holds until a separate Production-control-plane decision.

---

## R. Operational Runbook

Published: `OPERATIONAL_RUNBOOK.md`

Covers intake → completion with actor, model, required state, output, and failure behavior per step. Workflow Board is the default orchestration surface.

---

## S. Final Architecture

Published: `ARCHITECTURE.md`

Shows intake / core / capabilities / providers / integrations / orchestration / meta and the delivery flow with optional dependencies.

---

## T. Final Module Disposition

| Module | Final Role | Required? | Optional? | Runtime Status | Future Action |
|--------|------------|-----------|-----------|----------------|---------------|
| devhub_core | Core registry/policy/security | Yes (foundation) | | installed | Maintain |
| devhub_work | Core Work ownership | Yes | | installed | Maintain |
| devhub_plan | Capability Plan | Yes for delivery | | installed | Maintain |
| devhub_approval | Capability Approval | Yes for delivery | | installed | Maintain |
| devhub_analysis | Capability Analysis | Recommended | Yes (Manual Plan path) | installed | Maintain |
| devhub_generation | Capability drafts | | Yes | installed | Maintain |
| devhub_session | Capability Session | Yes for execution | | installed | Maintain |
| devhub_execution | Capability Execution | Yes for execution | | installed | Maintain |
| devhub_git | Provider Git | Yes for commit/push | | installed | Maintain |
| devhub_github | Provider GitHub App | Yes for PR/merge | | installed | Maintain |
| devhub_deploy | Provider Deploy | Yes for Test deploy | | installed | Maintain; no Prod |
| devhub_outbox | Provider messaging | | Yes | installed | Maintain |
| devhub_odoo_runtime | Provider runtime | | Yes | installed | Maintain |
| devhub_infrastructure | Provider infra | | Yes | installed | Maintain |
| devhub_code_analysis | Provider code analysis | | Yes | installed | Maintain |
| devhub_openproject | Integration consumer | | Yes | installed | Maintain |
| devhub_whatsapp | Integration consumer (Hub) | | Yes | installed | Stage-2 intake later |
| devhub_workflow | Orchestration board | Recommended | | installed | Default UI surface |
| dev_session_hub | Meta/compat | Meta package | | installed | Keep; no re-monolith |

---

## U. Deferred Work

Explicitly **out of scope** for this stabilization:

1. Production Dev Hub deployment / install  
2. Production deployment target enablement  
3. Stage 2 WhatsApp Dev Hub intake expansion  
4. Automated task intake expansion / Future API  
5. Additional deployment targets  
6. Advanced workflow customization  
7. Legacy module uninstall  
8. Historical worktree / Draft PR #15 deletion (needs explicit approval)  
9. Committing untracked modular tree to git remote  

---

## V. Final Verdict

```text
DEV HUB OPERATIONAL CONTROL PLANE READY WITH NON-BLOCKERS
```

### Success condition check

| Criterion | Met? |
|-----------|------|
| Freeze proven code/config baseline | Yes — `OPERATIONAL_BASELINE.md` |
| Regression documented | Yes — 0 failed / 0 errors shell contracts + skips listed |
| Workflow Board as operational surface | Yes — documented + capability discovery verified |
| GitHub App + governed merge standardized | Yes |
| Isolated worker + Test deploy documented | Yes |
| Inactive legacy shadows classified | Yes — no destructive deletes |
| Runbook for agent-driven tasks | Yes — `OPERATIONAL_RUNBOOK.md` |
| Production untouched / no Prod Dev Hub | Yes |

### Proven operational trace (retained)

```text
Work Item 3324
├── Analysis 2695
├── Plan 2478
├── Approval 2276
├── Session 950
├── Workspace 1849
├── Checkpoints 2142–2144
├── Commit 22c3cdc0…
├── GitHub App PR #16
├── Human Merge Approval 57
├── Merge Record 35
├── Merge SHA 0b516d5a…
└── Test Deployment 1 → Target 4 → succeeded
```
