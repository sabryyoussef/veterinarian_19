# P5E — Campaign Hub Soak Foundation — Completion Report

**Date:** 2026-07-23  
**Decision:** `P5E CAMPAIGN HUB SOAK FOUNDATION PASSED`  
**Recommendation (not started):** `READY TO ACTIVATE P5E LOW-VOLUME CAMPAIGN HUB SOAK`

Design baseline: [`P5E_CAMPAIGN_HUB_SOAK_AND_HEALTH_DESIGN.md`](./P5E_CAMPAIGN_HUB_SOAK_AND_HEALTH_DESIGN.md)

**Scope completed:** foundation only — render freeze, Campaign health, cron, Ops, tests, Test UAT, Production upgrade with Campaign Hub **OFF**.

**Explicitly not done:** Production soak, Campaign cutover/allowlist/purposes activation, P5F, media Hub support, Discuss changes.

---

## Rendering freeze

### Fields (`wa.campaign.line`)

| Field | Purpose |
|-------|---------|
| `rendered_body` | Immutable frozen outbound text |
| `rendered_body_hash` | SHA256 of exact stored body |
| `rendered_at` | Freeze timestamp |
| `rendered_locked` | When True, never re-render from `campaign.message` |

Helper: `campaign_line_body_hash(text)` — SHA256 UTF-8, no semantic rewriting.

### Freeze API

* `wa.campaign.line.service_freeze_rendered_body()`
* `wa.campaign.line.get_frozen_or_freeze_body()`
* Routing: `whatsapp.campaign.hub.routing.service_freeze_campaign_line(line)`

**Idempotent:** if already locked with body+hash → return existing body; do not change hash/timestamp.

**If not locked:** render once via existing `_render_message_for_line` (from `campaign.message` + personalise) → store body/hash/at/locked → sync `line.message` for operator visibility.

### Source-of-truth rule

```text
campaign.message (authoring)
  → render/personalize once
  → freeze on Campaign line
  → preview / Hub admit / Hub send / retry / shadow legacy send
     all use frozen snapshot
```

Template mutation after freeze does **not** change locked lines. New unfrozen lines may use the updated template.

### Hub / shadow integration

* Hub (`_process_campaign_queue_hub`): freeze before admit; payload body = frozen body; Hub-linked lines reuse identity + frozen body (no second logical message).
* Shadow (`_process_campaign_queue_shadow`): freeze → preview(frozen) → legacy send(frozen) → evidence compare.
* Retries/replays never silently re-render locked lines.

### Immutability behavior

Verified by automated tests + Test UAT R1: change `campaign.message` after freeze → line/Hub bodies unchanged.

---

## Campaign health

### Model / service

* Model: `whatsapp.campaign.hub.health` (singleton, mail activity mixin)
* Separate from `whatsapp.discuss.hub.health`
* `service_run_health_check(notify=..., create_activities=...)` — **read-only** for routing/transport (no send, retry, quarantine, flag/allowlist/purpose mutation)

### Checks (minimum)

Allowlist integrity, job outside allowlist (when cutover/allowlist active), stale pending, stuck processing without provider, duplicate business keys / provider IDs, legacy leakage on **active Hub-mode** campaigns, lifecycle divergence (active Hub), Hub ref consistency, compat gaps, `walog:*` twins, pending volume / backpressure, render hash mismatch (locked + active Hub), Discuss starvation warning, elevated failure rate.

### Severity

* **Critical:** not allowlisted Hub campaign, job outside allowlist, duplicate provider/business key, legacy leakage, lifecycle divergence, render hash mismatch, stuck processing >15m, malformed allowlist, missing allowlisted campaign.
* **Warning:** stale pending >30m, pending volume ≥ warn threshold, backpressure, compat gap, failure rate ≥20%, Discuss starvation.

ICP defaults: `campaign_health_stale_minutes=30`, `campaign_health_stuck_processing_minutes=15`, `campaign_health_pending_warn=15`, `discuss_starvation_minutes=10`.

### Historical-data handling

* Lifecycle / render-hash / walog / legacy leakage scoped to **active Hub-mode** campaigns where appropriate.
* Incomplete jobs while cutover OFF → warning `orphan_active_campaign_jobs` (not false “outside allowlist” from historical sent P5D).
* Pre-freeze historical lines: render mismatch **not** applied without `rendered_locked`.
* Production first run: **healthy / 0 issues** despite P5D historical Hub-sent records (#17 shadow).

---

## Cron

| Item | Value |
|------|-------|
| Name | `WhatsApp Hub: Campaign Hub Health Check` |
| Frequency | Every **30 minutes** |
| Behavior | Run checks → log concise result → create admin activity for **new** critical fingerprints |
| Activity prefix | `Campaign Hub Health CRITICAL` |
| Dedupe | Same fingerprint → no duplicate unresolved activity |
| Auto-rollback | **None** |

---

## Campaign Hub Ops

| Item | Value |
|------|-------|
| Action / menu | **Campaign Hub Ops** on `wa.campaign` (system group) |
| View | Lightweight list with decorations |

### Helper fields

`wa_hub_allowlisted`, `wa_hub_instance_name`, `wa_hub_job_count`, `wa_hub_pending_count`, `wa_hub_failed_count`, `wa_hub_last_outbound_at`, `wa_hub_max_retry_count`, `wa_hub_legacy_leakage_count`, `wa_hub_eligible`, `wa_hub_render_warning`, `wa_hub_scheduled_warning`, `wa_hub_health_warning`

### Decorations

* Danger: hub not allowlisted; legacy leakage; render hash warning
* Warning: allowlisted but not hub; pending/failed Hub jobs; health warning

### Drill-downs

Hub Jobs, Messages, Shadow, Quarantine (admin; calls existing `service_quarantine_campaign` — **not** auto from health cron).

---

## Fairness / backpressure

### Metrics (health + Ops)

Pending Campaign / Discuss jobs, oldest pending ages (minutes), Campaign pending by Ops job counts.

### Soak recommendations (documented; **not** applied on Production foundation deploy)

| ICP | Recommended soak | Current general default kept |
|-----|------------------|------------------------------|
| `campaign_admit_batch_size` | **5** | **25** |
| `max_pending_campaign_jobs` | **20** | **100** |

These ICPs affect **Hub Campaign admission only** (not legacy Campaign path). Foundation deployment did **not** change Production admit/max defaults so legacy behavior stays unchanged.

Campaign priority remains **3**. Discuss priority unchanged. No auto-pause scheduler in foundation (monitor only).

---

## Scheduled / media warnings

* Scheduled + `wa_outbound_mode=hub` → Ops warning: scheduled time not enforced by current Hub Campaign path (no scheduled Hub parity in P5E foundation).
* Attachments/media → `wa_hub_eligible=False` / not Hub eligible; Hub route fails pre-admission (no silent legacy fallback). Legacy Campaign path unchanged.
* Delivery/read projection expansion **not** implemented; Hub Campaign success truth remains provider acceptance → outbound sent → line sent.

---

## Tests

| Suite | Result |
|-------|--------|
| `whatsapp_p5e_campaign` | **0 failed / 15** |
| Regression `whatsapp_p5a_campaign,whatsapp_p5b_campaign,whatsapp_p5c_campaign,whatsapp_discuss_hub_health` | **0 failed / 41** |

Evidence: `p5e_test_suite.log`, `p5e_regression_suite.log`

Coverage includes freeze immutability, Hub/shadow frozen body, health severities, activity dedupe, Ops helpers, legacy/Hub smoke.

---

## Test UAT

| Scenario | Result |
|----------|--------|
| R1 Render freeze + template mutate | **PASS** |
| R2 Healthy allowlisted Hub | **PASS** |
| R3 Non-allowlisted Hub → critical | **PASS** |
| R4 Stuck processing | **PASS** |
| R5 Lifecycle divergence | **PASS** |
| R6 Legacy leakage | **PASS** |
| R7 Render hash mismatch | **PASS** |
| R8 Activity dedupe | **PASS** (n1=n2=1) |
| R9 Backpressure batch5/max20 | **PASS** |
| R10 Pause / resume / quarantine | **PASS** |
| R11 Discuss isolation (unchanged) | **PASS** |

Evidence: `p5e_test_uat.log`  
Test Campaign plane restored afterward (cutover False, allowlist empty, purposes=`discuss`).

**Note:** Test DB Discuss #5/#10 were already `legacy` at UAT baseline; R11 verified **unchanged**. Production Discuss remains hub (below).

---

## Production deployment

### Backup

| Item | Value |
|------|-------|
| Path | `backups/pet_spot_elsahel_pre_p5e_20260723T154059Z.dump` |
| Size | ~18M |
| `pg_dump` | success |

### Versions

| Module | Before | After |
|--------|--------|-------|
| `whatsapp_hub` | `19.0.1.8.0` | **`19.0.1.9.0`** |
| `evolution_whatsapp_chat` | `19.0.1.17.0` | **`19.0.1.18.0`** |

Upgrade: `-u whatsapp_hub,evolution_whatsapp_chat` → exit **0** (`p5e_upgrade_prod.log`).

### Before / after Campaign control plane

| Control | Before | After |
|---------|--------|-------|
| Campaign cutover | False | **False** |
| Campaign allowlist | empty | **empty** |
| Instance #1 Campaign cutover | False | **False** |
| purposes | `discuss` | **`discuss`** |
| Campaign #16 | shadow / completed | shadow / completed |
| Campaign #17 | shadow / completed | shadow / completed |
| purpose=campaign pending/processing | 0 | **0** |
| No Production Campaign Hub sends | — | **confirmed** |

---

## First Production Campaign health

| Metric | Value |
|--------|-------|
| Status | **healthy** |
| Issue count | **0** |
| Critical | **0** |
| Warning | **0** |
| Historical notes | P5D Hub-sent history on #17 (now shadow) did **not** create false critical leakage |

Cron present: `WhatsApp Hub: Campaign Hub Health Check` — 30 minutes — active.  
Freeze fields present on `wa.campaign.line`.

---

## Discuss regression

| Check | Result |
|-------|--------|
| #5 = hub | **confirmed** |
| #10 = hub | **confirmed** |
| Discuss allowlist = `10,5` | **confirmed** |
| Discuss health = healthy | **confirmed** (0 critical / 0 warning on post-upgrade run) |

---

## Final Production state

* Campaign cutover = **False**
* Campaign allowlist = **empty**
* Instance #1 Campaign cutover = **False**
* `unified_outbound_purposes` = **`discuss`**
* #17 / #16 = **shadow**
* Normal Campaigns = **legacy**
* purpose=campaign pending/processing = **0**
* #5 / #10 = **hub**
* Discuss allowlist = **10,5**
* Discuss health = **healthy**
* Campaign Hub health = **healthy**

---

## Final decision

**`P5E CAMPAIGN HUB SOAK FOUNDATION PASSED`**

Recommend:

**`READY TO ACTIVATE P5E LOW-VOLUME CAMPAIGN HUB SOAK`**

Do **not** start the soak automatically. Do **not** start P5F.
