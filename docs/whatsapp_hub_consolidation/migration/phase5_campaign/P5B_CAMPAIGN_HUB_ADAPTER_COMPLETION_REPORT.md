# P5B — Campaign Hub Adapter — Completion Report

**Date:** 2026-07-23  
**Decision:** `P5B CAMPAIGN HUB ADAPTER PASSED`  
**Next (not started):** `READY TO IMPLEMENT P5C CONTROLLED CAMPAIGN SHADOW`

Design: [`PHASE5_CAMPAIGN_HUB_MIGRATION_DESIGN.md`](./PHASE5_CAMPAIGN_HUB_MIGRATION_DESIGN.md)

---

## Routing implementation

Branch point in [`wa_campaign.py`](../../../../evolution_whatsapp_chat/models/wa_campaign.py) `_process_campaign_queue`:

```text
resolve_outbound_route(campaign)
  → legacy  → _process_campaign_queue_legacy()   # unchanged transport
  → shadow  → _process_campaign_queue_shadow()   # preview + legacy once + evidence
  → hub     → _process_campaign_queue_hub()      # Hub admit only
```

Decision API: `whatsapp.campaign.hub.routing.resolve_outbound_route`  
Admit API: `service_admit_campaign_line` → `whatsapp.outbound.message.service_enqueue_message`

| Module | Version |
|--------|---------|
| `whatsapp_hub` | **19.0.1.7.0** |
| `evolution_whatsapp_chat` | **19.0.1.16.0** |

---

## Hub Campaign payload

| Field | Value |
|-------|-------|
| Identity | `campaign:{campaign_id}:{line_id}` |
| purpose / source_app | `campaign` |
| related_model / res_id | `wa.campaign.line` / line.id |
| priority | **3** |
| message_type | text |
| send_now | False (enqueue; Hub cron owns send) |

---

## Queue ownership

Hub path never calls `_send_via_evolution` / `_send_media_evolution` / `integration.outbound.queue`.  
Verified in tests + Test UAT (`q_delta=0`).

---

## Lifecycle projection

Architecture: **Hub outbound write-back** via `_project_campaign_line_from_outbound()` on provider success and `_mark_retry`.

| Event | Line |
|-------|------|
| Admission | stays `pending`; sets `hub_message_id` / `hub_outbound_id` |
| Provider sent | `sent` + `wa_message_id` + `sent_date` |
| Temporary retry | stays non-sent |
| Exhausted fail | `failed` |
| Cancelled Hub job | `skipped` |

---

## Idempotency

Replay Start/Resume reuses same Hub message/job via business_key; line refs unchanged.

---

## Compatibility convergence

`wa.message.log` with `send_origin=hub_unified` + `hub_message_id`.  
Compat mirror prefers `hub_message_id` then `campaign:{id}:{line_id}` before `walog:*`.  
Never overwrites `campaign:*` business_key with walog.

---

## Batching / backpressure

| ICP | Default | Test UAT |
|-----|---------|----------|
| `campaign_admit_batch_size` | 25 | batch=2 → 2 admitted |
| `max_pending_campaign_jobs` | 100 | max=1 → 1 admitted, rest pending |

---

## Pause / resume / cancel / retry

| Action | Behavior |
|--------|----------|
| Pause | Stops new admissions; admitted Hub jobs continue |
| Resume | Continues pending; no duplicate Hub jobs |
| Cancel | Quarantines `purpose=campaign` Hub jobs for campaign |
| Retry failed | Hub-safe: no reset if provider-accepted; requeue same job if failed |

Shadow branch wired structurally (preview + legacy + evidence); Production activation deferred to P5C.

---

## Tests

| Suite | Result |
|-------|--------|
| `whatsapp_p5b_campaign` + `whatsapp_p5a_campaign` | **0 failed / 27** |
| `whatsapp_discuss_p4` + `whatsapp_e1_quarantine` | **0 failed / 23** |

---

## Test UAT

All scenarios passed (A–H): admission, provider success, idempotent replay, backpressure, batch, temp-fail/retry, attachments rejected, legacy regression. Test flags restored (campaign cutover False, allowlist empty, purposes discuss).

---

## Production deployment

| Item | Value |
|------|-------|
| Backup | `backups/pet_spot_elsahel_pre_p5b_20260723T143458Z.dump` |
| Campaign cutover | **False** |
| Campaign allowlist | **empty** |
| Campaign modes | **legacy** |
| purposes | **discuss** (no campaign) |
| purpose=campaign Hub jobs | **0** |
| Instance #1 campaign cutover | False |
| Legacy path | unchanged (`_send_via_evolution` / bridge queue) |

---

## Discuss regression

| Control | Value |
|---------|-------|
| #5 | **hub** |
| #10 | **hub** |
| Discuss allowlist | **10,5** |
| Discuss health | **healthy** |

---

## Final decision

**P5B CAMPAIGN HUB ADAPTER PASSED**

Recommendation: `READY TO IMPLEMENT P5C CONTROLLED CAMPAIGN SHADOW`

P5C was **not** started. Production Campaign Hub remains **OFF**.
