# Controlled Discuss Hub Expansion — Design Only

**Date:** 2026-07-23  
**Status:** DESIGN ONLY — no Production routing/flag changes in this task  
**Prior:** [`SINGLE_COHORT_HUB_CUTOVER_PILOT_ACTIVATION_REPORT.md`](./SINGLE_COHORT_HUB_CUTOVER_PILOT_ACTIVATION_REPORT.md)

---

## Final recommendation

**`READY FOR EXTENDED SINGLE-COHORT SOAK`**

Rationale: Production has only **two** WhatsApp Discuss channels. Channel **#10** has proven Hub success (3/3). Channel **#5** still has insufficient shadow volume (1 matched) for a second Hub cohort. Expansion beyond #10 should wait for a documented soak on #10 plus more shadow evidence on #5. Campaign remains out of scope.

---

## 1. Production Discuss channel inventory

Source of truth: Production DB `pet_spot_elsahel` (read-only inventory). Evidence: `discuss_expansion_inventory.txt`.

| ID | Name | Partner / group | Destination | Type | Instance | Mode | Outbound logs | Media logs | Last outbound | Shadow (matched/other) | Hub msgs | Hub conv | Unified jobs | Classification |
|----|------|-----------------|-------------|------|----------|------|---------------|------------|---------------|------------------------|----------|----------|--------------|----------------|
| **5** | WA: كريم ايهاب الساحل 2022 | Sabry Bridge Test (partner 469) | `201000059085` | Individual DM | `sabry min` | **shadow** | 2 legacy | 0 | 2026-07-23 11:32 | 1 / 0 | 1 | #7 | 0 | Test / low-risk |
| **10** | WA Group: Testopenclow (openlowtest) | Group (no partner) | `120363411424964076@g.us` | Group | `sabry min` | **shadow** | 10 legacy + 3 hub_unified | 0 | 2026-07-23 12:24 | 10 / 0 | 13 | #8 | 3 sent | Controlled test / validated Hub cohort |

### Totals

- WA Discuss channels: **2**
- Attachments on mail messages in channels 5/10: **0**
- Current hub-mode channels: **0**
- Flags: all cutover OFF; `unified_outbound_purposes=discuss`

### Dynamically created channels

`res.partner._get_or_create_wa_channel()` creates `discuss.channel` with `wa_phone` set and **does not** set `wa_outbound_mode` → Odoo field default **`legacy`**.

Any future Partner “Send WA” channel appears as **legacy** until an admin changes mode. These are **not** currently represented beyond the two rows above.

No other Production WA Discuss channels exist today (inventory is complete, not inferred).

---

## 2. Risk classification

### Tier A — Safe early expansion

| Channel | Why |
|---------|-----|
| **#10** OpenLow / Testopenclow | Hub pilot **PASSED**; 10/10 shadow matched; text-only; stable JID/instance; controlled test group; conversation #8 proven |

### Tier B — Requires more shadow evidence

| Channel | Why |
|---------|-----|
| **#5** Sabry Bridge Test DM | Low-risk **test** partner, but only **1** shadow matched sample; Hub path never used; should accumulate more shadow matches before Hub |

### Tier C — Do not migrate yet

| Category | Status on Prod |
|----------|----------------|
| Attachment/media-heavy Discuss WA | **None observed** (0 media logs / 0 attach msgs on 5 & 10) |
| Critical clinic/emergency Discuss WA | **None present** as WA Discuss channels |
| Unresolved JID/instance | **None** for current two |
| Campaign traffic | **Out of scope** (not Discuss routing) |

---

## 3. Recommended next cohort

**Option C (selected): Keep #10 as the Hub soak cohort; collect more shadow evidence on #5 in parallel.**

| Option | Assessment |
|--------|------------|
| A. Keep #10 permanently on Hub for soak | **Yes — next execution**, time-boxed soak (not “permanent forever”) |
| B. #10 Hub + one more channel now | **Premature** — #5 has only 1 shadow sample |
| C. #10 Hub soak + more shadow on #5 | **Recommended** |
| D. Other | N/A — inventory too small for multi-instance strategies |

**Do not execute in this task.**

---

## 4. Routing governance

### Modes (unchanged)

`legacy` | `shadow` | `hub`

### Rules

| Rule | Spec |
|------|------|
| New channel default | Always **`legacy`** (current field default; keep) |
| Shadow eligibility | Any non-critical channel with valid JID/instance |
| Shadow → Hub minimum evidence | Prefer **≥10** matched shadow observations **or** one formal Hub pilot batch (3/3) as on #10; **0** serious mismatches in last N samples |
| Who may change mode | **Admin only** — already UI-gated (`groups="base.group_system"` on `wa_outbound_mode`) |
| Production Hub activation | Requires **written approval record** (OP work package / short activation report) citing channel IDs, gate results, backup path |
| Global flags | Platform **capability**; never the sole routing decision |

Business users continue sending via normal Discuss permissions; they do not toggle Hub mode.

---

## 5. Global / instance / channel flag strategy

Keep the proven hierarchy:

```text
Platform capability:
  whatsapp_hub.unified_outbound_enabled
  whatsapp_hub.discuss_cutover_enabled
  instance.unified_outbound_enabled
  instance.discuss_cutover_enabled
  whatsapp_hub.unified_outbound_purposes = discuss   # already set — KEEP

Actual routing:
  channel.wa_outbound_mode ∈ {legacy, shadow, hub}
```

### Safety when multiple channels use Hub

- Higher-level flags stay ON for the soak/expansion window.
- Only allowlisted / explicitly `hub` channels send via Hub.
- All others remain `shadow` or `legacy` → still `_send_via_evolution`.
- Campaign / clinic ignore Discuss cutover flags.

**This remains safe enough** for Production’s current scale (2 channels, 1 instance), **with** one hardening control (section 6).

---

## 6. Explicit allowlist — **recommended**

### Risk without allowlist

During multi-channel soak, globals + instance flags are ON. If an operator mistakenly sets a future Partner channel to `hub`, it would immediately use Hub transport.

### Proposed control (implement before Expansion E2)

```text
ICP whatsapp_hub.discuss_hub_allowed_channel_ids = "10"
# later: "10,5"
```

Enforcement in `_send_whatsapp_discuss_message` when `mode=hub`:

1. Existing flag prerequisites, **and**
2. `channel.id` ∈ allowlist CSV (if ICP non-empty)

If allowlist empty → deny Hub (fail closed) **or** document “empty = allow any hub-mode channel” for Test only. **Production recommendation: fail closed when Discuss cutover is ON and allowlist is empty.**

Material risk reduction: **yes**, given dynamic Partner channel creation and admin-editable mode field.

---

## 7. Soak monitoring design

### Metrics (per approved Hub channel)

| Metric | Source |
|--------|--------|
| Hub sends / accepts | `whatsapp.outbound.message` `unified_bridge` + `state=sent` |
| Failures / retries | `state=failed|pending`, `retry_count` |
| Duplicate business keys | unique on `discuss:{ch}:{mm}` |
| Canonical duplicates | count by `business_key` / `wa_message_log_id` |
| Provider duplicates | same `evolution_message_id` on >1 message |
| Legacy leakage | `wa.message.log` with `channel_id=X` and `send_origin=legacy` while mode was `hub` |
| Jobs outside cohort | `discuss_channel_id NOT IN allowlist` |
| Conversation / JID / instance mismatches | compare message fields to channel `wa_phone` + instance map |
| Compat convergence | `hub_message_id` + Hub `wa_message_log_id` + no `walog:` twin |

### Anomaly alerts (stop / investigate)

- Hub-mode channel producing `send_origin=legacy`
- Duplicate business key / provider id
- Pending job older than **15 minutes**
- Failed with `retry_count >= max_retries`
- Any unified job outside allowlist

---

## 8. Success thresholds (fit actual volume)

Production Discuss WA volume is **very low** (mostly pilot traffic). Thresholds must be sample-based, not “days of customer load.”

### Extended single-cohort soak on #10 (E1)

| Criterion | Threshold |
|-----------|-----------|
| Additional Hub messages after re-activation | **≥10** successful `sent` (or ≥7 days if traffic slower — whichever first with min **5**) |
| Duplicate sends | **0** |
| Legacy leakage while `hub` | **0** |
| Canonical identity failures | **0** |
| Jobs outside cohort | **0** |
| Transport failure rate | Investigate if **>20%** of Hub attempts fail permanently; do not auto-expand |
| Conversation reuse | Same conversation #8 for group JID + discuss + instance |

### Promote #5 to Hub (E2) prerequisites

| Criterion | Threshold |
|-----------|-----------|
| Shadow matched on #5 | **≥10** |
| Shadow mismatches | **0** unexplained |
| Allowlist includes 5 | Yes |
| #10 soak E1 exit criteria met | Yes |

---

## 9. Operational dashboard / view recommendations

Prefer reuse over new apps:

1. **Existing:** WhatsApp Hub → Outbound Queue (filter `transport_mode=unified_bridge`, group by `discuss_channel_id`).
2. **Existing:** Discuss Shadow Reports (matched/mismatch by channel).
3. **Existing:** WhatsApp Messages (filter `source_app=discuss` / `discuss_channel_id`).
4. **Add (lightweight):** saved filters / a small `ir.actions.act_window` “Discuss Hub Migration” with domains:
   - Hub-mode channels (`wa_outbound_mode=hub`)
   - Pending unified jobs age > 15m
   - Shadow mismatches last 7d
5. Optional later: computed KPI fields on `discuss.channel` (Hub send count, last Hub error) — **not required** for E1.

---

## 10. Single-channel rollback (proven)

```text
1. channel.wa_outbound_mode = shadow
2. Quarantine incomplete unified_bridge jobs for that channel_id
3. Optionally remove channel from allowlist
4. If last Hub channel: disable instance + global Discuss/unified flags
```

Already exercised after the #10 pilot.

---

## 11. Cohort-wide / instance / global rollback

### Safe order (based on actual code)

Admission happens only when channel mode is `hub` **and** flags pass. Cron `process_pending` can still send **already admitted** jobs after mode change.

**Order:**

1. **Stop new admission** — set all Hub cohort channels → `shadow` (or clear allowlist first if enforced).
2. **Identify/quarantine** incomplete `unified_bridge` jobs for those `discuss_channel_id`s (`pending`/`processing` → `cancelled` + clear `next_retry_at`).
3. **Disable capability** — instance Discuss/unified OFF, then global Discuss/unified OFF.
4. Confirm zero hub-mode channels; confirm no pending unified jobs for Discuss.

### Scopes

| Scope | Action |
|-------|--------|
| One channel | Section 10 |
| One instance | All Hub Discuss channels on that instance → shadow; quarantine jobs; instance flags OFF |
| All Discuss Hub | All hub-mode channels → shadow; quarantine all Discuss `unified_bridge` incomplete; globals OFF |

---

## 12. Pending-job quarantine / reconciliation design

### States

| State | On channel leave Hub |
|-------|----------------------|
| `sent` + provider id | Leave; **do not** legacy-resend same `mail.message` |
| `failed` | Leave; new user text = new business key |
| `pending` / retry scheduled | **Cancel/quarantine** |
| `processing` | Wait short TTL; then cancel/fail if stuck |

### Recommendation: implement a small service (justified)

```python
env['whatsapp.outbound.message'].service_quarantine_discuss_channel(channel_id, reason=...)
```

- Searches `transport_mode=unified_bridge`, `discuss_channel_id=channel`, `state in (pending, processing)`
- Sets `cancelled`, clears `next_retry_at`, stamps reason
- Returns counts

Prefer this over manual SQL before Expansion E2. Optional wizard button on channel form (admin-only).

Prevents late Hub send and dual-engine confusion (Hub cron vs human legacy retry).

---

## 13. Text / media readiness assessment

| Topic | Finding | Expansion impact |
|-------|---------|------------------|
| Real Discuss attachment usage | **0** on current WA channels | Text-only Hub **does not block** current Prod Discuss expansion |
| Legacy Discuss attachments | Current path is plaintext via `html2plaintext`; Hub rejects attachments explicitly | No regression vs today’s Discuss behavior for media |
| Delivery/read | Not required for Hub pilot success; can wait | Improvement, not blocker |
| Retry | Hub-owned; Test-validated; Prod success path OK | OK for soak |
| Instance mapping | Single instance `sabry min` stable | OK |
| Hub cron | Must quarantine on rollback | Process + future service |
| **Blockers to controlled Discuss expansion** | Thin shadow on #5; no allowlist yet; no quarantine service | Soft blockers for E2, not for E1 soak |
| **Can wait** | Dashboard KPIs, delivery receipts, media Hub support | Yes |
| **Campaign blockers** | Separate Phase 5; Discuss expansion creates **no** Campaign dependency beyond keeping `_send_via_evolution` untouched | Campaign still blocked on its own cutover design |

---

## 14. Expansion phases (evidence-based)

### E1 — Extended Hub soak on #10 *(next execution)*

| Item | Spec |
|------|------|
| Cohort | Channel **#10** only |
| Prerequisites | Pilot PASSED; fresh backup; gates; allowlist=`10` (if implemented) or documented exception for E1 |
| Activation | Same as single-cohort design: purposes=discuss → globals → instance → #10=`hub` |
| Monitoring | Section 7 metrics |
| Success | Section 8 E1 thresholds |
| Rollback | Section 10 |
| Exit | Mark E1 PASSED → design E2 |

### E2 — Second channel (#5) after shadow depth

| Item | Spec |
|------|------|
| Cohort | #10 (remain or re-enter Hub) + **#5** |
| Prerequisites | ≥10 shadow matched on #5; 0 unexplained mismatches; allowlist `10,5`; quarantine service recommended live |
| Activation | Flags ON; set #5=`hub` last |
| Success | 3-message Hub pilot on #5 (same lineage checks as #10) + no leakage |
| Rollback | Per-channel or cohort-wide |

### E3 — All eligible text-only Discuss channels on `sabry min`

| Item | Spec |
|------|------|
| Cohort | Every Tier A/B channel that meets evidence bars (today: only 5 & 10) |
| Includes | Future Partner channels only after shadow period |
| Exit | All eligible channels Hub-capable; new channels still default legacy |

### E4 — Default Hub for newly **approved** Discuss channels

| Item | Spec |
|------|------|
| Not auto-Hub on create | Keep default **legacy** |
| Approval | Admin adds to allowlist + sets `hub` after shadow gate |
| Optional later | Policy “auto-shadow on create” for Partner WA channels |

### E5 — Legacy Discuss transport deprecation

| Item | Spec |
|------|------|
| Only after | E3 stable soak; media strategy decided; Campaign still separate |
| Action | Discourage/disable `_send_via_evolution` for Discuss wrapper paths; retain for Campaign until Phase 5 |

---

## 15. Exact recommended next execution task

**Task title:** `E1 — Extended Production Hub Soak on Discuss Channel #10`

**Scope:**

1. Implement (on Test first, then Prod upgrade if needed):
   - `discuss_hub_allowed_channel_ids` fail-closed allowlist, **and/or**
   - `service_quarantine_discuss_channel` (strongly recommended before E2; optional but useful in E1 rollback)
2. Fresh Prod backup + gates.
3. Re-activate Hub **only** for channel #10 (flags + mode), leave #5 on **shadow**.
4. Collect ≥10 additional Hub sends **or** time-boxed soak with min 5 successes (organic or controlled OpenLow test messages — authorize explicitly).
5. Monitor leakage/duplicates/outside jobs.
6. On exit: either keep #10 Hub under soak approval **or** restore shadow + disable flags (document choice).
7. In parallel: drive shadow samples on #5 toward ≥10 matched (no Hub on #5 yet).

**Out of scope:** Campaign; other channels to Hub; permanent global cutover.

---

## Campaign dependency note

Discuss expansion does **not** require Campaign changes. Keep Campaign on `_send_via_evolution`. Phase 5 remains a separate design after Discuss Hub is stable on all intended Discuss cohorts.

---

## Final recommendation (exact)

**`READY FOR EXTENDED SINGLE-COHORT SOAK`**
