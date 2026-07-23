# Production WhatsApp Hub Cutover Report (P9)

**Executed:** 2026-07-23  
**Final verdict:** **CUTOVER PASS WITH NON-BLOCKERS**  
**Rollback:** **Not required**

Evidence:

```text
docs/whatsapp_hub_consolidation/migration/p9_production_cutover/
```

---

## M. Final Verdict

```text
CUTOVER PASS WITH NON-BLOCKERS
```

Production successfully installed `whatsapp_hub` and upgraded the exact targeted modules using rehearsed pin **`4ce0387`** and the proven order. Business data deltas are **0**. Compatibility routes work. Registry starts clean for the migration scope. n8n / Evolution Production routing were **not** changed.

Non-blockers (do not justify rollback):

| Item | Notes |
|------|-------|
| Pre-existing `_sql_constraints` / petget searchable warnings | Unrelated to Hub; present before cutover |
| Bridge health JSON still embeds literal `"version": "19.0.1.0.0"` | Cosmetic string in controller; DB module version is `19.0.1.1.1` |
| Working tree still has ~90 dirty/untracked paths outside cutover stack | Cutover modules themselves match HEAD cleanly |
| One synthetic Hub message (`chatwoot_message_id=881001`) | Isolated cutover smoke; not customer traffic |

---

## A. Code Pin

| Item | Value |
|------|-------|
| Branch | `feature/devhub-modularization-whatsapp` |
| Deployed / HEAD SHA | **`4ce0387d45c13eae347e459d1683ee3886da57f4`** |
| Contains rehearsed pin | **YES** (HEAD == pin) |
| Cutover stack dirty vs HEAD | **NO** (clean for hub/bridge/evolution/intake/clinic/social) |
| Repo dirty overall | ~90 unrelated paths (mostly untracked `devhub_*`) |

Manifests at cutover: hub `19.0.1.0.1`, bridge `19.0.1.1.1`, evolution `19.0.1.10.1`, intake `19.0.1.0.1`, clinic `19.0.2.3.0`, social `19.0.1.0.1`.

---

## B. Backup Evidence

| Asset | Path |
|-------|------|
| Backup root | `/home/sabry/odoo_base/base_odoo_19/projects/pet_spot_elsahel/.migration_backups/p9_cutover_20260723T062315Z/` |
| DB dump | `…/pet_spot_elsahel.dump` (17M, `pg_restore -l` OK) |
| Filestore | `…/filestore/` (346M) |
| Config | `…/pet_spot_elsahel.conf` |
| Git/addons note | `…/git_and_addons.txt` |
| Service cmdline | `…/prod_master_cmdline.txt` |
| n8n workflow | ID `gKMYWKVT5FtUAFwB` — backup `/home/sabry/infra/n8n/backups/workflows/chatwoot-ai-analysis-hub-ingest-20260723T045647Z.json` (**unchanged**) |

---

## C. Module Migration

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
| `social_media_connector` | `19.0.1.0.0` | `-u` | `19.0.1.0.1` | **PASS** |

Pending `to install` / `to upgrade` / `to remove` after each step: **none**.  
Installed module count: **341** (was 340; only new module = hub).

Service was stopped via `systemctl --user stop pet_spot_elsahel` during `-i`/`-u`, then restarted.

Logs: `logs/p93_*.log` … `logs/p96_*.log`

---

## D. Data Integrity

| Table | Before | After | Delta |
|-------|--------|-------|-------|
| `wa_campaign` | 14 | 14 | **0** |
| `wa_campaign_line` | 2257 | 2257 | **0** |
| `evo_wa_template` | 15 | 15 | **0** |
| `integration_bridge_log` | 127 | 127 | **0** |
| `integration_outbound_queue` | 127 | 127 | **0** |
| `integration_bridge_token` | 5 | 5 | **0** |
| `petspot_wa_intake` | 12 | 12 | **0** |
| `wa_message_log` | 2 | 2 | **0** |
| `whatsapp_message` | 0 | 1 | +1 synthetic cutover smoke only |

`ALL_ZERO_DELTA` for required business tables.

---

## E. Registry / XML / View Results

| Check | Result |
|-------|--------|
| Critical migration-scope errors | **0** |
| ParseError | **0** |
| External ID not found | **0** |
| Missing fields / invalid inheritance | **0** |
| Hub / campaign / intake / outbound `get_views` | **OK** |
| Registry after restart | Modules loaded; HTTP 200 |

---

## F. Compatibility Routes

| Route | Status |
|-------|--------|
| `GET /whatsapp_hub/health` | **200** `{"ok": true}` |
| `POST /whatsapp_hub/ingest` | **200** (synthetic only) |
| `GET /bridge/inbound/health` | **200** |
| `OPTIONS /bridge/inbound` | **204** |
| `OPTIONS /bridge/evolution/webhook` | **204** |
| `GET /petspot/wa/intake/health` | **200** |
| `OPTIONS /petspot/wa/intake` | **204** |

n8n / Evolution webhook targets: **unchanged**.

---

## G. Hub ACL

| Item | Value |
|------|-------|
| Group | `whatsapp_hub.group_whatsapp_manager` (id 149) |
| User granted | `admin` (uid **2**) only |
| Broad grant | **No** |
| Post-grant worker restart | **Yes** |

---

## H. UI Smoke

| Screen / check | Result |
|----------------|--------|
| Login | 200 + screenshot `screenshots/01_login.png` |
| Hub health page | screenshot `screenshots/02_hub_health.png` |
| JSON-RPC login | OK |
| WhatsApp Hub menu | present |
| Hub message list/form views | OK |
| Campaign views | OK |
| Intake views | OK |
| Outbound views | OK |
| `campaign_phone_marassi` settings alias | OK |

---

## I. Optional Idempotency Test

```text
Production synthetic
```

| Call | Result |
|------|--------|
| 1st ingest `chatwoot_message_id=881001` | `duplicate=false`, `message_id=1` |
| 2nd identical ingest | `duplicate=true`, same id |
| DB count for that id | **1** |

Isolated to Hub ingest only; not routed to customers / OP / clinic automation / Dev Hub.

---

## J. Production Service Health

| Check | Result |
|-------|--------|
| `systemctl --user is-active pet_spot_elsahel` | **active** |
| HTTP `:8027` | **200** |
| Hub health | **ok** |
| DB accessible | **yes** |
| Workers + gevent | running under user systemd |
| Addons path | still canonical-only (no overlays) |

---

## K. Issues Found

| Severity | Issue | Action |
|----------|-------|--------|
| Low / non-blocker | Cosmetic bridge health version string | Noted; no code change in this cutover |
| Info | Synthetic hub row created for smoke | Documented; expected |
| Info | Pre-existing Odoo warnings | No action |

No critical issues. No schema surgery.

---

## L. Rollback Status

```text
ROLLBACK NOT REQUIRED
```

Backup retained at `p9_cutover_20260723T062315Z` if ever needed.

---

## Explicitly Out of Scope (not done)

- `-u all`
- Uninstalls / empty-bridge conversion
- Overlay/worktree deletion
- Addons path changes
- Production n8n → Hub routing enablement
- Evolution webhook retargeting
- Dev Hub modular install on Production

---

## Success Condition

> Production installs `whatsapp_hub` and upgrades the exact targeted legacy/consumer modules using the rehearsed code fingerprint and order, while preserving business data, keeping compatibility routes operational, starting a clean registry, and leaving n8n/Evolution Production routing unchanged.

**Status: MET.**
