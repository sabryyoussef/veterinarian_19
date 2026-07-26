# Live Test Canonical Cutover Report

**Date:** 2026-07-23  
**Target DB:** `pet_spot_elsahel_test`  
**Port:** `8028`  
**Evidence pack:** [`live_test_canonical_cutover/`](./live_test_canonical_cutover/)

---

## A. Final Verdict

```text
LIVE TEST CANONICAL CUTOVER PASS WITH NON-BLOCKERS
```

Live Test successfully moved from overlay-shadowed legacy `dev_session_hub 19.0.8.5.5` to the canonical functional modular stack with meta `dev_session_hub 19.0.9.1.0`.

**Non-blockers (same class as D14 / pre-existing):**

- Admin XML-RPC `search_count(dev.work.item)` returns **44** while DB count is **45** (record-rule visibility; IDs preserved; OP links 45/45 at SQL).
- Journal `Traceback` during cutover window was **enterprise `ai.embedding` autovacuum**, not Dev Hub.
- Expected seed deltas: **+1 environment, +1 policy, +1 runtime** (documented below).

**Hard constraints held:** Production untouched; no Dev Hub on Production; no `-u all`; no uninstalls; overlay/worktrees/releases not deleted; WhatsApp Hub ownership unchanged; `devhub_work` has no hard `openproject_sync` dependency.

---

## B. Preflight State

| Item | Value |
|------|--------|
| Service at start | **DOWN** (no listener on `:8028`; systemd stopped / inactive) |
| Staging conf | `pet_spot_elsahel_test_activation_staging.conf` (still referenced by unit before switch) |
| Overlay on staging path | `releases/addons_overlay_staging` **active in conf** |
| Clone still running | `pet_spot_elsahel_test_modular_mig :8041` (D14 rehearsal; left alone) |
| Git branch | `feature/devhub-modularization-whatsapp` |
| HEAD | `5d627a7e4b6ec4a29928dfd3c57f3fcf000f66cc` |
| Dirty | ~87 files (modular working tree) |
| Production Dev Hub | all `devhub_*` / `dev_session_hub` **uninstalled** |

**Installed Dev Hub before cutover:**

| Module | State | Version |
|--------|-------|---------|
| `dev_session_hub` | installed | 19.0.8.5.5 |
| all `devhub_*` | uninstalled | — |
| `openproject_sync` | installed | (present) |
| `whatsapp_hub` | installed | 19.0.1.1.0 |

Evidence: `live_test_canonical_cutover/preflight/`

---

## C. Backup Evidence

| Artifact | Path / result |
|----------|----------------|
| Backup dir | `.migration_backups/live_test_cutover_20260723T082245Z/` |
| DB dump | `pet_spot_elsahel_test.dump` — **18M**, `dump_rc=0` |
| Filestore | `filestore/pet_spot_elsahel_test/` — **219M** |
| Configs | staging + canonical conf copies |
| Systemd | unit + drop-ins copied under backup |
| Module inventory | `modules_before.txt` |

**Gate:** DB and filestore backups succeeded before any write migration.

---

## D. Old Runtime / Overlay Evidence

**Before:**

- Config: `pet_spot_elsahel_test_activation_staging.conf`
- Addons path included: `releases/addons_overlay_staging` **before** `projects/pet_spot_elsahel`
- Overlay hub shadowed canonical `dev_session_hub`

**After:**

- Overlay directory **retained** (not deleted)
- Marked: `releases/addons_overlay_staging/INACTIVE_RUNTIME_ROLLBACK_REFERENCE.md`
- Staging drop-in renamed: `activation-staging-0960fcc.conf.disabled_cutover_20260723`
- New drop-in: `canonical-cutover.conf` → `pet_spot_elsahel_test.conf`

---

## E. Security XML ID Remap

**Method (exact D14):**

```sql
UPDATE ir_model_data
SET module = 'devhub_core'
WHERE module = 'dev_session_hub'
  AND model = 'res.groups'
  AND name LIKE 'group_dev_hub_%';
```

**Result:** 7 rows updated; 0 duplicate group names.

| XML ID | GID | Users (unchanged) |
|--------|-----|-------------------|
| `devhub_core.group_dev_hub_user` | 151 | 1 |
| `devhub_core.group_dev_hub_manager` | 152 | 2 |
| `devhub_core.group_dev_hub_integration` | 153 | 2 |
| `devhub_core.group_dev_hub_approver` | 154 | 1 |
| `devhub_core.group_dev_hub_generation` | 155 | 1 |
| `devhub_core.group_dev_hub_deploy_approver` | 156 | 0 |
| `devhub_core.group_dev_hub_production_approver` | 157 | 0 |

Evidence: `remap/pre_remap_groups.sql.log`, `remap/verify_after_remap.txt`

---

## F. Canonical Config Switch

| Concern | Before | After |
|---------|--------|-------|
| Runtime config | `…_activation_staging.conf` | `pet_spot_elsahel_test.conf` |
| Systemd ExecStart | staging conf | canonical conf (`canonical-cutover.conf`) |
| Overlay on path | **yes** | **no** |

Effective addons path:

```text
community/addons
enterprise
projects/pet_spot_elsahel
```

Module resolution proof: `dev_session_hub` → `projects/pet_spot_elsahel/dev_session_hub`  
Evidence: `runtime/module_resolution_proof.txt`, `runtime/systemd_after_switch.txt`

---

## G. Install Sequence

Proven D14 order on live DB with `--stop-after-init` and canonical conf:

| Phase | Command | Exit |
|-------|---------|------|
| A | `-i devhub_core` | 0 |
| B | `-i devhub_work` | 0 |
| C | `-i devhub_plan,devhub_approval,devhub_analysis` | 0 |
| D | `-i devhub_generation,devhub_workflow` | 0 |
| E | `-i devhub_session,devhub_execution` | 0 |
| F | `-i` providers (outbox, odoo_runtime, infrastructure, git, github, deploy, code_analysis) | 0 |
| G | `-i devhub_openproject,devhub_whatsapp` | 0 |

Evidence: `upgrade/phases.log`, per-phase `*.log`

---

## H. Upgrade Sequence

Targeted upgrades were performed as installs of missing capability modules (phases A–G). No `-u all`. Transitional module states after cutover: **0**.

---

## I. Meta Upgrade

| Phase | Command | Result |
|-------|---------|--------|
| H | `-u dev_session_hub` | exit 0 → **19.0.9.1.0** |

Meta remains installer + compatibility + migration glue; business model ownership stays on capability modules.

---

## J. Final Module Versions

Architecture parity vs `devhub_modular_fresh`: **19/19**

| Module | Version | State |
|--------|---------|-------|
| `dev_session_hub` | 19.0.9.1.0 | installed |
| `devhub_core` | 19.0.9.0.1 | installed |
| `devhub_work` | 19.0.9.1.0 | installed |
| `devhub_analysis` | 19.0.9.1.0 | installed |
| `devhub_plan` | 19.0.9.1.0 | installed |
| `devhub_approval` | 19.0.9.1.0 | installed |
| `devhub_generation` | 19.0.9.1.0 | installed |
| `devhub_workflow` | 19.0.9.1.0 | installed |
| `devhub_session` | 19.0.9.0.0 | installed |
| `devhub_execution` | 19.0.9.1.0 | installed |
| `devhub_outbox` | 19.0.9.0.0 | installed |
| `devhub_odoo_runtime` | 19.0.9.0.0 | installed |
| `devhub_infrastructure` | 19.0.9.0.0 | installed |
| `devhub_git` | 19.0.9.0.0 | installed |
| `devhub_github` | 19.0.9.0.0 | installed |
| `devhub_deploy` | 19.0.9.0.0 | installed |
| `devhub_code_analysis` | 19.0.9.1.0 | installed |
| `devhub_openproject` | 19.0.9.1.0 | installed |
| `devhub_whatsapp` | 19.0.9.0.2 | installed |
| `openproject_sync` | 19.0.1.6.0 | installed |
| `whatsapp_hub` | 19.0.1.1.0 | installed |

Evidence: `validation/final_module_versions.txt`, `validation/architecture_parity.txt`

---

## K. Model Ownership Validation

Primary owners (XML IDs present):

- `dev.work.item` → `devhub_work` (+ inherits)
- `dev.work.analysis` → `devhub_analysis`
- `dev.work.plan` → `devhub_plan`
- `dev.work.approval` → `devhub_approval`
- `dev.work.checkpoint` → `devhub_execution`
- `dev.whatsapp.intake` / `dev.whatsapp.source` → `devhub_whatsapp`
- `dev.project` → `devhub_core` (+ inherits)

`devhub_work` manifest depends: `['devhub_core', 'project']` — **no** `openproject_sync`.  
OP via `devhub_openproject` + `openproject_sync`.  
WhatsApp via `whatsapp_hub` → `devhub_whatsapp`.

Evidence: `validation/model_ownership_xmlids.txt`, `validation/manifest_depends.txt`

---

## L. Data Reconciliation

| Model | Before | After | Delta |
|-------|--------|-------|-------|
| `dev.work.item` | 45 | 45 | 0 |
| `dev.work.analysis` | 47 | 47 | 0 |
| `dev.work.plan` | 25 | 25 | 0 |
| `dev.work.plan.step` | 87 | 87 | 0 |
| `dev.work.approval` | 21 | 21 | 0 |
| `dev.work.checkpoint` | 18 | 18 | 0 |
| `dev.session` | 23 | 23 | 0 |
| `dev.work.generation` | 32 | 32 | 0 |
| `dev.work.source.message` | 45 | 45 | 0 |
| `dev.external.outbox` | 8 | 8 | 0 |
| `dev.environment` | 13 | 14 | **+1** |
| `dev.policy` | 9 | 10 | **+1** |
| `dev.odoo.runtime` | 1 | 2 | **+1** |

- Sample IDs: **identical** before/after  
- FK orphans (analysis/plan/approval/checkpoint/steps/generation): **0**  
- Business preserve: **OK**

Evidence: `reconcile/reconciliation.txt`, `reconcile/sample_ids_after.txt`, `reconcile/fk_orphans_fixed.txt`

---

## M. Expected Seed Deltas

Matches D14 rehearsal:

| Record | ID | Name |
|--------|----|------|
| Environment | 292 | Dev Hub Modular Fresh |
| Policy | 83 | Modular Fresh MVP |
| Runtime | 2 | Master Odoo 19 Runtime |

Additive seeds only; no business ID overwrite.

---

## N. OpenProject 45/45 Validation

| Check | Before | After |
|-------|--------|-------|
| `op_backend_id` set | 45 | 45 |
| `op_work_package_id` set | 45 | 45 |
| `op_url` set | 45 | 45 |

Sample work still carries OP URLs/WPs via XML-RPC. No duplicate WP creation performed.

---

## O. WhatsApp Boundary Validation

- `whatsapp_hub` remains installed (19.0.1.1.0)
- `devhub_whatsapp` installed as consumer (19.0.9.0.2)
- Models `dev.whatsapp.intake` / `dev.whatsapp.source` owned by `devhub_whatsapp`
- Production Dev Hub intake: still **not** installed / unaffected
- No new Production Dev Hub intake enabled

---

## P. Workflow Dashboard UAT

`dev.workflow.board` loads with adaptive stage summary:

```text
Work → Analysis → Plan → Approval → Execution → Git / GitHub → Deploy
```

KPIs (admin record rules): work 44, analysis 47, plan 25, awaiting approval 4.  
Menu: `Dev Hub/Workflow` present. Action `res_model=dev.workflow.board`.

Evidence: `uat/workflow_board_uat.txt`, `uat/xmlrpc_smoke.txt`  
(Screenshots: HTTP login 200; board validated via XML-RPC read — browser MCP not used for capture in this run.)

---

## Q. Registry / XML / Security Results

- All A–H phases exit **0**; registry loaded on restart
- No Dev Hub ParseError / missing External ID in cutover install logs
- Groups remapped under `devhub_core.group_dev_hub_*`; memberships preserved
- Unrelated journal Traceback: `ai.embedding` GC (enterprise) — non-blocker
- Critical Dev Hub registry scan: no Dev Hub-specific ParseError/External ID failures

---

## R. Runtime Shadow Removal Proof

```text
Live Test :8028
→ conf = pet_spot_elsahel_test.conf
→ addons_path = community + enterprise + projects/pet_spot_elsahel
→ NO_OVERLAY_IN_ADDONS_PATH
→ dev_session_hub resolves from projects/pet_spot_elsahel
→ overlay dir retained as INACTIVE_RUNTIME / ROLLBACK_REFERENCE
```

PID `2837553` cmdline uses canonical conf only.  
Evidence: `runtime/shadow_proof.txt`

---

## S. Service Health

| Check | Result |
|-------|--------|
| `systemctl --user is-active pet_spot_elsahel_test` | **active** |
| Port 8028 `/web/login` | **HTTP 200** |
| Drop-In | `canonical-cutover.conf` |
| DB accessible | yes |

---

## T. Issues Found and Fixed

| Issue | Handling |
|-------|----------|
| Test already stopped at cutover start | Documented; L3 noop; proceeded after backup |
| `ss`/awk PID parse quirk | Used systemd `MainPID` for shadow proof |
| Source-message FK column name differs | Used corrected orphan queries; 0 orphans |
| Admin sees 44/45 work items | Known record-rule non-blocker (D14 same) |
| AI embedding autovacuum Traceback | Pre-existing enterprise; not Dev Hub |

No rollback required.

---

## U. Rollback Status

**Not invoked.**

Rollback assets retained:

- DB dump + filestore under `.migration_backups/live_test_cutover_20260723T082245Z/`
- Staging conf file
- Overlay directory + disabled staging drop-in
- D14 clone DB/runtime still available on `:8041`

---

## V. Final Architecture State

Live Test is now the **canonical modular Dev Hub** runtime:

```text
canonical addons only
→ functional capability modules
→ meta/compat dev_session_hub 19.0.9.1.0
→ OpenProject via devhub_openproject + openproject_sync
→ WhatsApp via whatsapp_hub → devhub_whatsapp
→ Workflow Board discovers installed stages
→ Production unchanged (no Dev Hub)
```

### Before / After Summary

| Concern | Before | After |
|---------|--------|-------|
| Runtime config | `…_activation_staging.conf` | `pet_spot_elsahel_test.conf` |
| Addons path | community + enterprise + **overlay** + project | community + enterprise + project |
| `dev_session_hub` source | overlay-shadowed | `projects/pet_spot_elsahel` |
| `dev_session_hub` version | 19.0.8.5.5 | **19.0.9.1.0** |
| Functional modules | none installed | full stack installed |
| OpenProject dependency | monolith / hub | `devhub_openproject` (+ sync); work independent |
| WhatsApp ownership | Hub (+ legacy hub) | Hub → `devhub_whatsapp` consumer |
| Workflow dashboard | N/A / legacy | `devhub_workflow` adaptive board |
| Active shadow | **yes** | **no** (overlay archived inactive) |

---

## Success Condition

> Live `pet_spot_elsahel_test :8028` successfully moved from the overlay-shadowed legacy `dev_session_hub 8.x` runtime to the canonical functional modular Dev Hub stack and meta `dev_session_hub 19.0.9.1.0`, with preserved business data and record IDs, OpenProject links preserved 45/45, WhatsApp remaining a Hub consumer, Workflow Board operational, clean registry/security/XML for Dev Hub cutover, and zero active Dev Hub overlay shadowing.

**Met.**
