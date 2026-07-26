# P5F-A — Broader Text Campaign Governance Completion Report

**Date:** 2026-07-23  
**Decision:** `P5F-A BROADER TEXT CAMPAIGN GOVERNANCE PASSED`  
**Recommendation:** `READY TO DESIGN/ACTIVATE P5F-B FIRST REAL TEXT CAMPAIGN`  
**Not started:** P5F-B, P5G, scheduled Hub (P5F-E), media Hub

---

## Governance implementation

### Allowlist lifecycle semantics

`whatsapp_hub.campaign_hub_allowed_campaign_ids` now means:

> Campaigns **currently authorized to admit NEW Hub jobs**.

| Case | Health |
|------|--------|
| Admission-capable Hub Campaign (`mode=hub`, not completed/cancelled) missing from allowlist | **Critical** `hub_not_allowlisted` |
| Completed/cancelled historical Hub Campaign removed from allowlist | **OK** (history preserved) |
| Completed/cancelled still allowlisted | **Warning** `completed_campaign_still_allowlisted` |

### Approval / revoke helpers

Admin actions on `wa.campaign` (Campaign Hub Ops):

| Action | Behavior |
|--------|----------|
| **Approve Hub** | Eligibility gate → idempotent allowlist add; **does not** flip `wa_outbound_mode` |
| **Revoke** | Removes ID; refuses if pending/processing Hub jobs (quarantine first); history kept |
| **Cleanup Allowlist** | Completed/cancelled only → same as revoke |

No `whatsapp.campaign.routing.approval` model (CSV allowlist retained).

### Files changed (primary)

| Area | Path |
|------|------|
| Routing / eligibility / allowlist API | `whatsapp_hub/models/whatsapp_campaign_hub_routing.py` |
| Campaign health | `whatsapp_hub/models/whatsapp_campaign_hub_health.py` |
| Ops helpers + actions | `evolution_whatsapp_chat/models/wa_campaign.py` |
| Line re-render gate | `evolution_whatsapp_chat/models/wa_campaign_line.py` |
| Ops list UX | `evolution_whatsapp_chat/views/campaign_hub_ops_views.xml` |
| Campaign form helpers | `evolution_whatsapp_chat/views/wa_campaign_views.xml` (if present) |
| Tests | `whatsapp_hub/tests/test_whatsapp_campaign_p5f_governance.py` |
| E3 setUp robustness | `whatsapp_hub/tests/test_whatsapp_discuss_hub_health.py` |
| Runbook | `docs/.../P5F_A_GOVERNANCE_RUNBOOK.md` |

### Versions

| Module | Before (Prod) | After |
|--------|---------------|-------|
| `whatsapp_hub` | `19.0.1.9.0` | **`19.0.1.10.0`** |
| `evolution_whatsapp_chat` | `19.0.1.18.0` | **`19.0.1.19.0`** |

---

## Eligibility

Hub-eligible (approve) only when:

* text-only (no attachments)
* `send_mode=immediate`
* not `state=scheduled` / not queue+`scheduled_date`
* valid Hub instance + recipient phones
* not completed/cancelled
* render-freeze fields available

| Ineligible reason | Typical cause |
|-------------------|---------------|
| `attachments_media` | #15 / any attachments |
| `scheduled_not_supported` | #10–14 queue+scheduled; `send_mode=scheduled` |
| `orchestration_not_supported` | non-immediate send modes |
| `invalid_instance` / `invalid_recipient` | missing instance or phones |
| `completed` / `cancelled` | no new admission |

Scheduled + media remain **legacy-only** for P5F. First P5F-B Campaign must be fresh immediate text.

---

## Render freeze UX

| Action | Rule |
|--------|------|
| **Freeze Campaign Lines for Hub** | Freeze unlocked eligible lines; returns frozen / already / skipped / invalid |
| **Re-render for Hub** (admin, line) | Allowed only with no `hub_message_id` / `hub_outbound_id` / provider acceptance |
| After Hub refs | Unlock/re-render **blocked**; payload immutable |
| Message edit | Unlocked may freeze later with new content; locked unchanged |

Ops shows locked/unlocked counts.

---

## Health changes

* **Active vs historical:** critical allowlist gap only for admission-capable Hub Campaigns.
* **Cleanup warning:** completed still allowlisted.
* **Multi-Campaign:** multiple allowlisted IDs supported (`allowlisted_campaign_count`).
* Historical integrity checks (dups, hash, refs) unchanged.
* Per-instance pending age / failure monitoring retained from P5E.

Production after deploy (plane OFF, empty allowlist, historical #17–19 shadow): **healthy**, 0 critical, 0 warning — no false criticals from completed Hub history.

---

## Campaign Hub Ops

New/updated list columns and actions:

* Eligibility + reason, allowlisted, active authorization, cleanup flag, historical, render ready, locked/unlocked counts, jobs/pending/failed, health warning
* Decorations: danger (active Hub not allowlisted / ineligible allowlisted / leakage / render integrity); warning (cleanup / scheduled / unlocked / pending-failed)
* Actions: Approve Hub, Revoke, Cleanup Allowlist, Freeze Lines, Hub Jobs, Messages, Shadow, Quarantine

Search filters on non-stored computes were omitted (Odoo 19 invalid); list columns + decorations provide the ops surface (same pattern as Discuss Hub Ops).

---

## Tests

| Suite / tag | Result |
|-------------|--------|
| `whatsapp_p5f_governance` | **0 failed** |
| `whatsapp_p5e_campaign` | **0 failed** (in combined run) |
| `whatsapp_p5b_campaign` | **0 failed** (in combined run) |
| `whatsapp_p5c_campaign` | **0 failed** (14 tests; prior run had e3 setUp noise only) |
| `whatsapp_e3_health` | **0 failed / 0 error** after setUpClass default-instance clear |

Combined P5F+P5E+P5B+discuss-tag run: **0 failed, 0 error(s) of 43 tests** (`p5fa_test_full.log`).  
E3 alone: **0 failed of 13** (`p5fa_test_e3.log`).

Coverage includes: completed removed → no critical; completed still listed → warning; active not allowlisted → critical; multi-allowlist; approve/revoke/freeze/re-render; eligibility for text/scheduled/media/completed.

---

## Test UAT

Evidence: `p5fa_test_uat.txt` — **`UAT_ALL_PASS True`**

| Scenario | Result |
|----------|--------|
| R1 Active approved (eligible, allowlist, mode stays legacy) | **PASS** |
| R2 Completed cleanup → no `hub_not_allowlisted` | **PASS** |
| R3 Completed still allowlisted → cleanup warning | **PASS** |
| R4 Scheduled approval blocked | **PASS** |
| R5 Attachment approval blocked | **PASS** |
| R6 Freeze + re-render pre-Hub OK / post-Hub blocked | **PASS** |
| R7 Multiple allowlisted Campaigns | **PASS** |
| R8 Revoke with incomplete job refused | **PASS** |
| R9 Discuss isolation unchanged | **PASS** (#5/#10 stayed `legacy` on Test baseline) |

Test config restored: cutover `False`, allowlist empty, purposes=`discuss`. Test Campaign health after synthetic cleanup: **healthy**.

---

## Production deployment

### Backup

| Item | Value |
|------|-------|
| Path | `backups/pet_spot_elsahel_pre_p5fa_20260723T161635Z.dump` |
| Size | ~18M |
| `pg_dump` | success |

### Upgrade

`-u whatsapp_hub,evolution_whatsapp_chat` → exit **0** (`p5fa_upgrade_prod.log`).  
HTTP `/web/login` → **200**.

### Config before / after

| Control | Before | After |
|---------|--------|-------|
| Campaign cutover | False | **False** |
| Campaign allowlist | empty | **empty** |
| Instance Campaign cutover | False | **False** |
| Purposes | `discuss` | **`discuss`** |
| Batch / max pending | 5 / 20 | **5 / 20** |
| Discuss cutover | True | True |
| Discuss allowlist | `10,5` | **`10,5`** |

No Campaign Hub sends. No modes flipped.

---

## Campaign inventory validation

| ID | Mode | State | Notes |
|----|------|-------|-------|
| #10–14 | **legacy** | scheduled / queue | ~125 lines each — **unchanged**; not Hub candidates until P5F-E |
| #15 | **legacy** | draft | 1 attachment — Tier C / P5G — **unchanged** |
| #16–19 | **shadow** | completed | Historical test/soak — **unchanged** |
| Hub active | **0** | — | `mode_counts`: legacy=14, shadow=4, hub=0, total=18 |
| Pending/processing Campaign Hub jobs | **0** | — | |

---

## First Production health

| Check | Result |
|-------|--------|
| Campaign Hub health | **healthy** |
| Critical | **0** |
| Warning | **0** |
| Historical cleanup behavior | Completed Hub Campaigns not on allowlist → **no false criticals** |

---

## Discuss regression

| Item | Value |
|------|-------|
| Channel #5 | **hub** |
| Channel #10 | **hub** |
| Allowlist | **`10,5`** |
| Discuss health | **healthy** (0 critical / 0 warning) |

---

## Standing control plane

Code/ops ready for future:

```text
purposes = discuss,campaign
campaign_cutover ON (global + instance)
allowlist fail-closed
new Campaign default = legacy
approved = allowlisted + mode hub (last)
```

**Not activated** in Production by P5F-A.

---

## Exit criteria checklist

1–18 from task brief: **met** (governance semantics, helpers, Ops, runbook, tests, UAT, Prod OFF + healthy, Discuss unchanged).

---

## Final decision

**`P5F-A BROADER TEXT CAMPAIGN GOVERNANCE PASSED`**

**`READY TO DESIGN/ACTIVATE P5F-B FIRST REAL TEXT CAMPAIGN`**

Do not start P5F-B or P5G from this report. Stop here.
