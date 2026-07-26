# Phase 0 Audit — WhatsApp AI triage + live ingestion gaps

**Date:** 2026-07-26  
**DB:** `pet_spot_elsahel_test`  
**Baseline preserved:** analysis `#383`, messages `9181–9187`, backup `pet_spot_elsahel_test_pre_ai_pipeline_20260726T043521Z.dump`

## Root cause (proven)

Dev Needed Hub data was **never live-streamed**. It arrived only via **bulk Evolution `findMessages` backfills**:

| create_date cluster (UTC) | msgs | message_timestamp range |
|---------------------------|-----:|-------------------------|
| 2026-07-23 21:36 | 3428 | 2026-03-30 → 2026-07-23 21:26 |
| 2026-07-25 09:34 | 42 | 2026-07-13 → **2026-07-25 09:19:15** |
| 2026-07-26 03:58 | 7 (Kafaat) | 2026-07-25 14:47 → 2026-07-26 03:51 |

- Provider on all 3477 Dev Needed Hub rows: `evolution`; **Chatwoot message IDs = 0**.
- `chatwoot_evolution_bridge` **did** receive `messages.upsert` for Dev Needed and wrote Chatwoot (`chatwoot_ingest_ok`) through the morning of Jul 25.
- Native Odoo Evolution webhook (`WEBHOOK_GLOBAL_URL` → `:8027/bridge/evolution/webhook`) only updates legacy reply state — **does not call** `service_ingest_normalized`.
- n8n logged repeated **502 Bad Gateway** to `test.drpaws.ai` (Test Odoo origin down) around Jul 25 ~03:21 UTC when attempting Hub HTTP calls.
- After the 09:34 backfill stopped at message_timestamp **09:19:15**, Ahmed’s **14:47 RPC** thread never reached Hub until the **manual** `test_kafaat_rpc_analysis.py` pull at 03:58 Jul 26.

**Why monitoring missed it:** no inbound lag/watchdog; only `last_hub_message_at` (backfill completion time). No comparison to provider/Chatwoot freshness.

**Secondary ops blockers:** source `#9` has `ai_triage_enabled=false`, `project_mapping_state=ambiguous`, `analysis_prompt_version=wa_triage_v1`.

## Audit table

| Component | Current behavior | Gap | Evidence | Proposed fix | Risk |
|-----------|------------------|-----|----------|--------------|------|
| Evolution→Chatwoot bridge | Live upserts for Dev Needed | Does not write Hub | bridge logs `chatwoot_ingest_ok` | Keep; add Hub fan-out or recovery | Dual-write dupes if both paths |
| Odoo `/bridge/evolution/webhook` | Reply-state only | No Hub ingest | `bridge_unified.py` | Optional Hub fan-out on upsert | Prod webhook target |
| Hub `/whatsapp_hub/ingest` | Canonical idempotent ingest | Not fed live for Dev Needed | 3 create_date clusters | Feed via recovery + live bridge | Low |
| n8n Hub ingest | Calls Hub URL | 502 when Test Odoo down | n8n logs Cloudflare 502 | Watchdog + local URL | External |
| Message dedupe | `dedupe_key` + provider unique | OK for Evolution IDs | `_sql_constraints` | Keep; recovery uses same path | Low |
| Inbound health | Outbound Discuss/Campaign health only | No gap status | no inbound health model | `whatsapp.ingestion.health` + cron | Low |
| Gap recovery | Manual scripts / Hub→DevHub backfill | No Evolution→Hub cron | `test_kafaat_rpc_analysis.py` | `action_recover_missing_messages` | API limits |
| `ai_triage_enabled` | false on Dev Needed | Blocks auto enqueue | source id 9 | Controlled enable + review mode | False positives |
| Auto analysis | Manual enqueue only | No debounce | no cron/hook | Debounced pending batch | Over-analysis |
| Dify payload | id/ts/sender/body/media | Missing quote, direction, external IDs, sequence | `_job_payload` | Enrich serialization | Prompt size |
| Technical extract | Alias/WI candidates only | No traceback/path parse | candidates/context | Deterministic preprocessor | Regex false hits |
| Result schema | Single-task v2 | `contains_multiple_tasks` LLM-set; empty AC accepted | analysis 383 | Multi-item + server validation | Prompt/compat |
| Work create | Dev Hub WI on approve | No OP/Odoo task auto | `action_approve_create_work` | Search + recommend OP parent; review mode | Prod writes |
| Eval harness | Ad-hoc MD report | No scored store | reference MD | `dev.whatsapp.analysis.eval` | Low |

## Baseline #383 (frozen)

- state `awaiting_review`, classification `new_dev_request`, action `create_work`
- project 11 Kafaat, `contains_multiple_tasks=false`
- mode `historical_quality_evaluation|kafaat-rpc-20260725`, prompt `wa_project_aware_v2.3`
