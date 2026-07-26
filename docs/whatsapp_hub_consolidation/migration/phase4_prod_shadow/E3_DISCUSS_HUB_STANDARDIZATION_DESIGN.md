# E3 — Production Discuss Hub Standardization Design

**Date:** 2026-07-23  
**Status:** DESIGN ONLY — **no Production changes in this task**  
**Scope:** Governance, onboarding, monitoring, and ops tooling — **not** another channel cutover  
**Decision:** **`READY TO IMPLEMENT E3 OPERATIONAL STANDARDIZATION`**

Evidence baselines:

- E1: [`E1_EXTENDED_HUB_SOAK_REPORT.md`](./E1_EXTENDED_HUB_SOAK_REPORT.md)
- #5 shadow: [`E1_CHANNEL5_SHADOW_EVIDENCE_REPORT.md`](./E1_CHANNEL5_SHADOW_EVIDENCE_REPORT.md)
- E2: [`E2_SECOND_CHANNEL_HUB_PILOT_ACTIVATION_REPORT.md`](./E2_SECOND_CHANNEL_HUB_PILOT_ACTIVATION_REPORT.md)
- Inventory: `e3_design_inventory.txt`

---

## 0. Non-goals (this document)

- Do **not** change allowlist, modes, or capability flags.
- Do **not** send messages or activate new Hub channels.
- Do **not** start Campaign / Phase 5.
- Do **not** deprecate `_send_via_evolution` for Discuss or Campaign.
- Do **not** invent a routing migration for channels that are already Hub.

---

## 1. Current Production inventory (read-only)

### 1.1 WhatsApp Discuss channels

Production still has **exactly two** WA Discuss channels (`wa_phone` set). **No new WA channel since E2.**

| ID | Name | Destination | Mode | Allowlisted | Conv | Instance | Unified jobs (sent/pend/fail) | Shadow matched/mismatch |
|----|------|-------------|------|-------------|------|----------|-------------------------------|-------------------------|
| **5** | Sabry Bridge Test DM (`WA: كريم…`) | `201000059085` | **`hub`** | Yes | **#7** | `sabry min` | 3 / 0 / 0 | 11 / 0 |
| **10** | `Testopenclow` / openlowtest | `120363411424964076@g.us` | **`hub`** | Yes | **#8** | `sabry min` | 13 / 0 / 0 | 11 / 0 |

Partner #5 → `wa_partner_id=469`. Channel #10 has no partner (group).

### 1.2 Controls

| Control | Value |
|---------|--------|
| Allowlist raw / parsed | `10,5` / `[10, 5]` |
| Hub-mode IDs | `{5, 10}` |
| Global unified / Discuss cutover | ON / ON |
| Instance #1 unified / Discuss | ON / ON |
| Purposes | `discuss` |
| Pending/processing unified | **0** |
| Jobs outside allowlist | **0** |
| Quarantine service | Available |
| Campaign send | `_send_via_evolution` only |

### 1.3 Conversations

| Conv | Purpose | Remote JID | Instance | Msg count |
|------|---------|------------|----------|-----------|
| **7** | discuss | `201000059085@s.whatsapp.net` | sabry min | 14 |
| **8** | discuss | `120363411424964076@g.us` | sabry min | 24 |

### 1.4 Dynamic Partner channel creation

Source: `res.partner` WA channel `create()` sets `wa_phone` / `wa_partner_id` but **does not** set `wa_outbound_mode`.

Field default: **`wa_outbound_mode = 'legacy'`** (required).

**Conclusion:** New Partner WA channels still default to **legacy**. They cannot use Hub until an admin sets `hub` **and** the channel id is on the allowlist (fail-closed). This is the correct safety default while globals stay ON for the two-channel soak.

### 1.5 Compatibility / shadow notes

- `#5` / `#10` still have historical `send_origin=legacy` logs from shadow/pre-Hub eras — expected; not current leakage while Hub.
- Current Hub posts use `send_origin=hub_unified` (3 on #5 from E2; 13 on #10 from pilot+E1).

---

## 2. What E3 actually means (given both channels are Hub)

### Scope choice

| Option | Meaning | Fit? |
|--------|---------|------|
| **A** | All currently existing eligible Discuss channels use Hub | **Already true** for the only two Production WA channels |
| **B** | Hub is the approved standard for **future** channels after shadow + approval | **Still needed as policy** |
| **C** | Both A and B | A done; B remains |

**Meaningful E3 work is not another cutover.** It is **operational standardization**:

1. Documented permanent routing governance  
2. Future-channel onboarding runbook + thresholds  
3. Soak monitoring + stop thresholds  
4. Lightweight admin surface + optional health cron  
5. Rollback hierarchy confirmed as standing ops procedure  
6. Explicit legacy retention strategy (Discuss vs Campaign)

**Do not create an artificial “migrate remaining channels” phase** — the eligible set is empty of non-Hub channels.

---

## 3. Final Discuss routing policy

### 3.1 Target architecture

```text
Approved (mode=hub AND allowlisted)
  → Hub unified outbound → canonical whatsapp.message
  → whatsapp.outbound.message (unified_bridge)
  → bridge one-shot → Evolution

Unapproved / new
  → default legacy
  → optional shadow (evidence)
  → hub only after explicit approval + allowlist

Campaign
  → remains _send_via_evolution (out of Discuss policy)
```

### 3.2 New channel creation — recommendation

**Default mode: `legacy`** (keep current code default).

| Option | Pros | Cons |
|--------|------|------|
| Default `legacy` | Zero Hub risk; no shadow noise; matches code today | Requires explicit enable for evidence |
| Default `shadow` | Faster evidence | Extra Hub preview load; more DB rows; harder for high-volume Partner auto-create |

**Recommendation:** keep **`legacy` default**. Promote to `shadow` only when an operator intends validation. At current volume and with Partner auto-create, shadow-by-default adds overhead without benefit for most contacts.

### 3.3 Required policy fields (operational, not necessarily a new model)

| Policy item | Production rule |
|-------------|-----------------|
| Default mode | `legacy` |
| Minimum shadow evidence | ≥**10** matched samples (or ≥**5** if traffic is sparse over ≥7 days — prefer 10 when controlled sends are allowed) |
| Mismatch tolerance | **0** unexplained mismatches |
| Approval authority | System admin / WhatsApp Hub manager (same as mode + ICP edits today) |
| Allowlist addition | Explicit ICP update **before or with** Hub flip; never Hub without allowlist |
| Cutover procedure | backup → gate → allowlist add → (optional shadow probe) → `hub` last → N-message pilot |
| Rollback procedure | channel → `shadow` → quarantine(channel) → remove from allowlist; leave flags ON if other Hub channels remain |

---

## 4. Permanent allowlist recommendation

Evaluate `whatsapp_hub.discuss_hub_allowed_channel_ids`:

| Option | Verdict |
|--------|---------|
| **A. Keep permanently** | **Recommended** |
| B. Replace with routing-policy model | Later, only if channel count / approval audit needs grow |
| C. Remove after E3; rely on `wa_outbound_mode` alone | **Reject** while globals stay ON and mode is admin-editable |

**Why keep:** Defense-in-depth. With Discuss cutover ON at instance+global for soak, a mistaken `hub` on a new Partner channel would otherwise send via Hub immediately. Fail-closed allowlist is the proven E1/E2 control.

Operational complexity at N=2 is trivial (`10,5`). Revisit a model only if N≫10 or multi-approver audit is required.

---

## 5. CSV allowlist vs routing-policy model

| Dimension | CSV ICP | `whatsapp.discuss.routing.policy` model |
|-----------|---------|----------------------------------------|
| Simplicity | Excellent | Heavier |
| Audit history | Weak (ICP history limited) | Strong |
| Approval UX | Manual | Form + chatter |
| Current scale (2 channels) | Sufficient | Overkill |
| Fail-closed semantics | Already implemented | Would re-implement |

**Recommendation:** **keep CSV allowlist** for Production now. **Do not implement** a policy model in E3 unless a later scale trigger hits (e.g. ≥10 Hub channels or formal change-control requirement). Optional later: thin wizard that writes the CSV + logs an `ir.logging` / note.

---

## 6. Future-channel onboarding workflow

```text
1. Channel created (Partner WA or manual) → wa_outbound_mode=legacy
2. Legacy baseline (optional smoke: 1 successful Discuss send)
3. Enable shadow
4. Collect evidence (organic and/or controlled test destination only)
5. Validation gate (thresholds below)
6. Add channel id to discuss_hub_allowed_channel_ids
7. Hub pilot (3 controlled plain-text messages)
8. Extended soak (≥10 Hub successes or time-box with min 5)
9. Standard Hub operation (remain hub + allowlisted)
```

### Minimum thresholds (aligned with E1/E2; low volume)

| Gate | Threshold |
|------|-----------|
| Shadow matched | ≥10 |
| Shadow mismatches | 0 unexplained |
| Hub pilot | 3/3 Hub-only; 0 legacy; unique providers; one conv; converge compat logs |
| Duplicates / outside-allowlist jobs | 0 |
| Identity | Stable JID + instance + conversation |
| Approval | Explicit allowlist + mode change by admin |

Customer-facing channels: controlled sends only if relationship/test authorization exists (same rule as Bridge Test / openlowtest).

---

## 7. Two-channel Hub soak monitoring

### Metrics (per channel 5 and 10)

| Metric | Source |
|--------|--------|
| Hub sends / accepts | `whatsapp.outbound.message` `unified_bridge` + `state=sent` |
| Failures / retries | `failed` / `pending`, `retry_count` |
| Pending age | `write_date`/`create_date` of pending/processing |
| Provider duplicates | same `evolution_message_id` on >1 message |
| Canonical duplicates | duplicate `business_key` (should be unique index) |
| Compat convergence | log `hub_message_id` ↔ message `wa_message_log_id`; no `walog:*` twin for Hub posts |
| Legacy leakage | hub-mode channel + new log with `send_origin=legacy` |
| Jobs outside allowlist | `discuss_channel_id` not in parsed allowlist |
| Conv / JID / instance mismatch | compare to channel `wa_phone` + expected conv #7/#8 |

### Stop / rollback thresholds

| Condition | Action |
|-----------|--------|
| Any outside-allowlist unified job | Investigate immediately; systemic if unexplained |
| Legacy leakage on hub channel | Channel rollback |
| Duplicate provider or business key | Channel rollback; escalate if both cohorts |
| Pending unified > **15 minutes** | Investigate; quarantine if stuck after reconcile |
| Permanent fail rate > **20%** of recent Hub attempts | Pause new Hub promotions; consider channel rollback |
| Unexplained retries on happy-path posts | Investigate before further expansion |

---

## 8. Operational dashboard (smallest useful)

**Prefer reuse over new apps.**

### Recommended minimum (E3 implementation)

1. **Saved filters / favorites** on existing menus:
   - Outbound Queue: `transport_mode=unified_bridge`, group by `discuss_channel_id`
   - Discuss Shadow: group by `channel_id` / classification
   - WhatsApp Messages: `source_app=discuss`
2. **One new `ir.actions.act_window`** “Discuss Hub Ops” opening `discuss.channel` with domain `[('wa_phone','!=',False)]` and a **list view** showing:
   - name, id, `wa_outbound_mode`, `wa_phone`, partner
   - **computed (non-stored OK)** or related display: `x_hub_allowlisted` (bool from ICP parse), last outbound job state, pending count, shadow matched/mismatch counts  
3. Keep existing **Quarantine** button on channel form.

### Highlight rules (list decorations / optional computed warnings)

- hub mode but **not** allowlisted  
- allowlisted but mode ≠ hub (stale approval)  
- pending count > 0 with age flag  
- mismatch shadow count > 0  

### Defer

- Dedicated dashboard model / KPI graph views  
- Heavy stored counters (unless query cost becomes an issue)

**Recommendation:** saved filters **+** one lightweight act_window list with a few computed fields. **No** new policy model required for the dashboard.

---

## 9. Automated health checks

### Design a daily (or hourly) cron: `whatsapp.discuss.hub.health`

Checks:

1. Every `wa_outbound_mode=hub` channel id ∈ allowlist  
2. Every allowlisted id that still exists has valid `wa_phone`  
3. No `unified_bridge` pending/processing older than **15m** for Discuss  
4. No unified job with `discuss_channel_id` outside allowlist (when allowlist non-empty)  
5. Optional: scan recent window for duplicate provider ids / business keys  

### Alerting (practical)

| Severity | Action |
|----------|--------|
| Default | `_logger.warning` + optional `ir.logging` / note on a singleton config record |
| Critical (outside allowlist, hub∉allowlist, pending>threshold) | Create **mail.activity** for admin / Hub manager |
| Do **not** auto-create Dev Hub work items in v1 | Avoid coupling; optional later |

Keep v1 read-only detect + notify. No auto-rollback from cron (operator confirms).

---

## 10. Rollback hierarchy (standing ops)

### Channel

```text
1. wa_outbound_mode → shadow
2. service_quarantine_discuss_channel(id, reason=...)
3. Remove id from allowlist
4. If other Hub channels remain: leave global/instance flags ON
```

### Instance

```text
1. All hub-mode Discuss channels on that instance → shadow
2. Quarantine each channel’s incomplete unified jobs
3. Instance unified + Discuss cutover OFF
4. Optionally shrink allowlist to remaining Hub channels on other instances (N/A today — single instance)
```

### Global Discuss

```text
1. All hub-mode channels → shadow
2. Quarantine all Discuss unified incomplete jobs
3. Allowlist → "" (fail-closed)
4. Instance flags OFF
5. Global unified + Discuss cutover OFF
```

**Never** resend already provider-accepted Hub messages via legacy for the same `mail.message` / business key.

---

## 11. Legacy Discuss transport strategy

| Option | Notes |
|--------|--------|
| A. Keep indefinitely as primary | Wrong — Hub is now primary for approved channels |
| **B. Retain for legacy/shadow only** | **Current correct state** |
| C. Deprecate once all approved are Hub | “Approved” set is dynamic; keep B |
| D. Remove eventually | Only after Campaign Phase 5 redesign and long Hub soak |

**Staged approach:**

1. **Now–E3:** `_send_via_evolution` remains for `legacy`/`shadow` Discuss **and** all Campaign.  
2. **Post-E3 maturity:** Document that Hub is the only supported path for **approved** Discuss; legacy is non-approved + fallback.  
3. **Phase 5 (separate):** Campaign migration design — do not touch in E3.  
4. **Far later:** Consider removing Discuss legacy only when no channel uses legacy/shadow and Campaign has its own Hub path.

**Do not remove now.**

---

## 12. Is E3 implementation required?

| Work type | Required? |
|-----------|-----------|
| Routing migration of current eligible channels | **No** — already complete (`{5,10}` hub + allowlisted) |
| Operational standardization (policy, monitoring, health, light UX) | **Yes** — closes governance gap while soak continues |
| New routing-policy model | **No** (not at current scale) |
| Campaign changes | **No** |

So E3 is **not** “expand Discuss Hub to more existing channels.” It is **make Hub the governed standard for Discuss going forward** and **instrument the two-channel soak**.

---

## 13. E3 deliverables (minimum)

### Required now (next implementation task)

1. **Written Production routing governance** (this design + short runbook page operators can follow)  
2. **Future-channel onboarding checklist** (section 6) checked into docs  
3. **Discuss Hub Ops** list action + 2–4 computed helper fields (allowlisted?, pending count, shadow matched/mismatch)  
4. **Cron health check** (section 9) with activity on critical findings  
5. Confirm quarantine button + allowlist ICP documented in Hub admin help  

### Recommended later

- Allowlist edit wizard with validation (parse + show channel names)  
- Richer KPIs / graphs  
- Optional routing-policy model if N grows  

### Unnecessary now

- Migrating nonexistent third channels  
- Defaulting new channels to shadow/hub  
- Removing legacy Discuss send  
- Campaign / Phase 5 work  
- Replacing CSV allowlist  

---

## 14. E3 exit criteria

E3 is complete when:

1. All currently eligible Production Discuss channels are Hub-routed → **already true**  
2. Every Hub channel is explicitly allowlisted → **already true**  
3. New channels have a defined onboarding policy → **document + ops checklist**  
4. Rollback is operational → **service exists; document hierarchy**  
5. Health monitoring exists → **implement cron + Ops view**  
6. Legacy leakage detection exists → **health check + Ops highlight**  
7. No duplicate/identity issues in soak window → **monitor continuously**  
8. Campaign remains untouched → **constraint**  
9. No global automatic Hub for unapproved channels → **allowlist fail-closed + legacy default**  

Items 1–2 are satisfied today. Items 3–6 are the **implementation gap** E3 should close.

---

## 15. Campaign isolation (explicit)

E3 must not modify:

- `wa.campaign` / lines / templates / bulk queues  
- Campaign `_send_via_evolution`  
- Campaign bridge retry ownership  

Phase 5 remains a **separate** design after Discuss E3 operational standardization is stable.

---

## 16. Exact next execution task

**Task title:** Implement E3 Operational Standardization (no routing expansion)

**Authorized work:**

1. Docs: publish operator runbook (onboarding + rollback + soak thresholds) from this design.  
2. Code (minimal): Discuss Hub Ops act_window + computed allowlist/pending/shadow columns; health cron + admin activity on critical.  
3. Test on Test DB; upgrade only modules that carry the Ops/health bits.  
4. Production upgrade with flags/modes/allowlist **unchanged**.  
5. Verify cron dry-run / first health report clean for `{5,10}`.  

**Forbidden in that task unless separately authorized:** changing allowlist, flipping modes, Campaign edits, Phase 5.

---

## 17. Code change requirement summary

| Area | Code change in E3? |
|------|---------------------|
| Discuss routing / cutover / allowlist semantics | **No** (already sufficient) |
| Channel migration | **No** |
| Ops list + computed fields + health cron | **Yes** (small) |
| Quarantine | Already present |
| Campaign | **No** |

---

## Final recommendation

**`READY TO IMPLEMENT E3 OPERATIONAL STANDARDIZATION`**

Rationale: Current eligible Discuss inventory is **fully Hub-migrated** (`#5` + `#10`). There is **no** routing expansion left. E3 should standardize governance, future onboarding, monitoring, and lightweight admin/health tooling — not invent another cutover. Campaign stays out of scope.
