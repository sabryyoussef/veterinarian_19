# Dev Hub Modularization + WhatsApp Intake — Final Evidence Report

**Date:** 2026-07-23  
**Acceptance DB:** `devhub_modular_fresh`  
**Evidence root:** `/home/sabry/odoo_base/base_odoo_19/projects/pet_spot_elsahel/docs/devhub_modular_uat_20260723`

---

## A. Canonical Source

| Item | Value |
|------|-------|
| Repository | `git@github.com:sabryyoussef/veterinarian_19.git` (path `base_odoo_19/projects/pet_spot_elsahel`) |
| Branch | `feature/devhub-modularization-whatsapp` |
| Canonical baseline commit | `43a2a7f693557b55fbb7818adf5f5517061caa6d` (ff53a8d / **19.0.8.8.0** era) |
| Canonical path (pre-split) | `/home/sabry/odoo_base/base_odoo_19/projects/pet_spot_elsahel/dev_session_hub` |
| Pin evidence | `baseline/CANONICAL_SOURCE.json` |
| Backups | `baseline/dev_session_hub_wt_backup`, `baseline/dev_session_hub_pinned_ff53a8d` |

Decision: pinned the complete 19.0.8.8.0 / ff53a8d Dev Hub tree (machine verification, Odoo runtime, OpenProject tabs, code/DB analysis, work lifecycle) as the modularization baseline.

---

## B. Fresh Acceptance Environment

| Item | Value |
|------|-------|
| Database | `devhub_modular_fresh` (genuinely fresh; not a clone) |
| Config | `base_odoo_19/config/projects/devhub_modular_fresh.conf` |
| Service / port | dedicated process on **127.0.0.1:8032** (PID observed during UAT) |
| URL | http://127.0.0.1:8032 |
| Odoo version | **19.0** |
| Install log | `install_attempt14.log` (EXIT 0, 69 modules) |

Production (`pet_spot_elsahel` :8027) and existing test (`pet_spot_elsahel_test` :8028) were left running and untouched.

---

## C. Implemented Modules

| Module | Version | State | Responsibility |
|--------|---------|-------|----------------|
| `devhub_core` | 19.0.9.0.0 | installed | Registry identity: project/client/machine/repository/environment/policy/task.link/dashboard; root security groups; base menus |
| `devhub_work` | 19.0.9.0.0 | installed | Work lifecycle: work.item, source.message, analysis, plan, approvals, checkpoints, communications |
| `devhub_session` | 19.0.9.0.0 | installed | Sessions + session events / launch-resume |
| `devhub_execution` | 19.0.9.0.0 | installed | Execution workspaces, leases, governed execution helpers |
| `devhub_outbox` | 19.0.9.0.0 | installed | External outbound event queue |
| `devhub_generation` | 19.0.9.0.0 | installed | Analysis/plan generation requests + worker lease RPCs |
| `devhub_git` | 19.0.9.0.0 | installed | Local git commit/push approvals & records |
| `devhub_github` | 19.0.9.0.0 | installed | GitHub App, PR/merge, allowlists, discovery |
| `devhub_deploy` | 19.0.9.0.0 | installed | Deploy targets/approvals/records/rollback/promotion |
| `devhub_odoo_runtime` | 19.0.9.0.0 | installed | Shared Odoo runtime definitions + env/runtime links |
| `devhub_infrastructure` | 19.0.9.0.0 | installed | Machine / Tailscale / SSH verification |
| `devhub_openproject` | 19.0.9.0.0 | installed | OP project mappings & Work Package / Odoo task tabs |
| `devhub_code_analysis` | 19.0.9.0.0 | installed | Code + database analysis actions/UI |
| `devhub_whatsapp` | 19.0.9.0.0 | installed | WhatsApp sources, intake candidates, ingest RPC |
| `dev_session_hub` | 19.0.9.0.0 | installed | Compatibility/meta bridge (menus, seeds, XML IDs, full-stack deps) |
| `openproject_sync` | 19.0.1.6.0 | installed | Sibling OP sync (not merged into Dev Hub) |
| `project` | 19.0.1.3 | installed | Odoo Project dependency |

---

## D. Final Dependency Graph

```text
base, mail, web
        ↓
   devhub_core
     ├─→ devhub_odoo_runtime
     ├─→ devhub_infrastructure
     └─→ devhub_work (+ project, openproject_sync)
            ├─→ devhub_session → devhub_execution
            │                      ├─→ devhub_git → devhub_github → devhub_deploy
            ├─→ devhub_outbox
            ├─→ devhub_generation
            ├─→ devhub_openproject (+ openproject_sync)
            ├─→ devhub_code_analysis (+ devhub_odoo_runtime)
            └─→ devhub_whatsapp
                    ↓
              dev_session_hub  (depends on entire stack)
```

No circular dependencies. Core does **not** depend on WhatsApp, GitHub, OpenProject, Tailscale/SSH, or deploy.

**Decision documented:** `devhub_work` depends on `openproject_sync` because work items retain first-class `op_backend_id` Many2one (preserving existing contracts). Core remains free of that dependency.

---

## E. Dev Hub Modularization Results

Monolithic `dev_session_hub` models/views/security were redistributed by ownership:

- **Core:** `dev_registry` identity plane + base ACL/groups/menus
- **Work:** `dev_work*` lifecycle models
- **Session / Execution:** session + workspace/lease/execution
- **Outbox / Generation:** outbound queue + generation leases (`service_lease`, `service_ack_*`, `import_*_draft`, etc.)
- **Git / GitHub / Deploy:** split local git vs GitHub vs deployment
- **Odoo Runtime / Infrastructure:** optional runtime + verification
- **OpenProject / Code Analysis:** optional UI/helpers
- **WhatsApp:** optional intake
- **Bridge (`dev_session_hub`):** seed data, preserved `dev_session_hub.*` menu/group XML IDs, installs full stack

Technical model names (`dev.*`) and PostgreSQL tables preserved; optional fields use `_inherit`.

---

## F. Compatibility Results

| Check | Result |
|-------|--------|
| Technical model names preserved | Yes (`dev.project`, `dev.work.item`, …) |
| Important XML IDs preserved under `dev_session_hub.*` | Yes (menus, seeds, policy/project/env refs) |
| Groups | Moved to `devhub_core.group_dev_hub_*` (tests/code updated) |
| RPC / worker method names | Preserved on generation/outbox/whatsapp services |
| Existing test DB upgrade | Not used as final acceptance; fresh DB is authoritative. Policy/env seed repaired for modular fresh env without breaking petspot_test policy scope. |

---

## G. WhatsApp Architecture (implemented)

```text
WhatsApp
  → Evolution
  → n8n (evolution-whatsapp)
  → Bridge
  → Chatwoot inbox
  → n8n (chatwoot-ai-analysis)
  → Dev Hub intake RPC  [dev.whatsapp.intake.service_ingest_message]
  → dev.work.source.message
  → dev.whatsapp.intake (candidate)
  → human confirm
  → dev.work.item
  → analysis → plan → (normal Dev Hub lifecycle)
```

No second Evolution→Odoo webhook was created.

**UAT evidence type for intake path:** **replayed** Chatwoot-normalized payload via Odoo shell (not live WhatsApp delivery).

---

## H. Whitelist Pilot

| Item | Value |
|------|-------|
| Pilot group | `testopenclow` |
| JID (from `/home/sabry/nextcloud/group-project-map.json`) | `120363411424964076@g.us` |
| Intake mode | `devhub` |
| Sender policy | `any_member` |
| Control group | `dev-needed` → `120363422104853335@g.us` → `legacy_op_only` |

---

## I. Anti-Duplication Result

1. **Dev Hub ingest** returns `skip_openproject_autocreate: true` when source `intake_mode=devhub`.
2. **n8n live workflow** `chatwoot-ai-analysis` (`gKMYWKVT5FtUAFwB`) patched in Evaluate Auto-Create Gates with marker `DEVHUB_INTAKE_MODE_SKIP`:
   - Pilot JID forces `failures.push('devhub_intake_mode')` → blocks legacy OP auto-create.
3. Backup: `/home/sabry/infra/n8n/backups/workflows/chatwoot-ai-analysis-devhub-pilot-20260722T221745Z.json`
4. Non-pilot groups retain prior gate behavior.

---

## J. Automated Tests

Suite: `--test-tags=/devhub_whatsapp,/devhub_work,/devhub_session,/devhub_git,/devhub_openproject,/devhub_code_analysis,/devhub_infrastructure`  
Log: `tests_modular_suite4.log`

| Metric | Count |
|--------|-------|
| **Passed** | **176 reported by Odoo loader (`0 failed, 0 error(s)`)** |
| **Failed** | **0** |
| **Errors** | **0** |
| **Skipped (legitimate external fixtures)** | **3+** |

Explicit skips:
- `TestCodeDatabaseAnalysis` — TOURZ pilot fixtures missing on fresh DB
- `test_deploy_requires_merged_reviewed_and_distinct_users` — no `merged_reviewed` workspace fixture
- `test_preexisting_operational_github_installation_untouched` — operational GitHub installation not present (by design on fresh DB)

Notes:
- SQL `duplicate key` log lines during UniqueViolation **negative tests** are expected (constraints proven); they are not failures.
- WhatsApp unit tests: 4/4 green (`tests_whatsapp.log`).

---

## K. Browser UAT

Against **http://127.0.0.1:8032** / DB `devhub_modular_fresh` — **35/35 screenshots OK**.

| Screen | Result |
|--------|--------|
| Login / home | Pass |
| Dev Hub dashboard | Pass |
| Projects list + form | Pass |
| Environments / Repositories / Machines tabs & forms | Pass |
| Odoo Project & Tasks + OpenProject Work Packages tabs | Pass |
| Odoo Runtime | Pass |
| Work Items + Analysis + Plan tabs | Pass |
| Sessions | Pass |
| Execution Workspaces (list; empty on seed) | Pass (list loads) |
| WhatsApp Sources + form | Pass |
| WhatsApp Intake + source messages tab | Pass |
| Source Messages | Pass |
| Generation / Outbox / Analysis & Plan revisions | Pass |

Details: `browser_uat_results.json`

---

## L. Screenshots

Directory: `docs/devhub_modular_uat_20260723/screenshots/`

| File | Description |
|------|-------------|
| `01_home_after_login.png` | Admin home on fresh DB |
| `03_devhub_dashboard.png` | Dev Hub dashboard |
| `04_projects_list.png` | Projects list |
| `05_project_form.png` | Project form |
| `05_project_tab_environments.png` | Environments tab |
| `05_project_tab_repositories.png` | Repositories tab |
| `05_project_tab_guardrails.png` | Guardrails tab |
| `05_project_tab_odoo_project_and_tasks.png` | Odoo Project & Tasks |
| `05_project_tab_openproject_work_packages.png` | OpenProject WPs |
| `06_environments.png` / `06b_environment_form.png` | Environments |
| `07_repositories.png` / `07b_repository_form.png` | Repositories |
| `08_machines.png` / `08b_machine_form.png` | Machines |
| `09_odoo_runtime.png` / `09b_runtime_form.png` | Odoo Runtime |
| `10_work_items.png` | Work Items list |
| `11_work_item_form.png` | Work Item form |
| `11_work_item_tab_analysis.png` | Analysis tab |
| `11_work_item_tab_plan.png` | Plan tab |
| `14_sessions.png` / `14b_session_form.png` | Sessions |
| `15_execution_workspace.png` | Execution Workspaces list |
| `18_whatsapp_sources.png` / `18b_whatsapp_source_form.png` | WA sources |
| `19_whatsapp_intake.png` | Intake list |
| `20_whatsapp_intake_form.png` | Intake candidate |
| `20_whatsapp_intake_tab_source_messages.png` | Linked source messages |
| `21_source_messages.png` / `21b_source_message_form.png` | Source messages |
| `23_generation.png` | Generation |
| `24_outbox.png` | Outbox |
| `25_analysis_revisions.png` | Analysis revisions |
| `26_plan_revisions.png` | Plan revisions |

---

## M. Data Verification (fresh DB)

| Record type | Count |
|-------------|------:|
| Projects | 1 |
| Machines | 1 |
| Repositories | 1 |
| Environments | 2 |
| Odoo Runtimes | 1 |
| Work Items | 1 (confirmed from intake) |
| Analysis | 1 |
| Plans | 1 |
| Sessions | 1 |
| WhatsApp Sources | 2 (pilot `devhub` + `dev-needed` `legacy_op_only`) |
| WhatsApp Intakes | 1 (confirmed → work item) |
| Source Messages | 2 (grouped onto same intake) |

---

## N. Production Safety Confirmation

**Production was not modified.**

- No installs/upgrades/restarts against `pet_spot_elsahel` (:8027).
- Acceptance work used only `devhub_modular_fresh` (:8032) and optional test-tagged runs on that DB (port 8033 for tests).
- Existing test DB (:8028) was not used as final acceptance.
- n8n change is limited to anti-duplication gate for the pilot JID (workflow backup retained).

---

## O. Remaining Issues / Non-critical Follow-ups

1. **n8n → Dev Hub intake RPC node** is not yet added; only the OP auto-create skip for the pilot JID is live. Intake UAT used **replayed** RPC payloads.
2. **Execution workspace** UAT seed did not create a proposal row (approval/policy gated); list UI verified empty.
3. **Code analysis TOURZ fixtures** not present on fresh DB → automated analysis tests soft-skip (expected).
4. Playwright browser packages do not officially support this host OS; UAT used a cached Chromium binary via `executable_path`.
5. Optional future: wire Chatwoot→n8n HTTP call to fresh/test Odoo `service_ingest_message` for live pilot messages.

None of the above blocks the modular architecture acceptance on the fresh database.
