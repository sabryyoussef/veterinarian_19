# P0–P2 Execution Report — Production-Safe Module & Worktree Migration

**Executed:** 2026-07-23  
**Scope:** P0 Freeze → P1 Runtime Inventory → P2 Canonical Source Pin Preparation  
**WhatsApp operational status:** Not live on Production (no historical WA message migration in this phase)  
**Production mutations:** None (no install / upgrade / uninstall / delete / config change)

Evidence root:

```text
docs/whatsapp_hub_consolidation/migration/
  p0_freeze/
  p1_runtime/
  p2_pin/
```

---

## A. Freeze Baseline

### Git

| Item | Value |
|------|-------|
| Repository | `/home/sabry/odoo_base/base_odoo_19/projects/pet_spot_elsahel` |
| Branch | `feature/devhub-modularization-whatsapp` |
| Commit SHA | `22e8b5414613da1e286b280c4884abd0cb3061d2` (`22e8b54`) |
| Dirty state | **DIRTY** — ~421 uncommitted paths (modularization + hub + docs in working tree) |
| Related worktrees | 16 (canonical + `pet_spot_elsahel_dh_p0` + multiple `releases/` + `worktrees/`) |

Full dump: `p0_freeze/git_baseline.txt`

### Odoo version

- Production `base` module: **19.0.1.3** (`p0_freeze/odoo_base_version_prod.txt`)
- Runtime: Odoo **19.0**

### Database module inventory

| Database | Role | Port | Installed modules | Pending `to upgrade/install/remove` | `whatsapp_hub` |
|----------|------|------|-------------------|-------------------------------------|----------------|
| `pet_spot_elsahel` | PRODUCTION | 8027 | 340 | **none** | **absent** |
| `pet_spot_elsahel_test` | TEST | 8028 | 321 | **none** | installed `19.0.1.0.0` |
| `devhub_modular_fresh` | FRESH | 8032 | 72 | — | installed |
| `whatsapp_hub_fresh` | FRESH | 8034 | 40 | — | installed |

Per-DB dumps: `p0_freeze/modules_*.tsv`, `p0_freeze/all_installed_prod.txt`, `p0_freeze/focus_modules_prod.txt`

### Production focus modules (installed)

| Module | Installed version | Canonical manifest | Match? |
|--------|-------------------|--------------------|--------|
| `whatsapp_hub` | — (not installed) | `19.0.1.0.1` | n/a |
| `evolution_whatsapp_chat` | `19.0.1.10.0` | `19.0.1.10.1` | **NO** |
| `integration_bridge_core` | `19.0.1.0.5` | `19.0.1.1.1` | **NO** |
| `petspot_wa_intake` | `19.0.1.0.0` | `19.0.1.0.1` | **NO** |
| `petspot_clinic_portal` | `19.0.2.2.1` | `19.0.2.3.0` | **NO** |
| `petspot_campaign_rewards` | `19.0.1.2.0` | `19.0.1.2.0` | YES |
| `petspot_vet_feedback` | `19.0.1.0.0` | `19.0.1.0.0` | YES |
| `petspot_backend_sidebar` | `19.0.1.1.1` | `19.0.1.1.1` | YES |
| `social_media_connector` | `19.0.1.0.0` | `19.0.1.0.1` | **NO** |
| `developer_hub` | `19.0.1.1.0` | `19.0.1.1.0` | YES |
| `dev_session_hub` | uninstalled | `19.0.9.0.0` | n/a |
| `chatwoot_evolution_error_bridge` | uninstalled | `19.0.1.0.1` | n/a |

### Runtime processes (freeze)

| Service | Master PID | Conf | DB |
|---------|------------|------|-----|
| Production | `3960576` | `config/projects/pet_spot_elsahel.conf` | `pet_spot_elsahel` |
| Test | `299149` | `config/projects/pet_spot_elsahel_test_activation_staging.conf` | `pet_spot_elsahel_test` |
| Modular | `1977143` | `devhub_modular_fresh.conf` | `devhub_modular_fresh` |
| Hub fresh | `2087369` | `whatsapp_hub_fresh.conf` | `whatsapp_hub_fresh` |

### External integration baseline (no secrets)

| Item | Value |
|------|-------|
| n8n workflow | `chatwoot-ai-analysis` |
| Current workflow ID | `gKMYWKVT5FtUAFwB` |
| Latest backup | `/home/sabry/infra/n8n/backups/workflows/chatwoot-ai-analysis-hub-ingest-20260723T045647Z.json` |
| Prior backups | also `…-devhub-pilot-20260722T221745Z.json`, `…-20260720T192124Z.json` |
| Evolution containers | `evolution_api`, `petspot_evolution_api`, bridge `chatwoot_evolution_bridge` (:3010) |
| Compose refs | `projects/pet_spot_elsahel/evolution-api/docker-compose.yml` (sanitized dump in `p0_freeze/external/`) |
| Live pilot report | `docs/whatsapp_hub_consolidation/LIVE_PILOT_REPORT.md` |

Details: `p0_freeze/external/external_baseline.json`

### Production WA data volume (context only — not migration scope)

| Table | Rows |
|-------|------|
| `wa_message_log` | 2 |
| `evo_wa_template` | 15 |
| `petspot_wa_intake` | 12 |
| `integration_bridge_log` | 127 |
| `integration_outbound_queue` | 127 |
| `integration_bridge_token` | 5 |
| `wa_campaign` | 14 |
| `wa_campaign_line` | 2257 |

Hub tables (`whatsapp_message` / `whatsapp_thread` / `whatsapp_account`): **do not exist on Production**.

---

## B. Actual Runtime Addons Paths

Verified from live `/proc/<pid>/cmdline` (not conf alone).

### Production `:8027`

```text
/home/sabry/odoo_base/base_odoo_19/odoo19/odoo19/addons
/home/sabry/odoo_base/base_odoo_19/odoo19/odoo19/enterprise
/home/sabry/odoo_base/base_odoo_19/projects/pet_spot_elsahel
```

Plus Odoo-implicit: `odoo19/odoo19/odoo/addons` (core `base`) and filestore addons dir.

**No overlay. No releases/worktrees on Production path.**

### Test `:8028` (CRITICAL)

```text
/home/sabry/odoo_base/base_odoo_19/odoo19/odoo19/addons
/home/sabry/odoo_base/base_odoo_19/odoo19/odoo19/enterprise
/home/sabry/odoo_base/base_odoo_19/releases/addons_overlay_staging   ← SHADOWS CANONICAL
/home/sabry/odoo_base/base_odoo_19/projects/pet_spot_elsahel
```

Conf file: `pet_spot_elsahel_test_activation_staging.conf` (not the clean `pet_spot_elsahel_test.conf`).

Evidence: `p1_runtime/ACTUAL_RUNTIME_ADDONS_PATHS.txt`, `p1_runtime/prod_master_cmdline.txt`, `p1_runtime/test_master_cmdline.txt`

---

## C. Module Resolution Matrix

| Database | Module | Installed Version | Runtime Source Path | Manifest Version (that path) | Match? |
|----------|--------|-------------------|---------------------|------------------------------|--------|
| Production | `evolution_whatsapp_chat` | 19.0.1.10.0 | `…/projects/pet_spot_elsahel/evolution_whatsapp_chat` | 19.0.1.10.1 | **NO** (DB behind source) |
| Production | `integration_bridge_core` | 19.0.1.0.5 | `…/pet_spot_elsahel/integration_bridge_core` | 19.0.1.1.1 | **NO** |
| Production | `petspot_wa_intake` | 19.0.1.0.0 | `…/pet_spot_elsahel/petspot_wa_intake` | 19.0.1.0.1 | **NO** |
| Production | `petspot_clinic_portal` | 19.0.2.2.1 | `…/pet_spot_elsahel/petspot_clinic_portal` | 19.0.2.3.0 | **NO** |
| Production | `whatsapp_hub` | absent | would resolve to `…/pet_spot_elsahel/whatsapp_hub` | 19.0.1.0.1 | n/a |
| Production | `dev_session_hub` | absent | would resolve to canonical `19.0.9.0.0` | 19.0.9.0.0 | n/a |
| Test | `dev_session_hub` | 19.0.8.5.5 | **`…/releases/addons_overlay_staging/dev_session_hub`** | 19.0.8.5.6 | **NO** + **ACTIVE SHADOW** |
| Test | `whatsapp_hub` | 19.0.1.0.0 | `…/pet_spot_elsahel/whatsapp_hub` | 19.0.1.0.1 | **NO** |
| Test | `evolution_whatsapp_chat` | 19.0.1.10.1 | canonical | 19.0.1.10.1 | YES |
| Test | `integration_bridge_core` | 19.0.1.1.1 | canonical | 19.0.1.1.1 | YES |
| Test | `petspot_wa_intake` | 19.0.1.0.1 | canonical | 19.0.1.0.1 | YES |
| Modular / Hub fresh | focus stack | current | canonical only | current | registry OK |

JSON: `p1_runtime/module_resolution_matrix.json`

---

## D. Shadowing Risks

| Severity | Finding |
|----------|---------|
| **CRITICAL** | Test `:8028` loads `dev_session_hub` from `addons_overlay_staging` (**19.0.8.5.6**) instead of canonical (**19.0.9.0.0**). Installed DB version is **19.0.8.5.5**. |
| **HIGH** | Production installed versions lag canonical for WA-related modules; upgrading from current source **pulls `whatsapp_hub` as a hard dependency** of `evolution_whatsapp_chat` and `petspot_wa_intake`. |
| **HIGH** | Dozens of duplicate copies under `releases/`, `worktrees/`, `pet_spot_elsahel_dh_p0` (archive candidates). Not on Production path today, but dangerous if any conf is edited carelessly. |
| **MEDIUM** | Dirty Git tree (421 paths) — freeze SHA is pinned, but working tree ≠ commit. |
| **LOW** | Overlay only contains `dev_session_hub` among WA modules (other WA modules do not actively shadow on Test). |

Classification counts for key modules: CANONICAL 6 / ACTIVE_SHADOW 1 / INACTIVE_REFERENCE 3 / ARCHIVE_CANDIDATE 66.

Full: `p1_runtime/shadowing_classification.json`, `p1_runtime/flags.json`

---

## E. Dependency Graph

Canonical focus chain (topo-derived):

```text
whatsapp_hub ──────────────────────────────────────────────┐
integration_bridge_core ───────────────────────────────────┤
        │                                                  │
        ├─► chatwoot_evolution_error_bridge                │
        ├─► evolution_whatsapp_chat ◄──────────────────────┤
        └─► petspot_wa_intake ◄───────────────────────────┤
                │                                          │
                └─► petspot_clinic_portal                  │
                        ├─► petspot_backend_sidebar        │
                        ├─► petspot_campaign_rewards       │
                        └─► petspot_vet_feedback           │
                                                           │
devhub_* … ► devhub_whatsapp ◄─────────────────────────────┘
        └─► dev_session_hub (meta)
```

**Critical dependency change vs Production DB:**

```text
evolution_whatsapp_chat 19.0.1.10.1  depends: […, integration_bridge_core, whatsapp_hub]
petspot_wa_intake       19.0.1.0.1   depends: [integration_bridge_core, whatsapp_hub, …]
```

Production has **not** installed `whatsapp_hub`. Any `-u evolution_whatsapp_chat` / `-u petspot_wa_intake` against current source on a clone **requires `-i whatsapp_hub` first** (or Odoo will auto-install it as a dependency).

Order JSON: `p1_runtime/recommended_upgrade_order.json`

---

## F. Dependency Conflict Findings

1. **Hard hub dependency in source:** Upgrading Production modules from canonical tree without installing hub first will fail or auto-install hub — must be intentional on clone only.
2. **Python cross-addon imports** (not only manifest depends):
   - `petspot_wa_intake` → `odoo.addons.integration_bridge_core` (`controllers/intake_controller.py`)
   - `petspot_clinic_portal` → `odoo.addons.integration_bridge_core` (`controllers/portal.py`)  
   → Bridge module **cannot** be emptied without updating these imports.
3. **Campaign stack still owns** `wa.campaign`, `wa.campaign.line`, `wa.message.log`, templates — evolution must remain FULL until campaigns are rehomed.
4. **Clinic / sidebar / rewards** depend on intake + bridge models/XML — converting intake to a thin bridge too early breaks portal.
5. **Test overlay** can make Dev Hub meta behave as 8.x while docs assume 9.x modular stack — registry/view mismatches if Test is used as rehearsal without pin fix.
6. **No circular dependency** detected in the focus topo sort.

---

## G. Database Schema Risks

### Production

| Risk | Assessment |
|------|------------|
| Hub tables already present | **No** — safe to introduce `whatsapp_*` on clone |
| Model name overlap hub vs evolution | **No real `_name` collision** (only false positives from field attrs) |
| Field type conflicts hub vs evo on same model | **None material** (`p1_runtime/field_conflicts_static.json`) |
| Existing WA campaign schema | Present and populated (campaigns) — must survive hub install |
| Bridge queue/log tables | Present (`integration_*`) — must survive |
| Duplicate XML IDs in focus modules (DB) | None found in sampled query |

### Test (already dual-stack)

| Risk | Assessment |
|------|------------|
| `whatsapp_message` exists | Yes |
| `whatsapp_thread` | Missing in `to_regclass` check — verify on clone if hub upgrade expects it |
| Hub installed version behind source | `19.0.1.0.0` vs source `19.0.1.0.1` |
| Overlay + modular meta mismatch | `dev_session_hub` 8.x shadow vs 9.x source |

Historical message migration: **not required** for Production (2 `wa_message_log` rows; hub unused).

---

## H. XML / View Risks

| Check | Result |
|-------|--------|
| Custom `inherit_id` refs unresolved in custom tree | **0** (`p1_runtime/view_inherit_unresolved_custom.json`) |
| Hub vs evo XML local-id namespace | Separate modules — no forced complete_name clash |
| Risk on hub install | New menus/actions/security — standard; must load after hub models |
| Risk if evolution becomes empty bridge too soon | Campaign views / wizards would break |
| Security CSV model-before-dep | Mitigated by installing hub before upgrading consumers |

Static checks only — full XML load validation deferred to clone rehearsal (`-i`/`-u` with `--stop-after-init`).

---

## I. Safe Future Install/Upgrade Order (clone rehearsal only)

**Do not run on Production.**

### Recommended sequence

```text
# 1) Install hub (new)
-i whatsapp_hub

# 2) Upgrade bridge (no hub dep; schema/API prep)
-u integration_bridge_core

# 3) Upgrade WA providers/consumers that now depend on hub
-u evolution_whatsapp_chat,petspot_wa_intake

# 4) Upgrade portal / sidebar / campaign consumers
-u petspot_clinic_portal,petspot_backend_sidebar,petspot_campaign_rewards,petspot_vet_feedback

# Optional later (Dev Hub modular — not on Production today)
-i / -u  devhub_* then -u dev_session_hub
```

### `-i` vs `-u`

| Module | Action on Production clone |
|--------|----------------------------|
| `whatsapp_hub` | **`-i`** (not installed) |
| `integration_bridge_core`, `evolution_whatsapp_chat`, `petspot_wa_intake`, `petspot_clinic_portal`, … | **`-u`** (already installed, versions behind) |
| `devhub_*` / `dev_session_hub` | **not on Production** — skip unless clone goals include Dev Hub |

### Why `-u all` is unsafe

- Touches ~340 modules; long lock / high blast radius  
- Dirty/unrelated version drift (`veterinary_clinic`, `pos_stock`, etc.) may upgrade unexpectedly  
- Auto-installs dependency closures across the DB  
- Prefer **targeted** `-i`/`-u` list above

---

## J. Compatibility Requirements

| Old / related module | Decision | Why |
|----------------------|----------|-----|
| `evolution_whatsapp_chat` | **KEEP FULL** → later **BRIDGE** | Campaigns + templates + discuss still live here; consumers inherit models |
| `integration_bridge_core` | **KEEP FULL** → later **BRIDGE** | Tokens, queue, logs; **direct Python imports** from intake/clinic |
| `petspot_wa_intake` | **KEEP FULL** → later **SLIM/BRIDGE** | Clinic portal + sidebar depend on it |
| `petspot_clinic_portal` | **KEEP FULL** | Product UI; depends on intake/bridge |
| `petspot_campaign_rewards` | **KEEP FULL** | Depends on bridge + clinic |
| `chatwoot_evolution_error_bridge` | **LATER REMOVE** from graph | Uninstalled on Production |
| `dev_session_hub` | **KEEP FULL** (modular meta) | Not on Production; fix Test shadow before using Test as truth |
| `developer_hub` | **KEEP FULL** | Unrelated CRM partner hub |
| `whatsapp_hub` | **NEW canonical** | Install on clone first; Production later (separate approval) |

---

## K. Canonical Addons Path

### Current Production

```text
…/odoo19/odoo19/addons
…/odoo19/odoo19/enterprise
…/projects/pet_spot_elsahel
```

### Recommended Production (future pin — **not applied**)

```text
…/odoo19/odoo19/addons
…/odoo19/odoo19/enterprise
…/projects/pet_spot_elsahel
```

(Already correct. Keep implicit `odoo/addons` via Odoo. **Do not add** `releases/`, `worktrees/`, `addons_overlay_*`.)

### Current Test

```text
…/addons
…/enterprise
…/releases/addons_overlay_staging    ← REMOVE from future runtime
…/projects/pet_spot_elsahel
```

### Recommended Test

```text
…/odoo19/odoo19/addons
…/odoo19/odoo19/enterprise
…/projects/pet_spot_elsahel
```

Use `pet_spot_elsahel_test.conf` (already clean) instead of `pet_spot_elsahel_test_activation_staging.conf`.

### Paths to remove from future runtime resolution (do not delete disks)

| Path | Reason |
|------|--------|
| `releases/addons_overlay_staging` | Active Test shadow of `dev_session_hub` |
| `releases/addons_overlay_*` | Inactive references |
| `releases/veterinarian_19_*` | Archive / worktree checkouts |
| `worktrees/*` | Feature worktrees |
| `projects/pet_spot_elsahel_dh_p0` | Old DH-P0 tree |
| `projects/resume` (as addons root) | Unrelated unless intentional |

---

## L. Canonical Tree Gaps

| Check | Result |
|-------|--------|
| Every Production **custom** module present under `projects/pet_spot_elsahel` | **Yes** (false positive `base` is in `odoo/addons`, not `addons/`) |
| Required WA modules only in overlay? | **No** — only `dev_session_hub` is overlay-shadowed on Test; WA modules resolve from canonical |
| `whatsapp_hub` / `devhub_*` only in canonical | **Yes** (single copy) |
| Merge-from-overlay needed before pin? | **No merge required** for Production pin; for Test, **drop overlay** and reconcile `dev_session_hub` version intentionally |

Gaps file: `p2_pin/canon_gaps_prod.json`

---

## M. Production Safety Confirmation

| Action | Performed on Production? |
|--------|---------------------------|
| Install `whatsapp_hub` | **No** |
| Upgrade / uninstall any module | **No** |
| Change `pet_spot_elsahel.conf` | **No** |
| Delete code / overlays | **No** |
| n8n Production routing change | **No** |
| DB clone | **No** (P3+) |

Read-only: process inspection, SQL SELECTs, conf reads, non-prod `--stop-after-init` on `whatsapp_hub_fresh` and `devhub_modular_fresh`.

Dry-run registry:

- `whatsapp_hub_fresh`: **OK** (40 modules, exit 0) — `p2_pin/dryrun_hub_fresh_registry.txt`
- `devhub_modular_fresh`: **OK** (72 modules, exit 0) — `p2_pin/dryrun_modular_registry.txt`

---

## N. Exact Next Phase — P3 → P8 Production Clone Rehearsal

### Preconditions from P0–P2

1. Freeze SHA `22e8b54` (+ decide whether to commit dirty tree before clone).  
2. Canonical tree verified.  
3. Production addons_path already clean; Test must drop overlay before Test is trusted.  
4. Hub must be installed **before** upgrading evolution/intake from current manifests.

### P3 — Clone

- Create DB clone of `pet_spot_elsahel` (name e.g. `pet_spot_elsahel_mig_rehearsal`)  
- Clone filestore or point to copy  
- Dedicated conf: canonical addons_path only, unused HTTP port  
- **No** Production traffic

### P4 — Install hub

```text
-i whatsapp_hub --stop-after-init
```

Validate registry, models, menus, security.

### P5 — Upgrade bridge + providers

```text
-u integration_bridge_core,evolution_whatsapp_chat,petspot_wa_intake --stop-after-init
```

### P6 — Upgrade consumers

```text
-u petspot_clinic_portal,petspot_backend_sidebar,petspot_campaign_rewards,petspot_vet_feedback
```

### P7 — Integrity checks (dependency/schema — not historical WA migration)

- Module states clean  
- Campaign tables intact (`wa_campaign*`)  
- Bridge queue/tokens intact  
- Hub tables created; no constraint violations  
- Portal/actions open without XML errors  
- Optional: smoke ingest to hub on clone only

### P8 — Rehearsal report + go/no-go

- Document exact commands, timings, failures  
- Confirm Production still untouched  
- Gate: approval required before any Production cutover (P9+)

### Explicitly out of P3–P8

- Production install of hub  
- Uninstall of evolution/bridge  
- Deleting overlays/worktrees  
- Assuming large historical WhatsApp backfill (unless clone proves unexpected volume)

---

## Success condition (P0–P2)

> One verified canonical source tree (`projects/pet_spot_elsahel`) and a complete understanding of module dependencies, runtime shadowing, model/schema risks, XML/view conflicts, and required compatibility bridges — **before** any Production clone migration.

**Status: MET.**

Highest follow-ups before P3:

1. **CRITICAL:** Fix Test addons_path (remove overlay) when Test is used for any rehearsal trust.  
2. **HIGH:** On clone, always `-i whatsapp_hub` before `-u` of evolution/intake.  
3. **MEDIUM:** Commit or stash dirty tree so freeze SHA matches runnable code.
