# E3 — Production Discuss Hub Operational Standardization — Completion Report

**Date:** 2026-07-23  
**Decision:** `E3 OPERATIONAL STANDARDIZATION PASSED`  
**Scope:** Ops tooling + documentation only — **no** Discuss routing / allowlist / mode / flag / Campaign / Phase 5 changes.

---

## Documentation

| Item | Path / content |
|------|----------------|
| Runbook | [`E3_OPERATOR_RUNBOOK.md`](./E3_OPERATOR_RUNBOOK.md) |
| Onboarding policy | New WA channel → `legacy` → optional `shadow` → Hub only after evidence + allowlist + approval |
| Rollback hierarchy | Channel → Instance → Global Discuss; quarantine mandatory; never legacy-resend accepted Hub messages |
| Soak stop thresholds | Outside-allowlist job, legacy leakage, duplicates, pending >15m, retry exhaustion, >20% permanent fail |

---

## Ops UX

| Item | Detail |
|------|--------|
| Action / view | **Discuss Hub Ops** (`action_discuss_hub_ops`) on `discuss.channel`, domain `wa_phone != False` |
| Menu | WhatsApp messaging → Discuss Hub Ops (`base.group_system`) |
| Helper fields (computed, non-stored) | `wa_hub_allowlisted`, `wa_hub_instance_name`, `wa_hub_conversation_id`, `wa_hub_pending_count`, `wa_hub_last_job_state`, `wa_hub_last_outbound_at`, `wa_shadow_matched_count`, `wa_shadow_mismatch_count`, `wa_hub_health_warning` |
| Warning decorations | Danger: hub ∧ ¬allowlisted; Warning: allowlisted ∧ ¬hub, pending >0, shadow mismatches, health warning text |
| Quarantine | Per-row **Quarantine** button → existing `action_quarantine_hub_outbound` (no semantic change) |
| Saved filters | Unified Bridge / Pending / Failed; Shadow Matched / Mismatches; Discuss Source messages |

---

## Health service

| Item | Detail |
|------|--------|
| Model | `whatsapp.discuss.hub.health` (`whatsapp_hub/models/whatsapp_discuss_hub_health.py`) |
| API | `service_run_health_check()`, `cron_run_health_check()` — **read-only** for routing |
| Checks | Hub∈allowlist, allowlist IDs exist, JID present, instance resolvable, jobs outside allowlist, stale pending >15m, duplicate provider IDs, duplicate business keys, current legacy leakage, compat warnings |
| Severity | Critical: hub not allowlisted, missing JID, incomplete job outside allowlist, stale pending, current leakage, dup provider/biz; Warning: historical sent jobs outside allowlist, compat gaps |
| Monitoring window | Leakage floor = trailing contiguous `hub_unified` streak (`create_date`,`id`); lookback 30d; dup lookback 7d |
| UI | **Discuss Hub Health** singleton form: last run, status, issue/critical/warning counts, JSON result, manual Run |

---

## Cron

| Item | Detail |
|------|--------|
| Name | WhatsApp Hub: Discuss Hub Health Check |
| Frequency | Every **1 hour** |
| Behavior | Run checks → log summary → activity only for **new** critical fingerprint |
| Duplicate suppression | `last_issue_fingerprint` SHA of open critical keys; unchanged fingerprint → no new activity |
| Auto-rollback | **None** |

---

## Tests

| Suite | Tag | Result |
|-------|-----|--------|
| E3 health | `whatsapp_e3_health` | **0 failed / 13** (suite7) |
| Discuss Phase 4 + Campaign legacy | `whatsapp_discuss_p4` | **0 failed** (incl. `test_21_campaign_still_uses_legacy`) |
| Quarantine | `whatsapp_e1_quarantine` | **0 failed** |

Logs: `e3_test_suite7.log`, `e3_test_discuss_p4.log`.

---

## Test UAT

| Scenario | Result |
|----------|--------|
| Healthy Hub channel | critical_count=0 (status may be warning on shared historical sent-outside jobs) |
| Non-allowlisted Hub | `hub_not_allowlisted` critical |
| Stuck pending >15m | `stale_pending` critical |
| Recent legacy leakage | `legacy_leakage` critical |
| Activity dedupe (2× cron) | 1 then 1 |
| No allowlist/mode mutation by health | Confirmed |
| Restore Test config | allowlist restored empty (Test baseline); 0 leftover UAT channels |

Log: `e3_test_uat2.log` → `UAT_OK`.

---

## Production deployment

| Item | Detail |
|------|--------|
| Backup | `backups/pet_spot_elsahel_pre_e3_20260723T132819Z.dump` (18M) |
| Modules upgraded | `whatsapp_hub` **19.0.1.4.0 → 19.0.1.5.0**, `evolution_whatsapp_chat` **19.0.1.13.0 → 19.0.1.14.0** |
| Routing before | #5=hub, #10=hub, allowlist=`10,5`, global+inst#1 ON, purposes=`discuss`, pending=0 |
| Routing after | **Identical** |

---

## First Production health result

| Field | Value |
|-------|-------|
| Status | **healthy** |
| Channels checked / Hub | `{5,10}` |
| Allowlist | `{10,5}` (`10,5`) |
| Issues | `[]` |
| Critical | **0** |
| Warning | **0** |

Note: Initial run flagged log #19 (`OpenLow E1 Preflight Shadow Regression`) as leakage using first-ever Hub floor. Floor logic was refined to the **current Hub streak**; re-run is clean. No destructive log cleanup.

---

## Final Production state

| Control | Value |
|---------|-------|
| #5 | `hub` |
| #10 | `hub` |
| Allowlist | `10,5` |
| Hub-mode set | `{5,10}` |
| Global unified / Discuss cutover | **ON** |
| Instance #1 unified / Discuss cutover | **ON** |
| `unified_outbound_purposes` | `discuss` |
| Pending unified jobs | **0** |
| Campaign | still `_send_via_evolution` (`wa_campaign.py`) |

---

## Exit criteria checklist

1. Routing unchanged — **yes**  
2. Ops list/action — **yes**  
3. Allowlist visibility — **yes**  
4. Pending/shadow helpers — **yes**  
5. Health service — **yes**  
6. Cron — **yes** (hourly)  
7. Critical admin alerting — **yes**  
8. Duplicate activity suppression — **yes** (UAT + unit)  
9. No auto-routing/rollback — **yes**  
10. Operator runbook — **yes**  
11. Test suite — **pass**  
12. Test UAT — **pass**  
13. Prod health clean — **healthy**  
14. Campaign unchanged — **yes**  

---

## Final decision

**E3 OPERATIONAL STANDARDIZATION PASSED**

Campaign migration and Phase 5 were **not** started.
