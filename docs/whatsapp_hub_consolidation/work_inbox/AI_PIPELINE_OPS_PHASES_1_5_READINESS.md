# Operational Phases 1–5 — Production Readiness

**Date:** 2026-07-26
**Test DB:** `pet_spot_elsahel_test`
**Prod DB (read-only):** `pet_spot_elsahel`
**Migration clone:** `pet_spot_elsahel_mig_rehearsal` (isolated, port 8035, dropped after rehearsal)
**Production upgrade:** **NOT performed**

---

## Decision

```text
NOT READY
```

Every operational blocker is now resolved or planned **except one hard gate**: the **real 24-hour Test observation** clock only started at **t0 = 2026-07-26T05:18:28Z** and cannot complete inside this task. A secondary item — executing the port-8027 duplicate-unit reconciliation and taking the final fresh Prod backup — is intentionally deferred (requires the explicit authorization the task withholds).

Newly proven in this task:
- Prod is **already supervised** (user systemd unit), not a manual process — earlier report corrected.
- The 44 `delayed` health warnings were **100% false positives**; semantics fixed + tested.
- Migration dry-run on a **fresh Prod clone passed**, and **caught a real upgrade-set defect** (`devhub_work` must be upgraded too).
- Safe default AI flags, rollback, and no-external-writes all verified.

---

## Phase 1 — Production process supervision audit

### Live process on port 8027 (read-only)

| Attribute | Value |
|-----------|-------|
| Listening PID | **1085909** (+ workers 1086223/1086224, gevent 1086226, cron 1086230) |
| Parent PID | **6259 = `/usr/lib/systemd/systemd --user`** (user manager for uid 1000) |
| User | `sabry` |
| Start time | 2026-07-26 07:21:03 EEST (today) |
| Command | `venv19/bin/python3 odoo-bin -c config/projects/pet_spot_elsahel.conf -d pet_spot_elsahel` |
| Working dir | `/home/sabry/odoo_base/base_odoo_19/odoo19/odoo19` |
| Python | `venv19/bin/python3` (3.12) |
| Config | `config/projects/pet_spot_elsahel.conf` |
| dbfilter | `^pet_spot_elsahel$` |
| addons_path | community + enterprise + `projects/pet_spot_elsahel` |
| data_dir | `projects/pet_spot_elsahel/.filestore` |
| workers | 2 (+ gevent) |
| **cgroup** | `user.slice/user-1000.slice/user@1000.service/app.slice/`**`pet_spot_elsahel.service`** |
| Supervisor | **user-level systemd unit** (NOT manual, NOT the failed system unit) |

**Correction to prior report:** the process is **not** an unmanaged manual background process. It is supervised by a **user** systemd unit with `Restart=always`, `RestartSec=5`, `ExecStartPre` waiting for PostgreSQL, and **linger enabled** (`/var/lib/systemd/linger/sabry`), so it survives logout/reboot. The whole fleet (Test 8028, Resume 8029, Tours 8031, cloudflared, proxies) runs the same way.

### The two units

| Item | Failed **system** unit | Live **user** unit | Expected canonical | Risk |
|------|------------------------|--------------------|--------------------|------|
| Fragment path | `/etc/systemd/system/pet_spot_elsahel.service` | `~/.config/systemd/user/pet_spot_elsahel.service` | **user unit** | Duplicate name → boot race |
| Scope | system (`multi-user.target`) | user (`default.target`, linger) | user | Two managers, one port |
| ActiveState | **failed** (`EADDRINUSE`, last try 2026-07-23) | **active/running** | active | System unit noise |
| MainPID | 0 (dead; was 45160) | **1085909** | user PID | — |
| ExecStart | same binary/conf/db | same + `ExecStartPre` pg wait | user (has pg gate) | System lacks pg wait |
| Restart | `on-failure` (hit start-limit, gave up) | `always`, `RestartSec=5` | `always` | — |
| Enabled | `enabled` | `enabled` | only one | Both try port 8027 on boot |
| Health now | n/a | `/web/login`=200, `/whatsapp_hub/health` ok, crons running | healthy | — |

**Root cause of EADDRINUSE:** both units are enabled; on boot the user unit binds 8027 first, so the system unit's `socket.bind` fails. It is a **stale duplicate**, not a real outage — Production has been healthy on the user unit the whole time.

### Reconciliation plan → exactly one supervised process (needs sudo authorization)

Canonical target = the **user** unit (consistent with the rest of the fleet, has pg-wait + `Restart=always` + linger).

```bash
# 1. Confirm user unit is the live owner (already verified)
systemctl --user status pet_spot_elsahel.service --no-pager
loginctl show-user sabry -p Linger              # Linger=yes

# 2. Neutralize the stale SYSTEM unit (root). It is already inactive/failed,
#    so this does NOT touch the running user process.
sudo systemctl disable --now pet_spot_elsahel.service      # system scope
sudo systemctl reset-failed pet_spot_elsahel.service
sudo systemctl mask pet_spot_elsahel.service               # prevent future boot-race
#    (or, instead of mask, remove the file:)
# sudo rm /etc/systemd/system/pet_spot_elsahel.service && sudo systemctl daemon-reload

# 3. Verify single owner remains
ss -ltnp | rg ':8027'                                      # only user PID
systemctl is-enabled pet_spot_elsahel.service || true      # masked/absent
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8027/web/login   # 200
```

**Rollback (if masking the system unit ever needed to be undone):**
```bash
sudo systemctl unmask pet_spot_elsahel.service
# Do NOT re-enable it; keep the user unit canonical. If ever consolidating to
# system scope instead: stop user unit first, then enable+start system unit:
#   systemctl --user disable --now pet_spot_elsahel.service
#   sudo systemctl enable --now pet_spot_elsahel.service
```

No disruptive command was executed during the audit.

---

## Phase 2 — 24-hour Test observation + delayed-health fix

### Observation window
- Dev Needed (#9) settings confirmed and **restored** to required values (were found flipped `ai_triage_enabled=false`; reset to true):
  `ai_triage_enabled=true, auto_analysis_enabled=true, analysis_review_only=true, analysis_debounce_minutes=3, openproject_create_allowed=false, analysis_prompt_version=wa_project_aware_v3.0`.
- **t0 = 2026-07-26T05:18:28Z** (`obs24_t0.txt`).
- Hourly sampler: `obs24_sampler.sh` → `obs24_samples.ndjson` (schedule via cron/systemd timer; aggregate at t0+24h).
- **Status: IN PROGRESS — the wall-clock day has not elapsed.** Not substituted with a synthetic run. First sample recorded (0 new msgs, 0 pending, 0 gaps, 7 dead-letter from prior UAT cleanup, 4 needs_review).

### 44 `delayed` health warnings — classification (before)

| Class | Count | Evidence |
|-------|------:|----------|
| Inactive conversation, no provider freshness (`last_provider_event_at IS NULL`) | 12 | Has messages but quiet; not lagging |
| Stale/legacy row, no matching conversation messages | 32 | Orphan / UAT smoke groups / NULL group_jid |
| Missing all freshness data | 0 | — |
| **Genuine provider-ahead lag** | **0** | none |

Root cause: `recompute_health_status` marked **any** row with `last_successful_ingestion_at` older than the 30-min threshold as `delayed`, even with **no provider signal** of pending traffic. That conflates *inactive* with *delayed*.

### Fix (`whatsapp_hub` 19.0.1.15.0 → **19.0.1.16.0**)
- Added statuses **`idle`** and **`unknown`** to `health_status`.
- `delayed` now requires **positive provider-ahead evidence** (`last_provider_event_at` newer than `last_successful_ingestion_at`); pure age → `idle`; no freshness data → `unknown`.
- `_should_flag_gap_or_delay` no longer treats inactivity as actionable (watchdog/auto-recover won't fire on quiet chats).
- **4 new tests** added; full `TestWhatsappIngestionHealth` = **7 tests, 0 failed** on Test and on the Prod clone.

### Before/after (Test)

| | delayed | healthy | idle | unknown |
|--|---:|---:|---:|---:|
| Before | 44 | 6 | 0 | 0 |
| After (recompute) | **0** | 5 | **45** | 0 |

All 44 false `delayed` reclassified to `idle`; zero genuine ingestion problems; warnings **explained and fixed, not cleared**.

---

## Phase 3 — Production OpenProject scope decision

### Read-only findings
- `devhub_whatsapp` depends only on `devhub_work`, `devhub_analysis`, `whatsapp_hub` — **no OpenProject dependency**. The AI review-only pipeline works fully without OP.
- `devhub_openproject` → depends on `devhub_work` + `openproject_sync`; `openproject_sync` → `project`, `mail`, `web`.
- Prod has **no** `openproject_backend`/`openproject_project_map` tables, **no** `op_*` columns on `dev_work_item`, **no** OP fields on `dev_whatsapp_analysis`. Both OP modules **uninstalled**.
- No Prod OpenProject endpoint/credentials/mappings configured. (Test uses backend "OpenProject Main" for its own UAT lane only.)

### Option A — WhatsApp AI review-only, no OpenProject
Upgrade `whatsapp_hub` + `devhub_whatsapp` (+ required `devhub_work`, `devhub_analysis` — see Phase 5). AI flags off, no auto-create, no OP linkage. Minimal surface; WI/task creation still possible manually later without OP.

### Option B — Full OpenProject linkage
Also install `openproject_sync` + `devhub_openproject`. Adds: OP backend config + API credentials, project maps, push-gating flags, pull/push crons, `op_*` schema on tasks/WI, cross-project parent logic, and reverse-sync risk. Requires its own mapping UAT, credential vault, and rollback of OP writes. Larger blast radius.

### Recommendation: **Option A** for the initial Production rollout.
Prod has no OP integration configured and `devhub_whatsapp` doesn't need it. Defer Option B until there is a concrete requirement to sync WhatsApp-originated work to OpenProject in Production, then run a separate OP-specific UAT.

---

## Phase 4 — Backup procedure rehearsal (on Test / safe path)

Rehearsed at `backups/rehearsal_20260726T051943Z/` (final Prod backup **not** taken):

| Step | Command | Result |
|------|---------|--------|
| DB dump | `pg_dump -Fc -h localhost -U odoo pet_spot_elsahel_test -f db.dump` | 12.5s, 92 MB |
| Integrity | `pg_restore -l db.dump` | 31,401 TOC entries; **1,389 TABLE DATA** |
| Checksum | `sha256sum db.dump` | `50230e3a…07fccd` |
| Module list | `SELECT name,latest_version … state='installed'` | 360 modules captured |
| Addon git | `git rev-parse HEAD` | `b2645d12…`, 232 dirty (uncommitted local edits) |
| Config | copy + mask `db_password` | captured |
| Disk | `df -h /home` | 242 G free (ample) |
| Restore | proven in Phase 5 (full restore + rollback) | OK |

### Final Production pre-upgrade backup runbook (execute only when authorized)
```bash
set -euo pipefail
TS=$(date -u +%Y%m%dT%H%M%SZ)
PKG=/home/sabry/odoo_base/base_odoo_19/backups/pet_spot_elsahel_preupgrade_$TS
mkdir -p "$PKG"
export PGPASSWORD='<odoo db password>'          # from conf; never echo

# 1. DB dump (custom format)
pg_dump -Fc -h localhost -U odoo pet_spot_elsahel -f "$PKG/db.dump"
# 2. Filestore archive
tar -C /home/sabry/odoo_base/base_odoo_19/projects/pet_spot_elsahel/.filestore/filestore \
    -czf "$PKG/filestore.tgz" pet_spot_elsahel
# 3. Odoo config (mask secrets in the copy)
sed 's/^db_password.*/db_password = ***MASKED***/' \
    config/projects/pet_spot_elsahel.conf > "$PKG/pet_spot_elsahel.conf.masked"
# 4. Env / unit files (secrets protected)
cp ~/.config/systemd/user/pet_spot_elsahel.service "$PKG/user_unit.service"
# 5. Addon git commit hashes
( cd projects/pet_spot_elsahel && git rev-parse HEAD; git status --porcelain | wc -l ) > "$PKG/addon_git.txt"
# 6. Installed module versions
psql -h localhost -U odoo -d pet_spot_elsahel -tAF'=' \
  -c "SELECT name,latest_version FROM ir_module_module WHERE state='installed' ORDER BY name" > "$PKG/installed_modules.txt"
# 7. Running process + webhook summary
ss -ltnp | rg ':8027' > "$PKG/process.txt" || true
psql -h localhost -U odoo -d pet_spot_elsahel -tAc \
  "SELECT key,CASE WHEN key ILIKE '%key%' OR key ILIKE '%token%' THEN 'present' ELSE value END \
   FROM ir_config_parameter WHERE key ILIKE 'integration_bridge.evolution%'" > "$PKG/webhook_summary.txt"
# 8. Checksums
( cd "$PKG" && sha256sum db.dump filestore.tgz > SHA256SUMS )
# 9. Restore instructions
cat > "$PKG/RESTORE.md" <<'EOF'
Restore: createdb + pg_restore --no-owner --role=odoo -d <db> db.dump;
untar filestore.tgz into data_dir/filestore/<db>; verify sha256sum -c SHA256SUMS.
EOF
```

---

## Phase 5 — Production-clone migration dry-run

Fresh **read-only** `pg_dump` of live Prod → isolated clone (no live traffic). Prod untouched throughout (verified 200 + versions unchanged after).

| Requirement | Result |
|-------------|--------|
| Fresh authorized Prod dump | `pg_dump` 4.3s, 18 MB, sha256 `b9fe7960…` |
| Restore into isolated DB | `pet_spot_elsahel_mig_rehearsal` (own data_dir, port 8035, `list_db=False`, `max_cron_threads=0`) |
| Filestore restored | 99 MB copied into isolated dir |
| Outbound neutralized | evolution_url → `127.0.0.1:9/disabled`, keys/n8n webhook blanked, all 82 crons disabled |
| **Upgrade set defect caught** | `-u whatsapp_hub` alone **FAILED**: `devhub_whatsapp` view inherits `devhub_work.view_dev_project_work_items_form`, absent on Prod (disk `devhub_work`=**9.1.4**, Prod DB=**9.1.1**) |
| Correct upgrade set | `-u whatsapp_hub,devhub_work,devhub_analysis,devhub_whatsapp` → **exit 0**, no fatal errors |
| Upgrade duration | **33.9 s** wall (registry 32.2 s) |
| Schema: health table | `whatsapp_ingestion_health` created ✓ |
| Schema: inbox cols | `inbox_state`, `previous_inbox_state` present ✓ |
| Schema: AI flag cols | all 6 created ✓ |
| **Safe default AI flags** | 12 sources: **triage=0, auto=0, review_only=12, op_create=0** ✓ |
| Existing records readable | 70 messages intact (2026-07-23 range), inbox all `untriaged` ✓ |
| Automated + smoke tests | `TestWhatsappIngestionHealth` **7 tests, 0 failed** on clone ✓ |
| No external writes | evolution stub + crons off; Prod verified unchanged ✓ |
| Rollback rehearsal | drop + `pg_restore` pre-upgrade dump → reverts to 1.14.0 / 9.1.9 / 9.1.1 ✓ |

Evidence: `backups/migclone_20260726T052046Z/` (`prod.dump` + `upgrade_cluster.log` + `smoke.log` + `rollback.err` + checksums). Clone DB and isolated filestore dropped after rehearsal.

**Key correction to the rollout:** the Production upgrade command is
`-u whatsapp_hub,devhub_work,devhub_analysis,devhub_whatsapp` (not just `whatsapp_hub,devhub_whatsapp`).

---

## Final readiness checklist

| Criterion | Status |
|-----------|--------|
| Canonical process supervision plan validated | **Yes** (user unit canonical; system unit stale) |
| No unresolved port 8027 ownership ambiguity | **Diagnosed**; single authorized `disable/mask` step pending |
| Real 24-hour Test observation passed | **No** — clock started t0 05:18Z, not elapsed |
| Delayed health warnings explained or fixed | **Yes** (fixed + tested; 44→0 false positives) |
| OpenProject rollout option selected | **Yes** (Option A) |
| Backup runbook verified | **Yes** (rehearsed; restore proven) |
| Fresh Production-clone migration rehearsal passed | **Yes** (caught + fixed upgrade-set defect) |
| Safe default AI flags verified | **Yes** (triage/auto off, review-only on, op-create off) |
| Rollback rehearsal passed | **Yes** |
| No external integration writes during rehearsal | **Yes** |

**Blocking:** real 24-hour observation incomplete (dominant), plus the authorized supervision-reconciliation + final backup + upgrade are intentionally not executed in this task.

---

## Final controlled Production rollout plan (execute only under separate authorization)

**Pre-req:** complete the 24h observation (aggregate `obs24_samples.ndjson`; require 0 stuck debounce, 0 dead-letter growth, 0 accidental WI/task, 0 genuine `delayed`/`gap`/`failed`).

1. **Supervision reconciliation** — `sudo systemctl disable --now && reset-failed && mask` the **system** `pet_spot_elsahel.service`; confirm only the user PID owns 8027; `/web/login`=200.
2. **Backup** — run the Phase 4 final runbook; verify `sha256sum -c SHA256SUMS`.
3. **Code** — confirm addon tree at intended commit (`whatsapp_hub` 1.16.0, `devhub_work` 9.1.4, `devhub_analysis` 9.1.1, `devhub_whatsapp` 9.5.0); keep P0 mapping data (forces AI triage off).
4. **Upgrade (maintenance window)** — stop the user unit, then:
   `odoo-bin -c pet_spot_elsahel.conf -d pet_spot_elsahel -u whatsapp_hub,devhub_work,devhub_analysis,devhub_whatsapp --stop-after-init --no-http` (expect ~35–60 s).
5. **Service restart order** — `systemctl --user start pet_spot_elsahel.service`; wait for pg (ExecStartPre); confirm single PID on 8027.
6. **Smoke tests** — `/whatsapp_hub/health` + `/bridge/inbound/health` = 200; Evolution `http://127.0.0.1:8080/` healthy; verify `whatsapp.instance` URL has no `:9` stub; verify **AI flags off** on all sources; confirm 0 new WI/task from ingress alone.
7. **Review-only config** — `ai_triage_enabled=false, auto_analysis_enabled=false, analysis_review_only=true, openproject_create_allowed=false`.
8. **Monitoring window (≥24 h)** — ingestion health (expect `idle`/`healthy`, no false `delayed`), debounce jobs, analysis pending/dead-letter, WI/task/OP deltas = 0.
9. **Then, separately authorized:** enable AI triage for **one** source only, still review-only.

### Stop conditions / rollback triggers
- `/whatsapp_hub/health` or `/bridge/inbound/health` ≠ 200
- Message ingest failure or uniqueness violation
- Any unexpected WI/task/OP creation
- Analysis job storm, stuck debounce, or growing dead-letter
- Duplicate process on 8027 / service flapping

### Rollback procedure
```bash
systemctl --user stop pet_spot_elsahel.service
dropdb -h localhost -U odoo pet_spot_elsahel && createdb -h localhost -U odoo pet_spot_elsahel
pg_restore --no-owner --role=odoo -h localhost -U odoo -d pet_spot_elsahel "$PKG/db.dump"
tar -C .../.filestore/filestore -xzf "$PKG/filestore.tgz"      # if attachments changed
# redeploy previous addon commit if code changed, then:
systemctl --user start pet_spot_elsahel.service
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8027/web/login   # expect 200
```
**Do not enable Production automatic work creation in the initial rollout.**

---

## Artifacts
- `docs/.../work_inbox/AI_PIPELINE_OPS_PHASES_1_5_READINESS.md` (this report)
- `docs/.../work_inbox/obs24_sampler.sh`, `obs24_t0.txt`, `obs24_samples.ndjson`
- `whatsapp_hub` health fix: `models/whatsapp_ingestion_health.py` (19.0.1.16.0) + `tests/test_whatsapp_ingestion_health.py`
- `backups/rehearsal_20260726T051943Z/` (backup runbook rehearsal)
- `backups/migclone_20260726T052046Z/` (migration dry-run evidence + logs)
- Prior: `AI_PIPELINE_PHASES_A_D_READINESS.md`, `AI_PIPELINE_GATES_1_5_COMPLETION.md`
