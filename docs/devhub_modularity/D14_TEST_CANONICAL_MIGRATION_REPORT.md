# D14 — Test Canonical Migration Report

**Date (UTC):** 2026-07-23  
**Verdict:** **TEST CANONICAL CUTOVER READY WITH CONDITIONS**  
**Live Test switched:** **NO** (rehearsal only)  
**Production touched:** **NO**

Evidence pack: `docs/devhub_modularity/d14_live_test_migration/`

---

## A. Live Test Baseline

| Item | Value |
|------|--------|
| PID | `299149` |
| Cmdline | `.../odoo-bin -c .../pet_spot_elsahel_test_activation_staging.conf -d pet_spot_elsahel_test` |
| Port | `8028` |
| Config | `pet_spot_elsahel_test_activation_staging.conf` |
| Addons path | community + enterprise + **`releases/addons_overlay_staging`** + `projects/pet_spot_elsahel` |
| Overlay | `addons_overlay_staging/dev_session_hub` → `veterinarian_19_staging_791cd1b` **19.0.8.5.6** |
| DB installed hub | `dev_session_hub` **19.0.8.5.5** |
| `devhub_*` | **none installed** |
| Filestore | shared `.filestore` (346M tree) |
| Git branch | `feature/devhub-modularization-whatsapp` |
| HEAD | `5d627a7e4b6ec4a29928dfd3c57f3fcf000f66cc` (dirty working tree with modular wave) |

### Module inventory (selected)

| Module | Version | State |
|--------|---------|-------|
| `dev_session_hub` | 19.0.8.5.5 | installed |
| all `devhub_*` | — | uninstalled |
| `openproject_sync` | 19.0.1.6.0 | installed |
| `whatsapp_hub` | 19.0.1.0.0 | installed |

### Data baseline (counts)

See `baseline/data_counts.txt`. Highlights: work items **45**, analyses **47**, plans **25**, steps **87**, approvals **21**, checkpoints **18**, sessions **23**, generations **32**, OP-linked work **45/45**, chatter on work **186**.

---

## B. Clone Details

| Item | Value |
|------|--------|
| Clone DB | `pet_spot_elsahel_test_modular_mig` |
| Port | **8041** (loopback only) |
| Config | `config/projects/pet_spot_elsahel_test_modular_mig.conf` |
| Filestore | `.filestore_test_modular_mig` (copy of Test filestore DB dir) |
| Backup dump | `.migration_backups/d14_20260723T080408Z/pet_spot_elsahel_test.dump` (18M) |
| Addons path | community + enterprise + **canonical `pet_spot_elsahel` only** |
| Overlay | **absent** |

Restore verified: `dev_work_item` count **45** immediately after restore.

---

## C. Runtime Addons Path Comparison

| Env | Overlay | Canonical project tree |
|-----|---------|------------------------|
| Live Test | **YES** (`addons_overlay_staging` first) | yes (shadowed for hub) |
| Migration clone | **NO** | yes (sole custom path) |

---

## D. Shadow Resolution

| Module | Live Test Source | Clone Source | Installed (after) | Canonical Manifest |
|--------|------------------|--------------|-------------------|--------------------|
| `dev_session_hub` | overlay **19.0.8.5.6** | canonical project | **19.0.9.1.0** meta | 19.0.9.1.0 |
| `devhub_work` | canonical (not installed) | canonical | 19.0.9.1.0 | 19.0.9.1.0 |
| `devhub_analysis` | canonical (not installed) | canonical | 19.0.9.1.0 | 19.0.9.1.0 |
| `devhub_plan` | canonical (not installed) | canonical | 19.0.9.1.0 | 19.0.9.1.0 |
| `devhub_approval` | canonical (not installed) | canonical | 19.0.9.1.0 | 19.0.9.1.0 |
| `devhub_generation` | canonical (not installed) | canonical | 19.0.9.1.0 | 19.0.9.1.0 |
| `devhub_openproject` | canonical (not installed) | canonical | 19.0.9.1.0 | 19.0.9.1.0 |
| `devhub_workflow` | canonical (not installed) | canonical | 19.0.9.1.0 | 19.0.9.1.0 |

Checks: `CLONE_OVERLAY_ABSENT|PASS`, `CLONE_CANONICAL_HUB|PASS`.

---

## E. Module Install/Upgrade Sequence

Derived topo order used (no `-u all`):

1. **Pre-glue (clone only):** remap `dev_session_hub.group_dev_hub_*` → `devhub_core.group_dev_hub_*` (preserve group IDs / memberships)
2. **A** `-i devhub_core`
3. **B** `-i devhub_work`
4. **C** `-i devhub_plan,devhub_approval,devhub_analysis`
5. **D** `-i devhub_generation,devhub_workflow`
6. **E** `-i devhub_session,devhub_execution`
7. **F** `-i devhub_outbox,devhub_odoo_runtime,devhub_infrastructure,devhub_git,devhub_github,devhub_deploy,devhub_code_analysis`
8. **G** `-i devhub_openproject,devhub_whatsapp`
9. **H** `-u dev_session_hub` → **19.0.9.1.0** meta

Logs: `upgrade/*.log`, `upgrade/phases.log`.

**Note:** During F, hub was temporarily skipped (`depends not loaded` until OP/WhatsApp present). Resolved by G then H.

---

## F. Module Versions Before/After

### Before (clone = live Test)

Only `dev_session_hub` 19.0.8.5.5 among Dev Hub; all `devhub_*` uninstalled.

### After

See `upgrade/after_module_state.txt` — full functional stack installed; hub **19.0.9.1.0**.

Parity with `devhub_modular_fresh`: **19/19** installed Dev Hub modules, versions match (`compare/module_versions_diff.txt` empty).

---

## G. Model Ownership Verification

Tables/`_name` unchanged. Functional owners after migration:

| Model | Owning capability module (XML) |
|-------|--------------------------------|
| `dev.work.item` | `devhub_work` (+ inherits) |
| `dev.work.analysis` | `devhub_analysis` |
| `dev.work.plan` / `.step` | `devhub_plan` |
| `dev.work.approval` | `devhub_approval` |
| `dev.work.checkpoint` | `devhub_execution` |

Evidence: `validation/model_ownership_xmlids.txt`. No table renames. No ID remaps.

---

## H–K. Capability Migrations

| Area | Before → After | IDs | Orphans |
|------|----------------|-----|---------|
| Analysis | 47 → 47 | SAME | 0 |
| Plan / steps | 25 / 87 → 25 / 87 | SAME | 0 |
| Approval | 21 → 21 | SAME | 0 |
| Checkpoint | 18 → 18 | SAME | 0 |

Manual plan without Analysis remains architecturally supported (`devhub_plan` does not depend on `devhub_analysis`).

---

## L. OpenProject Independence

| Check | Result |
|-------|--------|
| `devhub_work` depends | `devhub_core`, `project` only — **no** `openproject_sync` |
| OP fields present via | `devhub_openproject` inherit |
| OP depends | `devhub_work` + `openproject_sync` |
| OP-linked work items | **45 → 45** (backend + WP + URL) |
| Sample work OP backend | preserved (`OpenProject Main`) |

---

## M. Generation Registry Validation

| Check | Result |
|-------|--------|
| `GENERATION_KIND_REGISTRY` | `analysis`, `merge_analysis`, `plan` |
| Lease APIs present | `service_lease`, `service_mark_processing`, `service_complete`, `service_fail` |
| Generation rows | 32 preserved |

---

## N. WhatsApp Boundary Validation

| Check | Result |
|-------|--------|
| `devhub_whatsapp` depends | `devhub_work`, `whatsapp_hub` |
| Hub installed | yes |
| Generic Hub models owned by Dev Hub | **none** |
| `dev.whatsapp.intake` / `source` | present (intake count 0; source count 1 on clone) |
| Production intake | **not enabled** |

---

## O. Workflow Dashboard UAT

| Check | Result |
|-------|--------|
| Capabilities discovered | work → analysis → plan → approval → execution → git → deploy (all installed=True) |
| Stage summary | `Work → Analysis → Plan → Approval → Execution → Git / GitHub → Deploy` |
| KPIs | work visible 44 (ACL), analysis 47, plan 25, awaiting approval 4, execution 0 |
| Menu | `Dev Hub/Workflow` present |
| Server action | opens board form |

Screenshots: Playwright browsers not installed on host; UI validated via HTTP login **200** + XML-RPC board/menu smoke (`uat/xmlrpc_smoke.txt`). Login page reachable at `http://127.0.0.1:8041/web/login`.

---

## P. XML ID / Menu / Security Results

| Check | Result |
|-------|--------|
| Hub menus after upgrade | 37 XML IDs retained under `dev_session_hub.*` |
| Workflow menu | present (`menu_dev_session_hub_workflow`) |
| Group remap | 7 groups moved to `devhub_core.*` pre-install (required glue) |
| Rules | meta rules load against capability model XML IDs |
| Duplicate/conflict | no install-blocking External ID errors in phase logs / registry scan |

**Condition for live cutover:** apply the same group XML-ID remap before installing `devhub_core`.

---

## Q. Data Reconciliation

| Model | Before | After | Delta | Notes |
|-------|--------|-------|-------|-------|
| Core business work/analysis/plan/approval/checkpoint/session/generation/outbox/source | equal | equal | **0** | PASS |
| Work item IDs (sample 50) | — | — | **SAME** | PASS |
| FK orphans (analysis/plan/step/approval/checkpoint/source rel) | — | — | **0** | PASS |
| `dev_environment` | 13 | 14 | +1 | seed during meta upgrade |
| `dev_policy` | 9 | 10 | +1 | seed during meta upgrade |
| `dev_odoo_runtime` | 1 | 2 | +1 | seed `dev_odoo_runtime_master_19` |
| Chatter `mail_message` on work | 186 | 186 | 0 | PASS |
| OP links | 45 | 45 | 0 | PASS |

**Business data loss:** none. Deltas are explained seed additions only.

Admin XML-RPC `search_count` on work = **44** vs table **45** due to project membership record rules (expected).

---

## R. Registry / Functional UAT

| Check | Result |
|-------|--------|
| Clone server start | PASS (PID in `uat/server_8041.pid`) |
| `/web/login` | HTTP **200** |
| Critical ParseError / missing External ID / invalid views | **none** in registry scan |
| Models load | all required Dev Hub models present |
| Provider chain imports | `dev_git_constants.SHA1_RE` works |
| Menus | Dev Hub root, Workflow, Recent/Active Work |

Non-blocking warnings: legacy `_sql_constraints`, `ai.embedding` schema noise, social tracking parameter (pre-existing stack).

---

## S. Comparison with `devhub_modular_fresh`

| Dimension | Result |
|-----------|--------|
| Installed functional modules | **identical set (19)** |
| Module versions | **match** |
| Capability/workflow behavior | aligned |
| Data | different (expected — Test lineage vs fresh) |
| Architecture | **parity achieved** |

---

## T. Issues Found and Fixed

1. **Group XML IDs** still under `dev_session_hub` on Test lineage → remapped to `devhub_core` on clone before install.
2. **Hub temporarily unloadable** mid-sequence until `devhub_openproject` + `devhub_whatsapp` installed → fixed by ordering G before H.
3. **Playwright screenshots** unavailable (browser binaries missing) → documented RPC/HTTP evidence instead.

---

## U. Rollback Readiness

| Asset | Location |
|-------|----------|
| Pre-migration dump | `.migration_backups/d14_20260723T080408Z/pet_spot_elsahel_test.dump` |
| Live Test process | untouched on :8028 / staging conf |
| Overlay archive | `releases/addons_overlay_staging` **not deleted** |
| Clone | disposable; can `dropdb pet_spot_elsahel_test_modular_mig` |

Live rollback if a future cutover fails: restore dump + revert service to `pet_spot_elsahel_test_activation_staging.conf`.

---

## V. Final Verdict

```text
TEST CANONICAL CUTOVER READY WITH CONDITIONS
```

### GO criteria met

- Clone uses canonical addons only; zero active Dev Hub shadowing
- Capability stack installs/upgrades successfully
- Existing Test business data + IDs preserved
- OP links preserved
- WhatsApp Hub consumer boundary intact
- Workflow board works
- Registry clean for Dev Hub path
- Menu/security compatibility workable with documented group remap

### Conditions (must apply on live cutover)

1. Run group XML-ID remap (`dev_session_hub.group_dev_hub_*` → `devhub_core.group_dev_hub_*`) **before** `-i devhub_core`
2. Follow exact phase order A→H (especially G before H)
3. Expect +1 seed rows for environment/policy/runtime
4. Separate explicit authorization required before touching live Test
5. Keep overlay as rollback archive (do not delete)

---

## W. Exact Proposed Live Test Cutover Sequence

**Do not execute until separately authorized.**

1. Final backup of `pet_spot_elsahel_test` (DB + filestore)
2. Stop Test service (PID on :8028)
3. Switch systemd/service config from  
   `pet_spot_elsahel_test_activation_staging.conf`  
   → `pet_spot_elsahel_test.conf` (canonical addons only)
4. Verify addons_path contains **no** `releases/addons_overlay_*`
5. Apply group XML-ID remap SQL (same as clone)
6. Targeted installs (same phases A–G; no `-u all`)
7. `-u dev_session_hub` last (phase H)
8. Restart Test on :8028
9. Run reconciliation vs pre-cutover baseline
10. Full UAT (Workflow, Work, Analysis, Plan, Approval, OP, WhatsApp menus)
11. Rollback decision point (restore dump + staging conf if needed)

Overlay path `releases/addons_overlay_staging` remains as archive.

---

## Hard Constraints Compliance

| Constraint | Status |
|------------|--------|
| Production untouched | PASS |
| Live Test not switched | PASS |
| No `-u all` | PASS |
| No uninstalls | PASS |
| No overlay/worktree deletes | PASS |
| Preserve `dev.*` names/tables/IDs | PASS |
| `devhub_work` independent of OP | PASS |
| `devhub_whatsapp` Hub consumer | PASS |
| `dev_session_hub` meta/compat | PASS |
