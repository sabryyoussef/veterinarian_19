# P3–P8 Production Clone Rehearsal Report

**Executed:** 2026-07-23  
**Verdict:** **GO WITH CONDITIONS**  
**Production mutations:** **None**

Evidence root:

```text
docs/whatsapp_hub_consolidation/migration/p3_p8_rehearsal/
```

---

## M. Go / No-Go Decision

### **GO WITH CONDITIONS**

Clone rehearsal **proved** that the Production database can:

1. Install `whatsapp_hub` from the canonical tree  
2. Upgrade bridge / evolution / intake / clinic consumers in the mandatory order  
3. Keep campaign, template, bridge, and intake row counts intact  
4. Start a clean registry (no ParseError / missing XML ID / missing field for the migration scope)  
5. Accept idempotent hub ingest and link intake → hub message  

**Conditions before Production cutover (do not block clone success):**

| # | Condition | Why |
|---|-----------|-----|
| 1 | Deploy exact code pin **`4ce0387`** (or a descendant that includes that hub stack) | Rehearsal fingerprint |
| 2 | After install, assign Hub UI users to `whatsapp_hub.group_whatsapp_manager` (or User) | ACL is privilege-scoped; Settings admin does not auto-get Hub access |
| 3 | Restart Production HTTP workers after `-i`/`-u` | ACL/session cache; clone needed restart for Hub UI RPC to see groups |
| 4 | Keep mandatory order: `-i whatsapp_hub` **before** `-u` evolution/intake | Hard depends in manifests |
| 5 | Do **not** use `-u all` | Targeted list only |
| 6 | Optional: commit/stash remaining untracked `devhub_*` separately | Not required for this Production WA path |

**Non-blockers (pre-existing / noise):**

- `ai.embedding` “Model has no table” / missing not-null warnings (enterprise noise; not introduced by Hub)  
- Legacy `_sql_constraints` deprecation warnings on unrelated modules  
- Filestore path rename only matters for **renamed** clone DBs (symlink used on clone); Production keeps `pet_spot_elsahel`  

**No critical migration code fix was required.** Install/upgrade succeeded without weakening constraints.

---

## A. Reproducible Code Pin

| Item | Value |
|------|-------|
| Branch | `feature/devhub-modularization-whatsapp` |
| Pre-pin HEAD | `22e8b5414613da1e286b280c4884abd0cb3061d2` |
| **Rehearsal pin SHA** | **`4ce0387d45c13eae347e459d1683ee3886da57f4`** (`4ce0387`) |
| Dirty handling | Committed Hub + bridge/evolution/intake/clinic/social + consolidation docs (451 files). Remaining ~60 dirty paths are mostly untracked `devhub_*` (not upgraded on Production clone). |
| Runnable vs HEAD | Rehearsal used on-disk tree matching pin for WA stack modules |

Files: `code_pin.txt`, `pre_pin_git.txt`, `post_pin_remaining_dirty.txt`

---

## B. Production Clone

| Item | Value |
|------|-------|
| Clone DB | `pet_spot_elsahel_mig_rehearsal` |
| Filestore | `/home/sabry/odoo_base/base_odoo_19/projects/pet_spot_elsahel/.filestore_mig_rehearsal` (+ symlink `filestore/pet_spot_elsahel_mig_rehearsal` → `pet_spot_elsahel`) |
| Config | `/home/sabry/odoo_base/base_odoo_19/config/projects/pet_spot_elsahel_mig_rehearsal.conf` |
| Port | **8035** (`127.0.0.1` only) |
| URL | `http://127.0.0.1:8035` |
| Addons path | community + enterprise + `projects/pet_spot_elsahel` (canonical only) |
| Source backup | `.migration_backups/pet_spot_elsahel_20260723T060608Z.dump` |
| Traffic | No Production n8n / Evolution / Chatwoot pointed at clone |

---

## C. Module Install/Upgrade Results

| Module | Before | Action | After | Result |
|--------|--------|--------|-------|--------|
| `whatsapp_hub` | absent | `-i` | `19.0.1.0.1` installed | **PASS** (exit 0) |
| `integration_bridge_core` | `19.0.1.0.5` | `-u` | `19.0.1.1.1` | **PASS** |
| `evolution_whatsapp_chat` | `19.0.1.10.0` | `-u` | `19.0.1.10.1` | **PASS** |
| `petspot_wa_intake` | `19.0.1.0.0` | `-u` | `19.0.1.0.1` | **PASS** |
| `petspot_clinic_portal` | `19.0.2.2.1` | `-u` | `19.0.2.3.0` | **PASS** |
| `petspot_backend_sidebar` | `19.0.1.1.1` | `-u` | `19.0.1.1.1` | **PASS** |
| `petspot_campaign_rewards` | `19.0.1.2.0` | `-u` | `19.0.1.2.0` | **PASS** |
| `petspot_vet_feedback` | `19.0.1.0.0` | `-u` | `19.0.1.0.0` | **PASS** |
| `social_media_connector` | `19.0.1.0.0` | `-u` | `19.0.1.0.1` | **PASS** (`campaign_phone_marassi` alias present) |

Pending states after each step: **none** (`to install` / `to upgrade` / `to remove` empty).

Only new installed module vs Production: **`whatsapp_hub`**.

Logs: `p4_install_whatsapp_hub.log`, `p5_upgrade_bridge_evo_intake.log`, `p6_upgrade_consumers.log`

---

## D. `whatsapp_hub` Install Evidence

| Check | Result |
|-------|--------|
| Exit code | **0** |
| State | `installed` / `19.0.1.0.1` |
| Tables created | `whatsapp_message`, `whatsapp_message_event`, `whatsapp_outbound_message`, `whatsapp_group`, `whatsapp_contact`, `whatsapp_conversation`, `whatsapp_instance`, … |
| Models | `whatsapp.message`, `.outbound.message`, `.group`, `.contact`, `.conversation`, `.instance`, `.hub.compat`, … |
| Auto-install beyond hub | **None** (340 → 341 modules) |
| Constraint / XML failures | **None** for hub |

---

## E. Dependency Validation

| Check | Result |
|-------|--------|
| Hub installed before evolution/intake upgrades | **Yes** (mandatory order followed) |
| Bridge Python imports from intake/clinic | Still resolve (`odoo.addons.integration_bridge_core…`) |
| Evolution campaign ownership | `wa.campaign` / lines / templates preserved |
| Clinic chain | clinic portal upgraded to `19.0.2.3.0` with intake `19.0.1.0.1` |
| `campaign_phone_marassi` | Field present on `res.config.settings`; `default_get` returns alias keys |

---

## F. Database Integrity (before → after)

| Table | Baseline | After | Delta |
|-------|----------|-------|-------|
| `wa_campaign` | 14 | 14 | 0 |
| `wa_campaign_line` | 2257 | 2257 | 0 |
| `evo_wa_template` | 15 | 15 | 0 |
| `integration_bridge_log` | 127 | 127 | 0 |
| `integration_outbound_queue` | 127 | 127 | 0 |
| `integration_bridge_token` | 5 | 5 | 0 |
| `petspot_wa_intake` | 12 | 12 | 0 |
| `wa_message_log` | 2 | 2 | 0 |
| `whatsapp_message` | 0 | 2 | +2 (rehearsal ingest + outbound) |
| `whatsapp_outbound_message` | 0 | 1 | +1 (rehearsal) |

---

## G. Registry / XML / View Results

| Category | Critical errors in migration scope |
|----------|--------------------------------------|
| Registry startup (normal) | **0** — Modules loaded, registry OK |
| ParseError | **0** |
| External ID not found | **0** |
| Field does not exist | **0** |
| Invalid inheritance | **0** |
| View load (`get_views`) after ACL grant | Hub / campaign / intake **OK** |

Non-critical noise: `ai.embedding` table warnings; `_sql_constraints` deprecations; petget life-stage searchable warnings.

---

## H. Idempotency Smoke

Payload `chatwoot_message_id=880001` posted twice to `POST /whatsapp_hub/ingest` with bridge token:

| Call | Result |
|------|--------|
| 1st | `duplicate: false`, `message_id: 1` |
| 2nd | `duplicate: true`, `skipped: true`, same `message_id: 1` |
| DB | `COUNT(*) … chatwoot_message_id=880001` = **1** |

Evidence: `p7_idempotency.txt`

Consumer link: intake id 12 → `whatsapp_message_id=1` (`link_ok True`).

---

## I. UI Smoke

| Screen / check | Result | Evidence |
|----------------|--------|----------|
| Login page | 200 + screenshot | `screenshots/01_login.png` |
| Hub health JSON | 200 | `screenshots/02_hub_health.png` |
| JSON-RPC login | OK (uid 2) | `p7_ui_*` |
| Hub messages list/form views | OK after Manager group + worker restart | `p7_ui_hub_access_after_restart.txt` |
| Campaign views | OK | same |
| Intake views | OK | same |
| `/web` authenticated | 200 | UI summary |

Playwright Chromium not available on this host OS; firefox headless used for public pages. Authenticated Hub UI verified via JSON-RPC view/model loads.

---

## J. Compatibility Routes

| Route | Status |
|-------|--------|
| `GET /whatsapp_hub/health` | **200** `{"ok": true}` |
| `POST /whatsapp_hub/ingest` | **200** (idempotent) |
| `GET /bridge/inbound/health` | **200** |
| `OPTIONS /bridge/inbound` | **204** |
| `OPTIONS /bridge/evolution/webhook` | **204** |
| `GET /petspot/wa/intake/health` | **200** |
| `OPTIONS /petspot/wa/intake` | **204** |

No Production traffic sent.

---

## K. Production Safety

Confirmed:

```text
pet_spot_elsahel was not installed/upgraded/uninstalled/modified
```

| Check | Result |
|-------|--------|
| Production still on `pet_spot_elsahel.conf` / `:8027` | Yes (PID `3960576`) |
| Production `whatsapp_hub` installed? | **No** (count 0) |
| Production evolution version | still `19.0.1.10.0` |
| Production bridge version | still `19.0.1.0.5` |
| Production hub table | `to_regclass('whatsapp_message')` = NULL |

---

## L. Issues Found and Fixed

| Issue | Severity | Fix |
|-------|----------|-----|
| Clone filestore DB dirname mismatch | Medium (clone-only) | Symlink `…/filestore/pet_spot_elsahel_mig_rehearsal` → `pet_spot_elsahel` |
| Admin AccessError on Hub models until group + restart | Medium (ops) | Grant `whatsapp_hub.group_whatsapp_manager`; restart HTTP; document as cutover step |
| Playwright unavailable | Low (evidence) | Firefox headless + JSON-RPC view smoke |

**No module code change was required** to make install/upgrade pass.

---

## N. Exact Production Cutover Proposal (NOT EXECUTED)

Use code pin **`4ce0387`** (or approved successor containing the same stack).

```text
1. Final Production backup (DB dump + filestore snapshot)
2. Deploy exact rehearsed code fingerprint (4ce0387+)
3. Confirm addons_path remains canonical-only (already true on :8027)
4. -i whatsapp_hub --stop-after-init
5. -u integration_bridge_core --stop-after-init
6. -u evolution_whatsapp_chat,petspot_wa_intake --stop-after-init
7. -u petspot_clinic_portal,petspot_backend_sidebar,petspot_campaign_rewards,petspot_vet_feedback,social_media_connector --stop-after-init
8. Restart Production HTTP workers / gevent
9. Assign Hub UI users to WhatsApp Manager (or User) group
10. Integrity checks (module states, counts, hub health, one dry ingest if desired)
11. UI smoke (Hub menus, campaigns, intake, clinic)
12. Rollback decision point (restore dump + filestore; revert code if needed)
```

**Do not:** `-u all`, uninstall modules, delete overlays, change n8n Production routing, or point Evolution at Hub until separately approved.

---

## Success Condition

> A full clone of the current Production database successfully installs `whatsapp_hub` and upgrades the required legacy/consumer modules from the canonical source tree with clean registry startup, intact business data, valid views/XML, working compatibility contracts, and no critical database/module conflicts.

**Status: MET** (with ops conditions above for Production cutover).

Clone remains available for inspection:

```text
http://127.0.0.1:8035  (db=pet_spot_elsahel_mig_rehearsal)
```
