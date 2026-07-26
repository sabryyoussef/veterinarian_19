# P5E — Low-Volume Production Campaign Hub Soak — Activation Completion Report

**Date:** 2026-07-23  
**Decision:** `P5E LOW-VOLUME CAMPAIGN HUB SOAK PASSED`  
**Recommendation (not started):** `READY TO DESIGN P5F BROADER TEXT CAMPAIGN CUTOVER`

Foundation baseline: [`P5E_CAMPAIGN_HUB_SOAK_FOUNDATION_COMPLETION_REPORT.md`](./P5E_CAMPAIGN_HUB_SOAK_FOUNDATION_COMPLETION_REPORT.md)  
Evidence: `p5e_soak_evidence.json`, `p5e_soak_activation.log`, `p5e_soak_activation_resume.log`, `p5e_soak_hardgate_t0.jsonl`

---

## Preflight

### Backup

| Item | Value |
|------|-------|
| Path | `backups/pet_spot_elsahel_pre_p5e_soak_20260723T154848Z.dump` |
| Size | ~18M |
| `pg_dump` exit | **0** |
| Service before | **active** |
| HTTP `:8027` before | **200** |
| HTTP after restore | **200** |

### Hard gate

| Gate | Result |
|------|--------|
| Production HTTP healthy | **PASS** |
| Evolution `sabry min` open | **PASS** (`state=open`) |
| Campaign health healthy / critical=0 | **PASS** |
| Discuss health healthy | **PASS** |
| #5 / #10 hub | **PASS** |
| Discuss allowlist `10,5` | **PASS** |
| Campaign cutover False | **PASS** |
| Campaign allowlist empty | **PASS** |
| Instance #1 Campaign cutover False | **PASS** |
| purposes=`discuss` | **PASS** |
| purpose=campaign pending/processing=0 | **PASS** |
| Modules 19.0.1.9.0 / 19.0.1.18.0 | **PASS** |
| Freeze API available | **PASS** |
| Campaign health service available | **PASS** |
| Quarantine service available | **PASS** |
| No Hub-mode Campaigns | **PASS** |
| Partner #469 = `201000059085` | **PASS** |
| P5E foundation tests/UAT | **PASS** (prior foundation report) |

**HARD_GATE: PASS**

### T0

| Control | Value |
|---------|-------|
| Campaign cutover | False |
| Allowlist | empty |
| Instance #1 Campaign cutover | False |
| purposes | `discuss` |
| `campaign_admit_batch_size` | 25 → later set to **5** for soak |
| `max_pending_campaign_jobs` | 100 → later set to **20** for soak |
| purpose=campaign pending/processing | 0 |
| Campaign health | healthy |
| Discuss health | healthy |
| #5 / #10 | hub |
| Discuss allowlist | `10,5` |
| Mode counts | legacy=14, shadow=2, hub=0 |
| Discuss pending / oldest | 0 / 0m |
| Campaign pending / oldest | 0 / 0m |

---

## Soak Campaign A

| Field | Value |
|-------|-------|
| ID / name | **18** / `P5E Campaign Hub Soak A (PROD)` |
| Lines | **7** — IDs **3021–3027** |
| Recipients | controlled clones → all `201000059085` (SoakA01…SoakA07) |
| Attachments | **0** |
| Initial mode | legacy → freeze → allowlist `18` → **hub** last |
| Processor runs | Run1 admit **5** + send; Run2 admit **2** + send |
| Batch observed | admit capped at **5**; **2** remained pending |

### Per-line Hub evidence (A)

| Line | Hub msg | Job | Provider ID | Compat log | Frozen body |
|------|---------|-----|-------------|------------|-------------|
| 3021 | 60 | 21 | `3EB0F60849CEBC445C59A0` | 57 | `P5E Hub Soak A — SoakA01` |
| 3022 | 61 | 22 | `3EB0598061F0DCE1C44E8B` | 58 | `P5E Hub Soak A — SoakA02` |
| 3023 | 62 | 23 | `3EB0B02713152431B6E611` | 59 | `P5E Hub Soak A — SoakA03` |
| 3024 | 63 | 24 | `3EB01CEB603402C78CD42B` | 60 | `P5E Hub Soak A — SoakA04` |
| 3025 | 64 | 25 | `3EB006E181A41F2845F67E` | 61 | `P5E Hub Soak A — SoakA05` |
| 3026 | 65 | 26 | `3EB020B6DAEF7864C023CF` | 62 | `P5E Hub Soak A — SoakA06` |
| 3027 | 66 | 27 | `3EB0BAC1E466B21298894D` | 63 | `P5E Hub Soak A — SoakA07` |

### A verification summary

* All lines `rendered_locked=True`; **100%** frozen body ↔ Hub message/job hash agreement
* business keys `campaign:18:{line_id}`; priority **3**; `send_origin=hub_unified`
* Unique providers **7/7**; retries **0**; walog twins **0**; bridge queue **0**
* Safe processor replay: no duplicate jobs
* Counters: 7/7 sent

### A health checkpoints

| Checkpoint | Campaign | Discuss |
|------------|----------|---------|
| A midpoint | healthy / 0 crit / 0 warn | healthy |
| A complete | healthy / 0 crit / 0 warn | healthy |

---

## Soak Campaign B

| Field | Value |
|-------|-------|
| ID / name | **19** / `P5E Campaign Hub Soak B (PROD)` |
| Lines | **8** — IDs **3028–3035** |
| Recipients | controlled clones → all `201000059085` (SoakB01…SoakB08) |
| Attachments | **0** |
| Transition | A → shadow; allowlist → **19** only; B legacy → **hub** last |
| Processor runs | Run1 admit **5**; pause; send; resume; admit **3**; send |

### Per-line Hub evidence (B)

| Line | Hub msg | Job | Provider ID | Compat log | Frozen body |
|------|---------|-----|-------------|------------|-------------|
| 3028 | 67 | 28 | `3EB0B272F6AA2B86379759` | 64 | `P5E Hub Soak B — SoakB01` |
| 3029 | 68 | 29 | `3EB01B873C66A46BF51ADE` | 65 | `P5E Hub Soak B — SoakB02` |
| 3030 | 69 | 30 | `3EB037A4C06849A2817665` | 66 | `P5E Hub Soak B — SoakB03` |
| 3031 | 70 | 31 | `3EB050EE1CC5B18F2B64EA` | 67 | `P5E Hub Soak B — SoakB04` |
| 3032 | 71 | 32 | `3EB0F6A67F8994083C5BD8` | 68 | `P5E Hub Soak B — SoakB05` |
| 3033 | 72 | 33 | `3EB0BF71591B4CC643BE6F` | 69 | `P5E Hub Soak B — SoakB06` |
| 3034 | 73 | 34 | `3EB0B26B40B7490E689A7D` | 70 | `P5E Hub Soak B — SoakB07` |
| 3035 | 74 | 35 | `3EB0178825D356B6114220` | 71 | `P5E Hub Soak B — SoakB08` |

### B verification summary

* Same lineage/transport/compat invariants as A
* Unique providers **8/8**; retries **0**; bridge **0**; hash agreement **100%**
* Counters: 8/8 sent

### B health checkpoints

| Checkpoint | Campaign | Discuss |
|------------|----------|---------|
| B midpoint | healthy / 0 crit / 0 warn | healthy |
| B complete | healthy / 0 crit / 0 warn | healthy |

---

## Pause / resume

Observed on Campaign B:

1. Admitted batch of **5**; **3** left unadmitted.
2. `action_pause_campaign` → state=`paused`.
3. `_process_campaign_queue` while paused → **no new admissions** (hub outbound IDs unchanged).
4. Already-admitted Hub jobs finished → **5 sent** while paused.
5. `action_resume_campaign` → remaining **3** admitted.
6. No duplicate business keys / Hub jobs; freeze locks unchanged.
7. Remaining 3 sent successfully.

---

## Aggregate

| Metric | Value |
|--------|-------|
| Total soak lines | **15** |
| Successful Hub sends | **15** |
| Unique provider IDs | **15** |
| Canonical Hub messages | **15** (IDs 60–74) |
| Hub outbound jobs | **15** (IDs 21–35) |
| Compatibility logs | **15** (`hub_unified`) |
| Legacy sends | **0** |
| Bridge queue delta | **0** |
| Duplicate sends / business keys | **0** |
| Retries | **0** |
| Jobs outside allowlist | **0** |
| Render hash agreement | **100%** |
| walog twins | **0** |

---

## Fairness / backpressure

| Setting | Value |
|---------|-------|
| `campaign_admit_batch_size` | **5** (effective) |
| `max_pending_campaign_jobs` | **20** (not naturally hit at volume 15; hard threshold proven on Test) |

Batch behavior: no run admitted more than 5 new lines; remainder stayed pending until next run.

| Fairness point | Discuss pending / oldest | Campaign pending / oldest |
|----------------|--------------------------|---------------------------|
| T0 / resume_T0 | 0 / 0m | 0 / 0m |
| A midpoint | 0 / 0m | 5 (admitted, then drained) |
| A complete | 0 / 0m | 0 / 0m |
| B midpoint | 0 / 0m | 0 / 0m |
| B complete / final | 0 / 0m | 0 / 0m |

**Starvation result:** no Discuss pending aged >10 minutes; Campaign priority remained **3**; Discuss isolation clean.

---

## Campaign health

| Checkpoint | Status | Critical | Warning |
|------------|--------|----------|---------|
| before activation | healthy | 0 | 0 |
| A midpoint | healthy | 0 | 0 |
| A complete | healthy | 0 | 0 |
| B midpoint | healthy | 0 | 0 |
| B complete | healthy | 0 | 0 |
| final post-restore | healthy | 0 | 0 |

No render-hash mismatch. No lifecycle divergence. No legacy leakage.

---

## Discuss isolation

| Check | Result |
|-------|--------|
| #5 = hub | **confirmed throughout** |
| #10 = hub | **confirmed throughout** |
| Discuss allowlist = `10,5` | **confirmed** |
| Discuss health | **healthy** at all checkpoints |
| Discuss flags/modes unchanged | **confirmed** |
| No Campaign quarantine of Discuss | **confirmed** |

---

## Safe restore

| Action | Result |
|--------|--------|
| Campaign A mode | hub → **shadow** (completed) |
| Campaign B mode | hub → **shadow** (completed) |
| Quarantine A | ok; cancelled=0; already_sent=**7** (jobs 21–27 preserved) |
| Quarantine B | ok; cancelled=0; already_sent=**8** (jobs 28–35 preserved) |
| Allowlist | **empty** |
| Instance #1 Campaign cutover | **False** |
| Global Campaign cutover | **False** |
| purposes | `discuss,campaign` → **`discuss`** |
| batch / max_pending | kept conservative **5 / 20** |

---

## Final Production state

* global Campaign cutover = **False**
* Campaign allowlist = **empty**
* instance #1 Campaign cutover = **False**
* purposes = **discuss**
* Campaign A (#18) = **shadow / completed**
* Campaign B (#19) = **shadow / completed**
* #16 = shadow / completed
* #17 = shadow / completed
* normal Campaigns = legacy
* hub Campaign count = **0**
* purpose=campaign pending/processing = **0**
* batch=**5**, max_pending=**20** (Hub Campaign admission only; Campaign Hub OFF)
* #5 = **hub**, #10 = **hub**
* Discuss allowlist = **10,5**
* Discuss health = **healthy**
* Campaign health = **healthy**

Historical Hub messages/jobs/provider IDs for soak lines **preserved**.

---

## Notes

* First activation attempt stopped on invalid field `started_date` before any Hub send; campaigns/flags already prepared. Resume script completed full soak from that prepared state (no customer traffic; no Discuss changes).
* Quarantine validation on Production used completed soak Campaigns only (sent jobs preserved); mixed pending cancel proved on Test UAT.

---

## Final decision

**`P5E LOW-VOLUME CAMPAIGN HUB SOAK PASSED`**

Recommend:

**`READY TO DESIGN P5F BROADER TEXT CAMPAIGN CUTOVER`**

Do **not** start P5F automatically.
