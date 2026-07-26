# WhatsApp AI Triage + Live Ingestion Reliability — Delivery Report

**Date:** 2026-07-26  
**Test DB:** `pet_spot_elsahel_test`  
**Modules:** `whatsapp_hub` `19.0.1.15.0`, `devhub_whatsapp` `19.0.9.4.0`  
**Chat UX baseline:** preserved (`19.0.1.14.0` features untouched)  
**Baseline analysis preserved:** `#383` (unchanged)  
**Retest analysis:** `#387`  
**Backup:** `base_odoo_19/backups/pet_spot_elsahel_test_pre_ai_pipeline_20260726T043521Z.dump`  
**Phase 0 audit:** `docs/.../work_inbox/AI_PIPELINE_PHASE0_AUDIT.md`  
**Production upgrade:** **NOT done** (see remaining gaps)

---

## 1. Root cause

### Why live Hub ingestion stopped / lagged around Jul 25 ~09:19

Dev Needed Hub data was **never continuously live-streamed**. It arrived only via **bulk Evolution `findMessages` backfills**:

| create_date cluster (UTC) | count | message_timestamp coverage |
|---------------------------|------:|----------------------------|
| 2026-07-23 21:36 | 3428 | Mar 30 → Jul 23 21:26 |
| 2026-07-25 09:34 | 42 | → **2026-07-25 09:19:15** |
| 2026-07-26 03:58 | 7 (Kafaat manual) | Jul 25 14:47 → Jul 26 03:51 |

All 3477 Dev Needed Hub rows are `provider=evolution` with **Chatwoot IDs = 0**.

### Evidence

1. **Bridge kept working:** `chatwoot_evolution_bridge` logs show continuous `messages.upsert` + `chatwoot_ingest_ok` for `120363422104853335@g.us` through the morning of Jul 25.
2. **Odoo native Evolution webhook does not ingest Hub:** `WEBHOOK_GLOBAL_URL` → `:8027/bridge/evolution/webhook` only ran `mark_replied` (fixed in this delivery to fan-out to Hub).
3. **n8n Hub HTTP failing:** repeated Cloudflare **502** to `test.drpaws.ai` (~03:21 UTC Jul 25) while Test Odoo origin was down.
4. **Manual Kafaat pull:** messages `9181–9187` created together at `2026-07-26 03:58` via `test_kafaat_rpc_analysis.py`.

### Why monitoring did not detect it

No inbound lag/gap model existed. Only `last_hub_message_at` (updated by backfill completion). No comparison to provider/Chatwoot freshness, no watchdog cron, no `gap_detected` status.

---

## 2. Implementation plan (executed)

| Phase | Dependency | Status |
|------:|------------|--------|
| 0 Audit + backup + preserve #383 | — | Done |
| 1 Ingestion health + Evolution recovery + webhook fan-out | Hub | Done on Test |
| 2 Debounced auto-analysis (gated) | Source flags | Done (off by default) |
| 3 Enriched Dify payload | Chat/media fields | Done |
| 4 Deterministic technical extract | Messages | Done |
| 5 Schema v3 multi-item | Utils | Done |
| 6 Validation / empty-AC rejection | Apply + approve | Done |
| 7 Work orchestration / dedupe | Dev Hub / OP search | Done (review mode) |
| 8 OP/Odoo/Dev Hub linkage | Existing integrations | Recommend/search; no Prod writes |
| 9 Eval harness + scores | Analyses | Done |
| 10 Kafaat retest | All above | Done on Test |
| Prod upgrade | All gates | **Blocked** (see §8) |

---

## 3. Changes made (by file)

### `whatsapp_hub` 19.0.1.15.0
| Path | Purpose |
|------|---------|
| `models/whatsapp_ingestion_health.py` | Health statuses, watchdog, recover action |
| `models/whatsapp_evolution_recovery.py` | `findMessages` → `service_ingest_normalized` |
| `models/whatsapp_message.py` | Health update on ingest |
| `data/ir_cron_ingestion_health.xml` | 5-minute watchdog |
| `views/whatsapp_ingestion_health_views.xml` | UI + Recover button |
| `tests/test_whatsapp_ingestion_health.py` | Idempotency / gap / recovery |
| `__manifest__.py`, ACL, menus | Version + registration |

### `integration_bridge_core`
| Path | Purpose |
|------|---------|
| `controllers/bridge_unified.py` | `messages.upsert` → Hub ingest fan-out (non-fatal) |

### `devhub_whatsapp` 19.0.9.4.0
| Path | Purpose |
|------|---------|
| `models/dev_whatsapp_technical_extract.py` | RPC/paths/modules/tracebacks |
| `models/dev_whatsapp_work_orchestration.py` | Dedup / OP / task search before create |
| `models/dev_whatsapp_analysis_eval.py` | Weighted before/after scoring |
| `models/dev_whatsapp_analysis_utils.py` | Schema v3 + empty-AC rejection |
| `models/dev_whatsapp_analysis.py` | Enriched payload, evidence merge, multi-issue gate |
| `models/dev_whatsapp_source.py` | Debounce + auto_analysis flags |
| `models/dev_whatsapp_inbox.py` | Schedule debounce after new ingest |
| `data/ir_cron_analysis_debounce.xml` | Flush pending analyses |
| New tests (4 modules) | Extract / v3 / debounce / orchestration |

Chat OWL thread files were **not** modified.

---

## 4. Database / configuration changes (Test)

- New models: `whatsapp.ingestion.health`, `dev.whatsapp.analysis.eval` (+ abstract helpers)
- New analysis fields: `dify_request_json`, `technical_evidence_json`, `analysis_items_json`, `validation_*`, `op_recommended_parent_id`, orchestration JSON, etc.
- New source fields: `auto_analysis_enabled`, debounce minutes, `analysis_review_only`, `openproject_create_allowed`, `pending_analysis_after`
- Crons: ingestion health watchdog; analysis debounce flush
- ICP: `whatsapp_hub.auto_recover_gaps` (default false)
- Test Evolution instance fixed to `http://127.0.0.1:8080` / `sabry min` (previous default URL `http://127.0.0.1:9` was broken)
- `inbox_state` / `previous_inbox_state` already defined in `devhub_whatsapp` inherit (code path exists; Prod manual SQL was upgrade-order, not missing field defs)

---

## 5. Test results

```text
odoo-bin -u whatsapp_hub,devhub_whatsapp --test-enable \
  --test-tags=/whatsapp_hub:TestWhatsappChatThread,/whatsapp_hub:TestWhatsappIngestionHealth,\
/devhub_whatsapp:TestWhatsappTechnicalExtract,/devhub_whatsapp:TestWhatsappAnalysisV3Validation
→ 0 failed, 0 error(s) of 14 tests
```

Earlier focused suite (18 tests including debounce + orchestration) also green.

### UAT / Kafaat evidence
- Replay of evo IDs for msgs `9181–9187` → **all duplicate**, no new IDs
- Evolution recovery on conv 417: **created=26, existing=24, errors=0**; seven Kafaat evo IDs still **unique (count=1 each)**
- Technical extract finds `index.html` paths + `html4css1.css` + `RPC_ERROR` + `edafaa_student_profile` / `batch_intake`
- Empty acceptance criteria → **ValidationError** (v3)
- Live Dify raw re-applied with server hardening → `contains_multiple_tasks=true`, `validation_state=needs_review`, `safe_to_create_work=false`
- Artifact: `docs/.../work_inbox/kafaat_retest_20260726.json`

---

## 6. Before versus after

Weights: project 15 · multitask 20 · classification 10 · paths 20 · acceptance 15 · questions 10 · OP link 10.

| Area | Before #383 | After #387 (live Dify + server harden) | Cursor reference | Status | Evidence |
|------|-------------|----------------------------------------|------------------|--------|----------|
| Live ingestion | Lagging/stopped (backfill-only) | Recovery + health + webhook fan-out | Reliable | **Fixed** (Test) | Recovery 26/24/0; health model |
| Automatic analysis | Disabled (`ai_triage_enabled=false`) | Debounce implemented; still gated off | Controlled auto | **Partial** | Flags + cron; Dev Needed still off |
| Conversation bundle | Partial (7 manual) | Same 7 + fingerprint reuse | Complete | **Fixed** | Re-enqueue returns #387 |
| Project | Kafaat correct | Kafaat correct | Kafaat | **Fixed** | project 11 |
| Multiple tasks | False | **True** (server-side) | True where supported | **Fixed** | multi=true on #387 |
| RPC parsing | Weak | RPC_ERROR + FileNotFoundError + tracebacks | Exact | **Fixed** | technical_evidence_json |
| File paths | Missing | `…/index.html`, `html4css1.css` merged | Both paths | **Fixed** | extract + detail.affected_paths |
| Acceptance criteria | Empty | Present (Dify AC) + empty-AC gate | Complete | **Partial** | AC present; still single-item LLM body |
| Questions | Empty | Targeted multi-issue questions injected | Targeted | **Fixed** | missing_information_json |
| Arabic/context | Partial | Preserved in payload | Preserved | **Fixed** | msgs in dify payload |
| Media metadata | Partial | media_kind + availability fields | Structured | **Fixed** | `_job_payload` |
| Duplicate safety | Unclear | Idempotent ingest + fingerprint | Idempotent | **Fixed** | 7/7 duplicate replay |
| Dev Hub link | Present path | Orchestration search; review mode | Correct | **Partial** | no auto WI in eval |
| Odoo task link | Missing/unclear | Candidates searched | Correct decision | **Partial** | review mode |
| OpenProject link | Missing | `op_recommended_parent_id=87` | Parent #87 / OP #10 | **Partial** | recommend only; no create |
| **Overall score** | **20 / 100** | **90 / 100** | Target ≥85 | **Met on Test** | Eval records |

### Score detail
| | Baseline #383 | After #387 |
|--|--------------:|-----------:|
| Project | 15 | 15 |
| Multitask | 0 | 20 |
| Classification | 5 | 10 |
| Paths | 0 | 10 |
| Acceptance | 0 | 15 |
| Questions | 0 | 10 |
| OP link | 0 | 10 |
| **Total** | **20** | **90** |

Paths are 10/20 because Cursor expects bare `index.html` while extract stores full absolute paths (overlap on `html4css1.css` exact + partial index paths).

---

## 7. Final Kafaat normalized result (#387)

| Field | Value |
|-------|-------|
| Analysis ID | **387** |
| Baseline preserved | **383** unchanged |
| Workflow / prompt | `wa_project_aware_v2.3` (Dify live) + server harden |
| Source message IDs | `9181–9187` |
| Project | Kafaat `#11` |
| `contains_multiple_tasks` | **true** (server-side; LLM had false) |
| Title (LLM) | Review the Batch Intake screen… |
| Technical evidence | RPC_ERROR, FileNotFoundError, tracebacks, `edafaa_student_profile` / `batch_intake` / `index.html` / `html4css1.css` |
| Acceptance criteria | Non-empty (Dify) |
| Questions | Multi-issue confirmation questions |
| Validation state | **needs_review** |
| `safe_to_create_work` | **false** |
| OpenProject | recommended parent **87** (no create) |
| Human review | required |

---

## 8. Remaining gaps (explicit)

1. **Dify prompt/workflow still emits shallow single-item v2** — server now corrects multi-task + blocks unsafe auto-create; native v3 `items[]` not yet produced by LLM.
2. **Dev Needed `ai_triage_enabled` still false** — intentional until review-mode UAT is accepted; auto debounce exists but gated.
3. **Chatwoot→Hub live path** still depends on n8n/bridge; Odoo webhook fan-out helps when Evolution hits Odoo; Test Odoo downtime still breaks remote n8n calls.
4. **Broken Evolution ICP/instance stubs** (`:9` URLs) existed on Test — fixed for `sabry min`; other DBs may still need the same.
5. **OpenProject / Odoo task auto-create** not enabled (review mode); only search + parent recommendation.
6. **Production not upgraded** — waiting on: Dify v3 prompt publish, Prod Evolution instance URL audit, backup, and explicit go-ahead.
7. **Path scoring** still sensitive to bare vs absolute path strings.

---

## 9. Production decision

**Do not upgrade Production yet.**

Required before Prod:
1. Publish Dify workflow/prompt that returns schema v3 `items[]`.
2. Backup Prod DB.
3. Upgrade `whatsapp_hub` + `devhub_whatsapp` + restart bridge for webhook fan-out.
4. Verify Evolution instance URL/key on Prod (reject `:9` stubs).
5. Keep `ai_triage_enabled=false` / `analysis_review_only=true` initially.
6. Confirm no manual-only schema patches required (`inbox_state` already in module code).

---

## 10. Safest next actions

1. Update Dify `wa_project_aware` app to schema v3 multi-item output using `technical_evidence` from the enriched payload.
2. Enable `ai_triage_enabled` + `auto_analysis_enabled` on Dev Needed **on Test only**, review-only, 3-minute debounce.
3. After one clean Test day with zero duplicate WI/OP creates → schedule Production upgrade.
