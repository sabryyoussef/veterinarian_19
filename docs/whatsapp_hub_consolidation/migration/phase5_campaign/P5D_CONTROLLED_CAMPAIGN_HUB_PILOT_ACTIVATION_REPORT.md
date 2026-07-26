# P5D — Controlled Campaign Hub Pilot — Activation Completion Report

**Date:** 2026-07-23  
**Decision:** `P5D CONTROLLED CAMPAIGN HUB PILOT PASSED`  
**Next (not started):** `READY TO DESIGN P5E CAMPAIGN HUB SOAK AND HEALTH`

Design: [`P5D_CONTROLLED_CAMPAIGN_HUB_PILOT_DESIGN.md`](./P5D_CONTROLLED_CAMPAIGN_HUB_PILOT_DESIGN.md)

---

## Preflight

### Backup

| Item | Value |
|------|-------|
| Path | `backups/pet_spot_elsahel_pre_p5d_20260723T151355Z.dump` |
| Size | 17,897,440 bytes (~18M) |
| `pg_dump` exit | **0** |
| Production HTTP `:8027` | **200** |
| Service before activation | **active** (stopped during controlled shell activation) |

### Hard gate

| Gate | Result |
|------|--------|
| Production HTTP healthy | PASS |
| Evolution `sabry min` open | PASS (`state=open`, HTTP 200) |
| Discuss health | PASS (`healthy`) |
| #5 / #10 hub | PASS |
| Discuss allowlist `10,5` | PASS |
| Campaign cutover False | PASS |
| Campaign allowlist empty | PASS |
| Instance #1 Campaign cutover False | PASS |
| purposes=`discuss` | PASS |
| purpose=campaign pending/processing = 0 | PASS |
| Quarantine service available | PASS |
| P5B+P5C tests | PASS (**0 failed / 31**) |
| Partner #469 = `201000059085` | PASS |
| No Hub-mode Campaigns | PASS |

**HARD_GATE: PASS**

### T0

| Control | Value |
|---------|-------|
| Campaign cutover | False |
| Allowlist | empty |
| Instance #1 Campaign cutover | False |
| purposes | `discuss` |
| `campaign_admit_batch_size` | 25 |
| purpose=campaign pending/processing | 0 |
| #5 / #10 | hub |
| Discuss allowlist | `10,5` |
| Discuss health | healthy |
| legacy Campaigns | 14 |
| Campaign #16 | shadow |
| Hub Campaigns | none |

---

## Pilot Campaign

| Field | Value |
|-------|-------|
| ID / name | **17** / `P5D Controlled Campaign Hub Pilot (PROD)` |
| Line IDs | **3018**, **3019**, **3020** |
| Destinations | all `201000059085` (partner 469 + 2 clones) |
| Intended bodies | `Campaign Hub Pilot 01/02/03` (set on lines pre-start) |
| **Actual rendered bodies sent** | `Campaign Hub Pilot PLACEHOLDER` (see note) |
| Attachments | 0 |
| Initial mode | `legacy` → flipped to `hub` last |

**Body note:** `_process_campaign_queue_hub` calls `_render_message_for_line`, which rebuilt body from `campaign.message` (`PLACEHOLDER`) and overwrote the per-line Pilot 01/02/03 text. Transport/identity/provider proof is unaffected; three distinct Hub sends still occurred with unique business keys and provider IDs. Treat as activation-script lesson for P5E (set `campaign.message` to the intended template, or render from line message).

---

## Activation

| Step | Value |
|------|-------|
| batch size | 25 → **1** |
| purposes | `discuss` → **`discuss,campaign`** |
| global Campaign cutover | **True** |
| instance #1 Campaign cutover | **True** |
| allowlist | **`17`** only |
| pilot mode | legacy → **hub** |
| #16 | remained **shadow** (not allowlisted) |
| other Campaigns | all legacy / non-hub |

Discuss flags/modes/allowlist **unchanged** throughout.

---

## Line 01 (3018)

| Field | Value |
|-------|-------|
| business key | `campaign:17:3018` |
| status before admission | pending (hub refs empty) |
| status after admission | **pending** (hub_message_id=**57**, hub_outbound_id=**18**) |
| Hub message ID | **57** |
| outbound job ID | **18** |
| provider ID | **`3EB0DF7CD1B3373FA4C70E`** (real Evolution) |
| compat log ID | **54** (`hub_unified`, hub_message_id=57) |
| final status | **sent** |
| retry_count | **0** |
| legacy send count | **0** |
| bridge queue delta | **0** |
| instance | `sabry min` |
| purpose/source_app | campaign / campaign |
| related | `wa.campaign.line` / 3018 |
| walog twin | **0** |

---

## Line 02 (3019)

| Field | Value |
|-------|-------|
| business key | `campaign:17:3019` |
| Hub message / job | **58** / **19** |
| provider ID | **`3EB0A858B6EA95356EC5C0`** |
| compat log | **55** |
| final status | **sent** |
| retry_count | **0** |
| legacy / bridge | **0 / 0** |

(Admitted during L01 safe replay because batch=1 skips already-linked pending without consuming the batch slot — then sent via Hub `_send_one` with full verification before L03.)

---

## Line 03 (3020)

| Field | Value |
|-------|-------|
| business key | `campaign:17:3020` |
| Hub message / job | **59** / **20** |
| provider ID | **`3EB0667144771422F596D2`** |
| compat log | **56** |
| final status | **sent** |
| retry_count | **0** |
| legacy / bridge | **0 / 0** |

---

## Aggregate

| Metric | Result |
|--------|--------|
| Campaign lines | 3 |
| sent / failed / pending | **3 / 0 / 0** |
| Campaign state | **completed** |
| canonical Hub messages | **3** |
| Hub outbound jobs | **3** |
| unique real provider IDs | **3** |
| hub_unified logs | **3** |
| legacy sends | **0** |
| bridge queue delta | **0** |
| duplicate business keys / msgs | **0** |
| happy-path retries | **0** |
| jobs outside allowlist | **0** |

---

## Idempotency

Final processor replay after all three sent:

* Hub messages **+0**
* Hub jobs **+0**
* provider sends **+0**
* compatibility logs **+0**
* bridge queue **+0**

Per-line Hub refs unchanged.

---

## Discuss isolation

| Control | After pilot |
|---------|-------------|
| #5 | **hub** |
| #10 | **hub** |
| Discuss allowlist | **10,5** |
| Discuss health | **healthy** |
| Discuss purpose | still active (`discuss` retained in purposes during pilot; restored alone after) |

No Discuss routing/flag changes.

---

## Safe restore (Option B)

| Action | Result |
|--------|--------|
| Pilot mode | hub → **shadow** |
| Quarantine | ok; **already_sent=[18,19,20]**; cancelled=0 |
| Allowlist | **empty** |
| Instance #1 Campaign cutover | **False** |
| Global Campaign cutover | **False** |
| purposes | **`discuss`** |
| batch size | **25** |
| Sent Hub evidence | **preserved** |

---

## Final Production state

| Control | Value |
|---------|-------|
| Campaign cutover | **False** |
| Campaign allowlist | **empty** |
| Instance #1 Campaign cutover | **False** |
| purposes | **`discuss`** |
| `campaign_admit_batch_size` | **25** |
| Pilot #17 | **shadow** / completed |
| Campaign #16 | **shadow** |
| Normal Campaigns | **legacy** (no hub) |
| purpose=campaign pending/processing | **0** |
| purpose=campaign sent (pilot historical) | **3** |
| #5 / #10 | **hub** |
| Discuss allowlist | **10,5** |
| Discuss health | **healthy** |
| Production HTTP | **200** |

---

## Final decision

**P5D CONTROLLED CAMPAIGN HUB PILOT PASSED**

Live path proven with **real** Evolution acceptance for 3/3 lines; Hub-only transport; projection + `hub_unified` convergence; Option B restore complete; Discuss untouched.

Recommendation: `READY TO DESIGN P5E CAMPAIGN HUB SOAK AND HEALTH`

P5E was **not** started.
