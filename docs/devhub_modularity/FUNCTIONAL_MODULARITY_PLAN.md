# Dev Hub Functional Modularity Plan

**Status:** Approved architecture — implementation in progress  
**Date:** 2026-07-23  
**Branch:** `feature/devhub-modularization-whatsapp`  
**Baseline SHA (pre-split):** `5d627a7e4b6ec4a29928dfd3c57f3fcf000f66cc`  
**Canonical tree:** `/home/sabry/odoo_base/base_odoo_19/projects/pet_spot_elsahel`  
**Acceptance DB:** `devhub_modular_fresh` (:8032)  
**Production:** Untouched — modular Dev Hub **not** installed on `pet_spot_elsahel`

---

## Critical Answers (locked)

| # | Question | Answer |
|---|----------|--------|
| 1 | Is `devhub_work` still too monolithic? | **Yes.** ~3328-line `dev_work.py` owns analysis, plan, steps, approval, checkpoint, completion, communication, outbox model + form tabs. |
| 2 | Should Analysis become `devhub_analysis`? | **Yes.** |
| 3 | Should Plan become `devhub_plan`? | **Yes.** Manual plans work **without** Analysis installed. |
| 4 | Should Approval become `devhub_approval`? | **Yes** — plan approval + reusable mixin; git/deploy adopt later. |
| 5 | Can `devhub_work` run without OpenProject? | **Not today** (hard `openproject_sync`). **Target: yes** via moving OP fields to `devhub_openproject`. |
| 6 | Can Work exist without Analysis/Plan/Execution? | **Target: yes** after split. Execution already optional. |
| 7 | Is `devhub_generation` generic enough? | Lease engine yes; kinds hardcoded. Add kind registry. |
| 8 | Is `devhub_execution` separated from providers? | **Mostly yes.** Chain: session → execution → git → github → deploy. Extract shared constants. |
| 9 | What remains in `dev_session_hub`? | Meta installer + menus + `ir.rule` + seeds + migrations. Zero models already. |
| 10 | How does Workflow Dashboard discover capabilities? | Soft `"model" in self.env` + optional `dev.workflow.capability` registry. |
| 11 | Which models move without table/data migration? | `dev.work.analysis`, `dev.work.plan`, `dev.work.plan.step`, `dev.work.approval`, `dev.work.checkpoint` — keep `_name`/tables. |
| 12 | Safest migration order? | Fresh install matrix → upgrade `devhub_modular_fresh` → Test clone canonical → never Production. |

---

## 1. Current Architecture

```text
devhub_core (registry)
    ↓
devhub_work  ←── MONOLITH (analysis+plan+approval+checkpoint+outbox model)
    ├── openproject_sync (HARD)
    ├── devhub_session → execution → git → github → deploy
    ├── devhub_generation (hardcoded analysis/plan/merge kinds)
    ├── devhub_outbox (lease on work-owned outbox model)
    ├── devhub_code_analysis (extends analysis)
    ├── devhub_openproject (UI only today)
    └── devhub_whatsapp → whatsapp_hub

dev_session_hub = meta fan-in + ALL menus + ALL ir.rule + seeds
```

WhatsApp Hub consolidation is closed and out of scope. `devhub_whatsapp` remains a Hub consumer.

---

## 2. Current Module Inventory

| Module | Version | Own Models | Extends | Main Capability | Dependencies | Coupling |
|--------|---------|------------|---------|-----------------|--------------|----------|
| `devhub_core` | 19.0.9.0.1 | machine, client, project, repository, environment, task.link, policy, dashboard | — | Registry | base, mail, web | LOW |
| `devhub_work` | 19.0.9.0.0 | work.item, lifecycle.event, source.message, external.link, analysis, plan, plan.step, approval, checkpoint, completion.report, communication, external.outbox | — | Work + artifacts (monolith) | core, project, **openproject_sync** | HIGH |
| `devhub_session` | 19.0.9.0.0 | session, session.event | work.item, checkpoint | Sessions | work | MEDIUM |
| `devhub_execution` | 19.0.9.0.0 | execution.workspace, workspace.event | repository, work.item, session, checkpoint | Execution orchestration | session | MEDIUM |
| `devhub_git` | 19.0.9.0.0 | git.remote, commit/push approval+record | repository, workspace | Git provider | execution | MEDIUM |
| `devhub_github` | 19.0.9.0.0 | PR/merge/bind/bootstrap/app/allowlist | repository, project, workspace | GitHub provider | git | HIGH |
| `devhub_deploy` | 19.0.9.0.0 | deploy/rollback approval+record+target | workspace | Deploy provider | github | HIGH |
| `devhub_generation` | 19.0.9.0.0 | work.generation | project, work.item, analysis | AI draft lease | work | MEDIUM |
| `devhub_outbox` | 19.0.9.0.0 | — | external.outbox | Outbound lease | work | MEDIUM |
| `devhub_code_analysis` | 19.0.9.0.0 | — | analysis, work.item, project.task | Code/DB inspection | work, odoo_runtime | LOW-MED |
| `devhub_openproject` | 19.0.9.0.0 | — | project, project.task | OP UI links | work, openproject_sync | MED-HIGH |
| `devhub_odoo_runtime` | 19.0.9.0.0 | odoo.runtime, runtime.addon.source | environment, project | Odoo runtime | core | LOW |
| `devhub_infrastructure` | 19.0.9.0.0 | machine.verification.event | machine | Infra verify | core | LOW |
| `devhub_whatsapp` | 19.0.9.0.2 | whatsapp.intake/event/source/sender | work.item | WA consumer | work, whatsapp_hub | HIGH (external) |
| `dev_session_hub` | 19.0.9.0.0 | **none** | — | Meta/menus/rules/seeds | all 14 | META |

---

## 3. Current Model Ownership

| Model | Current Owner | Correct Functional Owner | Move? | Table |
|-------|---------------|--------------------------|-------|-------|
| `dev.machine` … `dev.dashboard` | core | core | No | `dev_*` |
| `dev.work.item` | work | work | No | `dev_work_item` |
| `dev.work.lifecycle.event` | work | work | No | `dev_work_lifecycle_event` |
| `dev.work.source.message` | work | work | No | `dev_work_source_message` |
| `dev.work.external.link` | work | work | No | `dev_work_external_link` |
| `dev.work.analysis` | work | **devhub_analysis** | **Yes** | `dev_work_analysis` |
| `dev.work.plan` | work | **devhub_plan** | **Yes** | `dev_work_plan` |
| `dev.work.plan.step` | work | **devhub_plan** | **Yes** | `dev_work_plan_step` |
| `dev.work.approval` | work | **devhub_approval** | **Yes** | `dev_work_approval` |
| `dev.work.checkpoint` | work | **devhub_execution** | **Yes** | `dev_work_checkpoint` |
| `dev.completion.report` | work | work (later optional) | No now | `dev_completion_report` |
| `dev.work.communication` | work | work (later optional) | No now | `dev_work_communication` |
| `dev.external.outbox` | work | work (service in outbox) | No | `dev_external_outbox` |
| `dev.work.generation` | generation | generation | No | `dev_work_generation` |
| `dev.session*` | session | session | No | — |
| `dev.execution.workspace*` | execution | execution | No | — |
| OP fields on work.item | work | **devhub_openproject** | **Yes (fields)** | same table |
| `dev.whatsapp.*` | whatsapp | whatsapp | No | — |

Preferred migration: **move Python/XML ownership; keep `_name` and table; no data copy.**

---

## 4. Current Dependency Graph

```text
core
 ├─ infrastructure
 ├─ odoo_runtime
 └─ work ──(HARD)──► openproject_sync
      ├─ session → execution → git → github → deploy
      ├─ generation
      ├─ outbox
      ├─ code_analysis (+ odoo_runtime)
      ├─ openproject (+ openproject_sync)
      └─ whatsapp (+ whatsapp_hub)

dev_session_hub → ALL of the above
```

---

## 5. Monolithic / Coupled Areas

1. **`devhub_work` file monolith** — analysis/plan/approval/checkpoint co-located.
2. **Hard OpenProject depend** — blocks Core+Work-only installs.
3. **Generation kinds hardcoded** — not a plugin registry.
4. **Approval pattern duplicated** ~9 times (git/github/deploy) without shared mixin.
5. **Menus + ir.rule centralized** in `dev_session_hub` — partial installs lack navigation/RLS.
6. **Test overlay shadow** — live Test still on monolith 8.x.
7. **Private constant imports** from `devhub_execution` into git/github/deploy.

---

## 6. `devhub_work` Deep Analysis

**Contains today:** intake (source messages), lifecycle FSM, analysis, plan+steps, approval, checkpoints, completion, communication, outbox model, full multi-tab form.

**After split stays:**

- `dev.work.item` identity + FSM (soft gates when capabilities absent)
- `dev.work.lifecycle.event`
- `dev.work.source.message`
- `dev.work.external.link`
- `dev.completion.report`, `dev.work.communication`, `dev.external.outbox` (phase 1)

**Moves out:** analysis, plan, plan.step, approval, checkpoint, OP Many2one fields.

**FSM policy after split:**

- Transitions requiring analysis/plan become soft (`"dev.work.analysis" in self.env`).
- Manual plan allowed without Analysis module.
- If Analysis installed, soft guidance to prefer accepted analysis (not hard gate for manual plans).

---

## 7. Analysis Capability Design

**Module:** `devhub_analysis`

- Depends: `devhub_work`
- Soft-uses: `devhub_generation`
- Owns: `dev.work.analysis`, import/merge RPCs, Analysis tab/views, related ACLs
- Extends: `dev.work.item` with `analysis_ids` / current analysis fields

**Boundary vs `devhub_code_analysis`:**

| Module | Role |
|--------|------|
| `devhub_analysis` | Business artifact + workflow |
| `devhub_code_analysis` | Codebase/DB inspection **provider** writing into `dev.work.analysis` |

---

## 8. Plan Capability Design

**Module:** `devhub_plan`

- Depends: `devhub_work` **only** (no hard Analysis)
- Soft-depends Analysis for enrichment / auto-generate context
- Owns: `dev.work.plan`, `dev.work.plan.step`, import/revision, Plan UI
- Registers `plan` generation kind with Generation when both installed

**Manual Plan without Analysis:** supported.

---

## 9. Approval Capability Design

**Module:** `devhub_approval`

- Depends: `devhub_plan` (plan approval is primary consumer)
- Owns: `dev.work.approval`
- Introduces mixin: approver, decided_at, decision, binding_hash, immutability, optional event

**Generic contract (phase 1):** plan approval only.  
**Phase 2+:** git/deploy/PR approvals adopt mixin (not forced in D6).

Reusable for: Plan, Execution gate, Merge, Deploy — without coupling Approval to GitHub.

---

## 10. Execution Capability Design

**Already mostly correct.**

```text
devhub_execution     = orchestration (workspace lifecycle)
devhub_session       = interactive sessions
devhub_git/github/deploy/odoo_runtime/infrastructure = providers
```

**Change:** move ownership of `dev.work.checkpoint` into `devhub_execution`.  
**Change:** publish shared regex/constants so providers stop importing private module attrs.

---

## 11. Generation Capability Design

```text
devhub_generation     = generic lease/job lifecycle + kind registry
devhub_analysis       = registers analysis, merge_analysis
devhub_plan           = registers plan
```

Keep: `service_lease`, `service_mark_processing`, `service_complete`, `service_fail`.  
Replace: hardcoded `if kind == ...` branches with registry lookup.

---

## 12. Session Capability Design

Keep `devhub_session` as-is. Depends on Work. Optional for Execution chain. Workflow discovers via `"dev.session" in self.env`.

---

## 13. Git / GitHub / Deploy Boundaries

Keep provider modules. Later adopt `devhub_approval` mixin. No merge into Execution. No ownership of Work analysis/plan.

---

## 14. Odoo Runtime / Infrastructure Boundaries

Already clean leaves off Core. Keep. `devhub_code_analysis` may depend on runtime.

---

## 15. OpenProject Boundary

```text
openproject_sync     = generic Odoo Project ↔ OpenProject engine
devhub_openproject   = Dev Hub OP fields + UI + policies
```

**Remove** hard `openproject_sync` from `devhub_work`.  
**Move** `op_backend_id`, `op_work_package_id`, OP helpers onto work item via `_inherit` in `devhub_openproject`.

**Can Work run without OpenProject after change?** Yes — install Core+Work only.

---

## 16. WhatsApp Consumer Boundary

Confirmed correct today:

```text
whatsapp.message → devhub_whatsapp → dev.whatsapp.intake → dev.work.item
```

Owns: source config, JID whitelist, sender policy, `intake_mode`, classification, human confirm.  
Does **not** own: generic messages/contacts/groups/conversations/instances.  
Keep governed outbox for replies — never replace with direct Hub send.  
Do **not** enable Production Dev Hub WhatsApp intake in this workstream.

---

## 17. Outbox Boundary

`devhub_outbox` is clean: depends only on Work; extends `dev.external.outbox`; Chatwoot/OP/n8n as channel strings + lease RPCs.  
**Keep:** Dev Hub → outbox → Chatwoot/n8n.  
**Do not** depend on WhatsApp Hub for outbound.

---

## 18. Core Purity Review

`devhub_core` depends only on `base`, `mail`, `web`. Dashboard soft-checks Work/Session. Machine verification stubs to infrastructure.  
**No leakage** requiring OP/GitHub/WhatsApp/Dify/n8n/Execution/Analysis.  
Optional later: shared public constants utility (may live under Core or Execution public API).

---

## 19. Proposed Final Module List

1. `devhub_core`  
2. `devhub_work` (slim)  
3. `devhub_analysis` **(new)**  
4. `devhub_plan` **(new)**  
5. `devhub_approval` **(new)**  
6. `devhub_generation` (registry)  
7. `devhub_code_analysis`  
8. `devhub_session`  
9. `devhub_execution` (+ checkpoint)  
10. `devhub_git`  
11. `devhub_github`  
12. `devhub_deploy`  
13. `devhub_odoo_runtime`  
14. `devhub_infrastructure`  
15. `devhub_outbox`  
16. `devhub_openproject` (absorbs OP fields)  
17. `devhub_whatsapp`  
18. `devhub_workflow` **(new)**  
19. `dev_session_hub` (meta/compat)

---

## 20. Final Model Ownership Matrix

See §3 “Correct Functional Owner” column — that is the final matrix.

---

## 21. Final Dependency DAG

```text
devhub_core
  ├─ infrastructure
  ├─ odoo_runtime
  └─ work                    # NO openproject_sync
       ├─ analysis ──► generation (soft/register)
       │    └─ code_analysis (+ runtime)
       ├─ plan ──► approval
       │    └─ generation (register plan)
       ├─ generation
       ├─ outbox
       ├─ openproject ──► openproject_sync
       ├─ whatsapp ──► whatsapp_hub
       └─ session → execution → git → github → deploy

devhub_workflow → work (+ soft detects capabilities)
dev_session_hub → full default stack including workflow
```

No cycles.

---

## 22. Independent Installation Matrix

| Scenario | Modules | Installable | Functional | Blocker (today → after) |
|----------|---------|-------------|------------|-------------------------|
| Minimal registry | core | Y | Projects/machines/repos/envs | — |
| Work tracking | core+work | Y after D3 | Create/track work | OP hard dep → fixed |
| Analysis | +generation+analysis | Y after D4 | Analysis drafts | co-location → fixed |
| Planning | core+work+plan | Y without analysis | Manual plans | co-location → fixed |
| Approval | +approval | Y | Approve/reject | co-location → fixed |
| Execution | +session+execution | Y | Workspaces | — |
| WhatsApp | hub+core+work+whatsapp | Y | Intake→work | — |
| OpenProject | +openproject+sync | Y | OP-linked | — |
| Full | meta | Y | All menus/rules | — |

---

## 23. Workflow Dashboard Architecture

**Module:** `devhub_workflow`

- Depends: `devhub_work`
- Soft-discovers: analysis, plan, approval, session, execution, git, github, deploy, whatsapp, openproject
- Registry model (optional): `dev.workflow.capability` seeded by each capability module
- Stages: Intake → Analysis → Plan → Approval → Execution → Verify/PR → Deploy
- Absent modules → stage hidden; no hard imports
- Owns orchestration UI/KPIs; **does not** own analysis/plan/approval/execution business logic
- Core `dev.dashboard` remains minimal fallback

---

## 24. Database Migration Strategy

| Item | Action |
|------|--------|
| `_name` | Unchanged |
| Tables | Unchanged |
| Record IDs | Unchanged |
| Attachments / chatter | Same res_model/res_id |
| Ownership | Move Python class + views/security to new addon |
| Upgrade | `-i` new modules then `-u` work + dependents |
| Data copy | **None** |

Per moved model:

| Model | Old | New | Migration |
|-------|-----|-----|-----------|
| `dev.work.analysis` | work | analysis | move code/XML; `-i analysis -u work` |
| `dev.work.plan` (+step) | work | plan | same |
| `dev.work.approval` | work | approval | same |
| `dev.work.checkpoint` | work | execution | same |
| OP fields | work | openproject inherit | field defs move; table columns remain |

---

## 25. XML ID / Security Migration Strategy

- Prefer **stable XML IDs** under existing modules for one cycle via meta compatibility (`dev_session_hub` / noupdate bridges) to avoid breaking menus/favorites.
- New capability modules own new XML IDs for new views where safe.
- Groups remain in `devhub_core` (already shared).
- ACLs move with models; avoid duplicates.
- Record rules: gradually push from meta to owners; meta keeps aliases until D11 complete.
- Sequences/crons: move with owning capability; preserve name where possible.

---

## 26. Compatibility Meta Module Strategy

`dev_session_hub` final role:

```text
Meta installer (depends on full default stack)
Compatibility XML IDs / menu tree (during transition)
ir.rule bridge (until owners absorb)
Seed data + migrations
```

Users installing/upgrading `dev_session_hub` continue to receive the full default stack.  
It must **not** re-own primary business models.

---

## 27. Test Shadow Resolution Plan

| Item | Value |
|------|--------|
| Live conf | `pet_spot_elsahel_test_activation_staging.conf` |
| Overlay | `releases/addons_overlay_staging/dev_session_hub` **19.0.8.5.6** monolith |
| Canonical | `dev_session_hub` **19.0.9.0.0** meta |
| Test DB | `dev_session_hub` installed **19.0.8.5.5**; **no** `devhub_*` |

**Do not switch live Test until fresh matrix + clone rehearsal pass.**

Sequence:

1. Backup Test DB  
2. Clone → `pet_spot_elsahel_test_devhub_mig` (or similar)  
3. Run with `pet_spot_elsahel_test.conf` (canonical-only)  
4. Install/upgrade modular path on clone  
5. UAT  
6. Cut live Test only after sign-off  
7. Keep overlay as archive — **do not delete**

Rollback: restore conf to staging activation + DB backup.

---

## 28. Fresh Acceptance Test Strategy

Preferred DB: new disposable DB or clean install sequence on isolated port.

Order:

1. Core only  
2. Core + Work  
3. + Analysis (+ Generation)  
4. + Plan  
5. + Approval  
6. + Execution/Session  
7. Integrations one-by-one (OP, WhatsApp, Git…)  
8. Full meta  

Full-stack-only install is **not** sufficient proof of modularity.

---

## 29. Existing Database Migration Strategy

1. Prove matrix on fresh DB  
2. Upgrade `devhub_modular_fresh` in place (`-i` new modules, `-u` changed)  
3. Rehearse Test on **clone**  
4. Production: **out of scope** (Dev Hub modular stack not installed)

---

## 30. Risks and Rollback

| Risk | Mitigation |
|------|------------|
| Soft FSM gates wrong | Module-presence tests per transition |
| XML ID duplication | Meta bridge one release |
| Live Test accidental upgrade | Clone-only until signed |
| Generation worker break | Dual-path `service_complete` one release |
| Missing menus on partial install | Document; workflow/meta optional |

**Rollback:** revert code/XML; tables unchanged → `-u` previous addon layout.

---

## 31. Ordered Implementation Phases

| Phase | Focus |
|-------|--------|
| D0 | Write this plan; freeze baseline SHA |
| D1 | Runtime truth + Test shadow plan evidence (no live switch) |
| D2 | Core purity confirmation |
| D3 | Optionalize OpenProject |
| D4 | Extract `devhub_analysis` |
| D5 | Extract `devhub_plan` |
| D6 | Extract `devhub_approval` + mixin |
| D7 | Generation kind registry |
| D8 | Checkpoint → execution; shared constants |
| D9 | WhatsApp/OP boundary verification |
| D10 | `devhub_workflow` foundation |
| D11 | Meta cleanup |
| D12 | Fresh independent-install matrix |
| D13 | Migrate `devhub_modular_fresh` |
| D14 | Test clone canonical rehearsal |
| D15 | UAT evidence |

---

## 32. Exact First Execution Phase

**D0 (this document) + D1 pin/shadow docs**, then D3→D15 implementation on non-Production DBs only.

---

## Module Disposition Table

| Current Module | Current Role | Proposed Final Role | Keep | Split | Merge | Compatibility |
|----------------|--------------|---------------------|------|-------|-------|---------------|
| `devhub_core` | Registry | Registry | Yes | — | — | — |
| `devhub_work` | Monolith | Core work only | Yes | analysis/plan/approval/OP | — | Thin inherits |
| `devhub_generation` | Hardcoded kinds | Engine + registry | Yes | kinds → analysis/plan | — | — |
| `devhub_execution` | Workspace | Workspace + checkpoint | Yes | — | checkpoint | — |
| `devhub_session` | Sessions | Sessions | Yes | — | — | — |
| `devhub_git/github/deploy` | Providers | Providers | Yes | later approval mixin | — | — |
| `devhub_code_analysis` | Inspection | Analysis provider | Yes | — | — | — |
| `devhub_outbox` | Lease outbound | Same | Yes | — | — | — |
| `devhub_openproject` | OP UI | OP fields + UI | Yes | — | work OP fields | — |
| `devhub_whatsapp` | Hub consumer | Same | Yes | — | — | — |
| `devhub_odoo_runtime` / `infrastructure` | Providers | Same | Yes | — | — | — |
| `dev_session_hub` | Meta+menus+rules | Meta/compat | Yes | push menus/rules gradually | — | Primary |
| `devhub_analysis` | — | Analysis | **Create** | — | — | — |
| `devhub_plan` | — | Plan | **Create** | — | — | — |
| `devhub_approval` | — | Approval | **Create** | — | — | — |
| `devhub_workflow` | — | Orchestration | **Create** | — | — | — |

---

## Recommended Final Module List

`devhub_core`, `devhub_work`, `devhub_analysis`, `devhub_plan`, `devhub_approval`, `devhub_generation`, `devhub_code_analysis`, `devhub_session`, `devhub_execution`, `devhub_git`, `devhub_github`, `devhub_deploy`, `devhub_odoo_runtime`, `devhub_infrastructure`, `devhub_outbox`, `devhub_openproject`, `devhub_whatsapp`, `devhub_workflow`, `dev_session_hub` (meta).
