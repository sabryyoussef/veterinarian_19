# Phases A–D — Operational Validation & Production Readiness

**Date:** 2026-07-26  
**DB Test:** `pet_spot_elsahel_test`  
**DB Prod (read-only):** `pet_spot_elsahel`  
**Production upgrade:** **NOT performed**  
**Evidence JSON:** `phase_abd_uat_result.json`

---

## Decision

```text
NOT READY
```

Controlled create/retry/rerun/replay/rollback **passed on Test**. Production Evolution base URL has **no `:9` stubs** and responds healthy. Still **NOT READY** because:

1. Wall-clock **≥1 operating day** observation was **not** completed (synthetic UAT substituted; real Dev Needed traffic after Gates 1–5 was only prior debounce pings).
2. Production modules are **behind Test** (`whatsapp_hub` 19.0.1.14.0 vs 19.0.1.15.0; `devhub_whatsapp` 19.0.9.1.9 vs 19.0.9.5.0).
3. Production AI triage schema/flags **not migrated yet** (no `ai_triage_enabled` columns on `dev_whatsapp_source`).
4. `openproject_sync` / `devhub_openproject` are **uninstalled** on Production (Test has them installed).
5. `pet_spot_elsahel.service` is **failed** (port 8027 bind conflict); Prod currently runs as a **manual** python process — restart/upgrade order must be reconciled first.
6. Fresh Production DB dump should be taken immediately before any upgrade (existing dumps are from 2026-07-24).

---

## Phase A — Test observation report

**Traffic kind:** `synthetic_uat` (clearly labeled). Real meaningful Dev Needed traffic during the post–Gate-5 window was insufficient for a calendar day.

**Dev Needed (#9) settings retained:**

| Setting | Value |
|---------|-------|
| `ai_triage_enabled` | true |
| `auto_analysis_enabled` | true |
| `analysis_review_only` | true |
| `analysis_debounce_minutes` | 3 |
| `openproject_create_allowed` | false |
| `analysis_prompt_version` | `wa_project_aware_v3.0` |

| Metric | Result | Expected | Status | Evidence |
|--------|-------:|---------:|--------|----------|
| Newly ingested messages (obs window) | 20 | ≥1 | PASS* | Test msgs since 04:56 UTC; 9 tagged `SYNTH-OBS-` |
| Conversations affected (synth) | 1 | ≥1 | PASS* | Dev Needed group |
| Debounce schedules created | ≥3 | ≥1 | PASS* | Runner `schedule_debounced_analysis` per ingest |
| Debounce resets | ≥1 | ≥0 | PASS* | `pending_analysis_after` moved on re-ingest |
| Analyses created (obs window) | 8 | tracked | INFO | Includes #390–#399 family; synth cron flush blocked by Dev Needed mapping gate |
| Source message count / analysis | #390:7; Phase B:2–3 | stable | PASS | `phase_abd_uat_result.json` |
| Duplicate fingerprints | 0 extras for #390 | 0 | PASS | `extra_analyses_same_fingerprint_390=0` |
| Analyses reused instead of recreated | #390 fingerprint reuse | reuse | PASS | Gate 5 + obs |
| Dify successes (native v3) | 1 (#390) | ≥1 | PASS | prior Gate 1 |
| Dify failures (unhandled) | 0 | 0 | PASS | obs window |
| Validation failures | 0 | 0 | PASS | obs window |
| Analyses `needs_review` | 4 | review-only OK | PASS | expected under review |
| Stuck pending analyses | 0 | 0 | PASS | |
| Pending jobs older than 15m | 0 | 0 | PASS | cleaned during UAT |
| Accidental Dev Hub WI (non-UAT) | 0 | 0 | PASS | |
| Accidental Odoo tasks (non-UAT) | 0 | 0 | PASS | |
| Accidental OpenProject creates (non-Testing UAT) | 0 | 0 | PASS | Testing WP #403/#404 only from Phase B |
| Ingestion health warnings | 44 `delayed` | prefer 0 | WARN | Test health rows; **0** `gap_detected` |
| Recovery operations | none | tracked | INFO | |
| Missing-message gaps | 0 | 0 | PASS | |
| Duplicate default analyses | 0 | 0 | PASS | |
| Stuck debounce jobs | 0 (`pending_analysis_after` cleared) | 0 | PASS | source #9 |

\*PASS against synthetic success criteria; **calendar 24h observation still outstanding**.

**Note:** Debounced flush on Dev Needed still logs mapping ambiguity (“confirm project”) — auto-analysis schedules, but flush does not create surprise analyses until mapping is confirmed. Review-only remains in force.

---

## Phase B — Controlled Test-only create UAT

**Lane:** Odoo project **11** (`OP: Testing`) → OP project **21**, map #9, `op_push_create=true`.  
**Disposable Dev project / source** created for UAT.  
**Not** Production data. **Not** unrestricted auto-create (`wa_orchestration_force` + manager only).

### Links stored

| Field | Value |
|-------|-------|
| analysis ID | **396** |
| item index | 0 |
| source message IDs | 9273, 9274 |
| conversation fingerprint | `75878eb0…c62ef7cb` |
| Dev Hub WI | **3411** |
| Odoo task | **3348** |
| OpenProject project | **21** |
| OpenProject WP | **404** |
| OpenProject parent | `op_project:21` |
| decision reason | `phase_b_controlled_manual_approve_force` |

### Test matrix

| Test | Result | Status |
|------|--------|--------|
| Review + manual approve (force) | WI 3411 + task 3348 + OP WP 404 | PASS |
| Blocked without force | UserError under review_only | PASS |
| Retry approve | blocked; same WI/task/WP; ΔWI=0 Δtask=0 | PASS |
| Analysis rerun | analysis **398**, decision `update_existing`, match WI 3411 | PASS |
| Provider replay | duplicate ingest; no new msgs/analysis/work | PASS |
| Follow-up message | analysis **399**, `update_existing`, same WI; no unrelated child | PASS |
| Rollback/archive | WI → `cancelled`; task `active=false`; OP WP **404 retained** (evidence); analyses kept | PASS |

**Before → after rollback counts:** WI total unchanged (62); active tasks 379→378; WI phase `cancelled`; task inactive.

**Orphans cleaned:** WI 3409/3410 cancelled; task 3347 archived (prior failed attempts / OP WP 403 retained as evidence).

---

## Phase C — Production read-only audit (`pet_spot_elsahel`)

No module upgrade, ICP write, service restart, AI enable, or work creation was performed.

| Check | Current value/state | Expected | Ready? | Risk/action |
|-------|---------------------|----------|--------|-------------|
| `whatsapp_hub` version | **19.0.1.14.0** installed | ≥19.0.1.15.0 (Test) | **No** | Upgrade after backup |
| `devhub_whatsapp` version | **19.0.9.1.9** installed | ≥19.0.9.5.0 (Test) | **No** | Upgrade after backup; brings AI flags/debounce/v3 |
| `openproject_sync` | **uninstalled** | installed if OP push/link required | **No** | Install only if Prod OP linkage is in scope |
| `devhub_openproject` | **uninstalled** | installed with OP identity on WI | **No** | Same |
| `integration_bridge_core` | 19.0.1.1.3 installed | installed | Yes | |
| `whatsapp.instance` | #1 active `sabry min` | active Evolution map | Yes | |
| Evolution base URL (instance) | `http://127.0.0.1:8080` | valid non-stub | Yes | |
| Instance API key field | **missing** | present or ICP fallback | Warn | ICP `integration_bridge.evolution_key` **present(48)** |
| `:9` URL stubs | **none** | none | Yes | |
| ICP `evolution_url` | `http://127.0.0.1:8080` | valid | Yes | |
| ICP `evolution_instance` | `sabry min` | matches instance | Yes | |
| ICP `evolution_key` | present (masked) | present | Yes | |
| Webhook routes (code) | `/bridge/evolution/webhook`, `/whatsapp_hub/ingest`, `/whatsapp_hub/health` | configured | Yes | Confirm Evolution webhook points at live Prod |
| Bridge health (HTTP) | `/bridge/inbound/health` → 200 | 200 | Yes | Against process on :8027 |
| Hub health (HTTP) | `/whatsapp_hub/health` → `{"ok":true}` | ok | Yes | |
| Evolution API health | HTTP 200, v2.3.7 | healthy | Yes | `curl http://127.0.0.1:8080/` |
| Cron state | outbound + discuss/campaign hub health active | active | Yes | No debounce/AI flush crons until upgrade |
| Queue state | no `queue_job` relation | N/A / hub outbound cron | Info | Hub uses its own outbound queue |
| Message uniqueness | unique on `dedupe_key`, `business_key`, Evolution `(provider,instance,provider_message_id)` | unique ready | Yes | |
| `inbox_state` / `previous_inbox_state` | columns present; all 70 msgs `untriaged` | present | Yes | |
| `whatsapp_ingestion_health` table | **absent** on Prod | present after hub 1.15 | **No** | Comes with hub upgrade |
| AI triage flags on sources | **columns absent** | false/false/true initially | **No** | Schema arrives with `devhub_whatsapp` upgrade |
| `ai_triage_enabled` (Prod) | n/a (not migrated) | **false** post-upgrade | **No** | Do not enable on upgrade day |
| `auto_analysis_enabled` | n/a | **false** | **No** | |
| `analysis_review_only` | n/a | **true** | **No** | |
| Backup readiness | dumps **2026-07-24** (`pet_spot_elsahel.dump` + filestore) | fresh pre-upgrade dump | **Partial** | Take new dump immediately before upgrade |
| systemd unit | `pet_spot_elsahel.service` **failed** since 2026-07-23 (EADDRINUSE :8027) | healthy unit | **No** | Manual python PID owns 8027; fix unit before formal restart |
| Live HTTP on 8027 | 200 (manual process) | serving | Yes* | *Not managed by failed unit |
| Bridge restart requirement | expected after module upgrade | yes | Info | Restart the **actual** Prod process / fix systemd first |
| Module upgrade order | documented below | documented | Yes | |

Secrets masked; no broad Prod message history fetched.

---

## Phase D — Readiness criteria checklist

| Criterion | Met? |
|-----------|------|
| Test observation period (≥1 day) | **No** (synthetic only) |
| No duplicate analyses | **Yes** (fingerprint) |
| No stuck debounce jobs | **Yes** |
| Controlled create UAT passed | **Yes** |
| Retry created no duplicate work | **Yes** |
| Analysis rerun found existing work | **Yes** (`update_existing`) |
| Provider replay created no duplicates | **Yes** |
| Rollback/archive path verified | **Yes** (WI cancel + task archive; OP WP retained) |
| Production Evolution configuration valid | **Yes** (URL/key ICP; no `:9`) |
| No `:9` URL stubs | **Yes** |
| Migrations verified (Prod) | **No** (Prod still on older modules) |
| Module upgrade order documented | **Yes** |
| Backup plan documented | **Yes** |
| Rollback plan documented | **Yes** |

---

## Proposed controlled Production rollout (do **not** execute in this task)

### 1. Backup
```bash
# Fresh Prod dump + filestore snapshot before any -u
pg_dump -Fc -h localhost -U odoo pet_spot_elsahel \
  -f /home/sabry/odoo_base/base_odoo_19/backups/pet_spot_elsahel_pre_ai_$(date -u +%Y%m%dT%H%M%SZ).dump
# filestore tarball of projects/pet_spot_elsahel/.filestore as used today
```

### 2. Code deployment
Deploy the same addon tree already validated on Test (`whatsapp_hub` 19.0.1.15.0, `devhub_whatsapp` 19.0.9.5.0). Do **not** enable AI flags via data XML without review (P0 mapping forces triage off on ambiguous sources — still verify after `-u`).

### 3. Module upgrade order
1. `whatsapp_hub`  
2. `devhub_whatsapp`  
3. Only if OP WI identity is required on Prod: `openproject_sync` then `devhub_openproject`  
4. Update apps list / `-u` with `--stop-after-init` on a maintenance window  
5. **Do not** install unrelated DevHub modules

### 4. Service restart order
1. Resolve systemd vs manual process on **8027** (stop manual PID **or** fix unit — do not double-bind).  
2. Restart Evolution only if webhook URL changes (usually not needed).  
3. Start/restart Prod Odoo (unit or supervised process).  
4. Confirm `/whatsapp_hub/health` and `/bridge/inbound/health` return 200.  
5. Confirm Evolution webhook still targets `/bridge/evolution/webhook`.

### 5. Smoke tests
- Hub health + bridge health  
- One known group: no broad backfill; optional single-conversation recovery dry-run on Test first  
- Confirm `whatsapp.instance` URL still `http://127.0.0.1:8080` / no `:9`  
- Confirm AI flags default **off**  
- Confirm no new WI/task/OP from ingress alone

### 6. Review-only configuration (initial)
```text
ai_triage_enabled = false
auto_analysis_enabled = false
analysis_review_only = true
openproject_create_allowed = false
```
After smoke tests, AI triage may be enabled for **one** selected source only, still review-only, under a **separate explicit authorization**.

### 7. Monitoring window
≥24h after deploy: ingestion health, debounce jobs, analysis pending/dead_letter, WI/task/OP create deltas = 0 while auto-create remains off.

### 8. Rollback triggers
- Hub/bridge health non-200  
- Message ingest failures or uniqueness violations  
- Unexpected WI/task/OP creates  
- Dify/analysis job storm or stuck debounce backlog  
- Port/service instability

### 9. Rollback procedures
```bash
# Stop Prod Odoo cleanly (the process that actually owns 8027)
# Restore DB from pre-upgrade dump
pg_restore --clean --if-exists -h localhost -U odoo -d pet_spot_elsahel /path/to/pre_ai.dump
# Restore filestore snapshot if attachments changed
# Redeploy previous addon versions; start Odoo; re-check health endpoints
# Re-point Evolution webhook if changed during failed cutover
```

**Do not enable Production automatic work creation in the initial rollout.**

---

## Safest next actions

1. Keep Test Dev Needed on current review-only auto-analysis settings and **complete a real 24h observation** (or scheduled synthetic day with the same metrics table).  
2. Fix Prod process supervision (`pet_spot_elsahel.service` vs manual :8027).  
3. Take a **fresh Prod backup**.  
4. Only then authorize a controlled Production upgrade under the plan above — still with AI create disabled.

**Artifacts**
- `docs/.../work_inbox/phase_abd_uat_result.json`  
- `docs/.../work_inbox/phase_abd_uat_runner.py`  
- `docs/.../work_inbox/phase_b_continue_runner.py`  
- Prior: `AI_PIPELINE_GATES_1_5_COMPLETION.md`, Test dump `pet_spot_elsahel_test_pre_ai_pipeline_20260726T043521Z.dump`
