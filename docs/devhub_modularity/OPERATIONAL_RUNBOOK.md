# Dev Hub Operational Runbook

**Audience:** Agents and humans operating Live Test Dev Hub  
**Board:** Workflow Board (`dev.workflow.board` / action Workflow)  
**Baseline:** `OPERATIONAL_BASELINE.md`

Default SOP for every new development task on Live Test.

---

## Stage ownership cheat sheet

| Stage | Mode | Actor |
|-------|------|--------|
| Intake | automatic / human / integration | system or human |
| Work | human / agent | Dev Hub User+ |
| Analysis | agent-driven or human | analyst / agent |
| Plan | agent-driven or human | planner / agent |
| Plan Approval | **human approval** | Plan Approver / Manager |
| Session / Workspace | agent-driven | Manager + worker euid |
| Execution | agent-driven | worker |
| Git commit/push | agent-driven + gates | worker |
| GitHub PR | agent-driven (GitHub App) | worker + Manager |
| Merge request | human / agent as requester | dedicated requester user |
| Merge Approval | **human approval** | distinct approver (Manager) |
| Governed Merge | agent-driven after approval | worker + Merge App |
| Test Deploy | **human approval** then runner | Deploy Approver + runner |
| Completion | human / agent | Manager |

---

## Step-by-step SOP

### 1. Receive task

| | |
|--|--|
| Actor | Human / WhatsApp / OpenProject / agent |
| Output | Intent + evidence |
| Failure | Do not invent Production scope |

### 2. Create / find Work Item

| | |
|--|--|
| Actor | Human or intake module |
| Model | `dev.work.item` (`devhub_work`) |
| Required | Project + environment with **production-denied** policy |
| Output | Work Item id |
| Failure | Abort if only Production policy available |

**Intake variants**

| Source | Path | Dedupe |
|--------|------|--------|
| Manual | Create WI in Dev Hub | Human title uniqueness |
| OpenProject | `devhub_openproject` link | OP work package id |
| WhatsApp | `whatsapp_hub` → `devhub_whatsapp` → WI | provider message id + index |
| Future API | Deferred | TBD |

Preserve source evidence on the WI / source message records.

### 3. Attach source evidence

| | |
|--|--|
| Actor | Agent / human |
| Models | `dev.work.source.message`, attachments, OP refs |
| Output | Traceable intake |

### 4. Run Analysis (optional if Manual Plan)

| | |
|--|--|
| Actor | Agent / human |
| Model | `dev.work.analysis` |
| Required state | Work open |
| Output | Accepted analysis |
| Failure | Leave WI in analyzing; do not fake accept |

### 5. Create Plan

| | |
|--|--|
| Actor | Agent / human |
| Model | `dev.work.plan` (+ steps) |
| Output | Draft plan with content hash |
| Failure | Do not submit empty/invalid plan |

### 6. Human Plan Approval (exact-hash)

| | |
|--|--|
| Actor | **Human** Plan Approver |
| Model | `dev.work.approval` via `action_approve_exact` |
| Required | Submitted plan; hash match |
| Output | Approved decision bound to plan hash |
| Failure | Reject / rework plan — never bypass hash |

### 7. Create isolated Session / Workspace

| | |
|--|--|
| Actor | Agent (Manager) + worker confirm |
| Models | `dev.execution.workspace`, `dev.session` |
| Required | Approved plan; repository `safe_for_isolated_worktree` |
| Sequence | prepare → confirm → **Ready** → `action_create_and_start_isolated_session` → pause for worker |
| Output | Ready/paused workspace + started then paused session |
| Failure | Do not start session before Ready; do not use dirty developer checkout |

### 8. Execute approved Plan

| | |
|--|--|
| Actor | Worker stages (`implement`, checkpoints) |
| Required | Workspace Ready or paused after session start |
| Output | Checkpoints; files only under worktree |
| Failure | Block on main-snapshot drift / policy |

### 9. Commit + Push

| | |
|--|--|
| Actor | Worker via `devhub_git` |
| Required | Review → approve → execute gates; euid 1100 |
| Output | `committed_sha`, remote branch |
| Failure | Never weaken Git safety; never force-push protected bases |

Branch naming: `devhub/DW-<id>-…`  
Base: `staging` only for PetSpot Test. Prohibited: Production branches / force-push to protected bases.

### 10. Create PR via GitHub App

| | |
|--|--|
| Actor | Worker + Manager |
| Model | `devhub_github` PR approval/execute |
| Path | Dev Hub → broker → installation token → PR |
| Output | Open PR (product path is non-draft); `pr_number`, `pr_url_reference` |
| Failure | Do not fall back to `gh` as primary path (`gh` = diagnostic/emergency only) |

### 11. Human Merge Approval

| | |
|--|--|
| Actor | Requester user ≠ Approver user |
| Models | merge review request + `dev.git.merge.approval` |
| Required | Checks (e.g. GitGuardian); head SHA binding; open PR |
| Output | Merge approval record |
| Failure | Stop — present READY FOR HUMAN MERGE APPROVAL |

### 12. Governed Merge

| | |
|--|--|
| Actor | Approver + Merge App (worker) |
| Output | `dev.git.merge.record`, `merge_result_sha`, workspace `merged_reviewed` |
| Failure | Fail closed; no UI/`gh pr merge` as primary path |

### 13. Test Deploy

| | |
|--|--|
| Actor | Deploy Approver (≠ requester) |
| Target | **4** PetSpot Test Staging Deploy |
| Required | `merged_reviewed` + merge record + remote tip SHA match |
| Runner | preflight → deploy_code → healthcheck → smoke |
| Output | `dev.deploy.record` `succeeded`; workspace `deployed_staging_reviewed` |
| Failure | `failed_safely`; reconcile — no blind retry |

States: `DEPLOYMENT READY` (merged_reviewed) → `DEPLOYING` → `SUCCEEDED` / `FAILED`.

### 14. Healthcheck / Smoke

| | |
|--|--|
| Actor | Runner |
| Check | HTTP on Test port; smoke acknowledge |
| Failure | Mark failed; do not deploy Production |

### 15. Complete Work Item

| | |
|--|--|
| Actor | Manager / agent |
| Models | completion report + `action_complete` |
| Output | WI completed; board KPIs update |

---

## Failure behavior (global)

1. Prefer fail-closed over silent success.
2. Never disable Git/approval gates for convenience.
3. Never install or deploy Dev Hub to Production from this runbook.
4. Never use `-u all`.
5. Preserve UAT evidence and dirty unrelated developer work.
