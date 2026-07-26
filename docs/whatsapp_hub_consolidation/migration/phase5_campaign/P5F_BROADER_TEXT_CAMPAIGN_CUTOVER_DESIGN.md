# P5F — Broader Production Text Campaign Hub Cutover — Design

**Date:** 2026-07-23  
**Status:** DESIGN ONLY — **no Production changes in this task**  
**Modules (baseline):** `whatsapp_hub` **19.0.1.9.0**, `evolution_whatsapp_chat` **19.0.1.18.0**  
**Final recommendation:** **`READY TO IMPLEMENT P5F BROADER TEXT CAMPAIGN GOVERNANCE`**

Baselines:

* P5E soak activation: [`P5E_LOW_VOLUME_CAMPAIGN_HUB_SOAK_ACTIVATION_REPORT.md`](./P5E_LOW_VOLUME_CAMPAIGN_HUB_SOAK_ACTIVATION_REPORT.md)
* P5E foundation: [`P5E_CAMPAIGN_HUB_SOAK_FOUNDATION_COMPLETION_REPORT.md`](./P5E_CAMPAIGN_HUB_SOAK_FOUNDATION_COMPLETION_REPORT.md)
* Inventory dump: `p5f_campaign_inventory.json`

---

## 0. Non-goals (this document)

* Do **not** activate broader Campaign Hub traffic.
* Do **not** change Production Campaign flags, allowlist, purposes, or Campaign modes.
* Do **not** modify Discuss routing, allowlist `10,5`, #5/#10, or Discuss health.
* Do **not** start P5G media.
* Do **not** implement scheduled Hub parity in this design task (plan only).

---

## 1. Production Campaign inventory

Inspected live Production `wa.campaign` on 2026-07-23. Control plane remains OFF (`cutover=False`, allowlist empty, purposes=`discuss`, batch=5, max_pending=20). Discuss #5/#10 hub, allowlist `10,5`.

### Summary

| Metric | Count |
|--------|------:|
| Total Campaigns | **18** |
| cancelled | 7 |
| completed | 5 |
| scheduled | 5 |
| draft | 1 |
| running / paused | 0 |
| `wa_outbound_mode=legacy` | 14 |
| `wa_outbound_mode=shadow` | 4 |
| `wa_outbound_mode=hub` | **0** |
| text-only (0 attachments) | **17** |
| with attachments | **1** |
| `send_mode=immediate` | 4 (all Hub-test Campaigns #16–19) |
| `send_mode=queue` | **14** (all real PetSpot + cancelled series + test draft) |
| `send_mode=scheduled` | **0** |
| rows with `scheduled_date` set | 13 |
| name looks test/internal | 5 |
| customer-facing candidates | 6 (#9 completed + #10–14 scheduled) |
| historical Hub usage | 3 (#17, #18, #19) |

`send_mode` selection in code: `immediate` | `scheduled` | `queue`.  
Real PetSpot marketing Campaigns use **`send_mode=queue`** + **`state=scheduled`** + `scheduled_date`, not `send_mode=scheduled`.

### Full inventory (relevant fields)

| ID | State | Mode | send_mode | Lines | Att | Notes |
|----|-------|------|-----------|------:|----:|-------|
| 2 | cancelled | legacy | queue | 751 | 0 | Weekly cycle W25 (cancelled) |
| 3–8 | cancelled | legacy | queue | 125–126 | 0 | W25 daily series (cancelled) |
| **9** | **completed** | legacy | queue | **126** | 0 | **Real customer** — all sent (legacy). `scheduled_date` 2026-06-20 |
| **10–14** | **scheduled** | legacy | queue | **125** each | 0 | **Real customer pending** — dates 2026-06-21…25; **still pending** (past due; never Hub) |
| 15 | draft | legacy | queue | 4 | **1** | TEST DRAFT + attachment — **not Hub eligible** |
| 16 | completed | shadow | immediate | 10 | 0 | P5C shadow |
| 17 | completed | shadow | immediate | 3 | 0 | P5D Hub pilot (historical Hub) |
| 18 | completed | shadow | immediate | 7 | 0 | P5E Soak A (historical Hub) |
| 19 | completed | shadow | immediate | 8 | 0 | P5E Soak B (historical Hub) |

### Operational reading

1. **Real Production Campaign pattern** is ~**125 unique customer phones**, text-only, **queue + scheduled_date**, not immediate Hub-test style.
2. Campaigns **#10–14** are orphaned/past-due scheduled queues (125 pending each). They are **not** safe Hub cutover targets as-is.
3. Only proven Hub Campaigns are dedicated test/soak (#17–19) to `201000059085`.
4. Media is rare today (1 draft test with attachment) but must stay fail-closed.
5. **No Campaign is currently Hub-mode.** Broader cutover starts from a clean OFF plane.

---

## 2. Eligibility policy (recommended)

A Campaign may use Hub **only if all** of the following hold:

| # | Rule | Rationale |
|---|------|-----------|
| E1 | `attachment_ids` empty (text-only) | Proven P5B–P5E; media = P5G |
| E2 | Valid Hub instance resolved (`sabry min` / instance #1 with Campaign cutover) | Existing gate |
| E3 | Every pending line has a non-empty normalized phone | Invalid dest → fail closed |
| E4 | Render freeze available; lines freeze before/at first Hub admission | P5E SoT |
| E5 | `wa_outbound_mode=hub` **and** Campaign ID on allowlist **and** global/instance Campaign cutover ON **and** purposes include `campaign` | Defense in depth |
| E6 | Supported orchestration: **manual Start/Resume** with Hub admission semantics | See §13 |
| E7 | Explicit human approval recorded (Ops / approval note) | Customer blast risk |
| E8 | Campaign health has **0 critical** immediately before flip | Continuous ops |
| E9 | Recipient count ≤ current volume-band max (F1/F2/…) | Staged expansion |
| E10 | **Not** depending on Hub-enforced `scheduled_date` until parity exists | Dominant real pattern gap |

### Optional / not required for first governance + first real pilot

| Item | Recommendation |
|------|----------------|
| Prior shadow evidence | **Recommended for first customer Campaign**; optional later once Hub is standing practice |
| Separate 3-line pilot per Campaign | **Not required** if F1 size ≤20 and freeze+health gates pass (P5D/P5E already proved transport) |
| Customer-facing extra approval | **Yes** — operator + (if available) business owner ack in notes |
| Scheduled mode on Hub | **Excluded** until P5F-E / scheduled parity |

### Practical policy statement

> **Hub Campaign = approved, allowlisted, text-only, freeze-ready, manually orchestrated Campaign within the active volume band. Default remains legacy. Scheduled/queue-timed and media stay legacy until dedicated parity.**

---

## 3. Tier classification (current Production)

### Tier A — Hub eligible **now** (after governance + control plane ON)

*None of the existing customer Campaigns.*

Technically eligible **templates** for a **new** Campaign:

* text-only, 0 attachments
* `send_mode=immediate` (or queue used only as “manual batch trigger,” not time semantics)
* recipient count within F1 (≤20)
* explicit approval + allowlist
* freeze before/at admit

Existing #16–19 are completed test/shadow — do **not** reuse for customer traffic.

### Tier B — Requires validation / dedicated pilot

| Campaign | Why Tier B |
|----------|------------|
| **New** real text Campaign cloned from #9-style content with **≤20** recipients, immediate orchestration | First customer-facing Hub use |
| Future weekly marketing drafts **if converted** to immediate Hub orchestration with staged volume | Size + customer impact |
| #9 (completed legacy) | Historical only — do not re-send; use as content/recipient **pattern** reference |

### Tier C — Not Hub eligible yet

| Campaign / class | Why |
|------------------|-----|
| **#10–14** scheduled queue, 125 pending, past `scheduled_date` | Scheduled/queue timing not Hub-enforced; large customer set; stale pending |
| **#2–8** cancelled | Dead |
| **#15** attachments | Media → P5G |
| Any Campaign with `send_mode=scheduled` or relying on `scheduled_date` for due-time | No Hub scheduled parity |
| Any Campaign with attachments/media | P5G |
| Accidental `wa_outbound_mode=hub` without allowlist | Fail-closed (and health critical if active) |

---

## 4. Broader-cutover scope — recommendation

### Options

| Option | Meaning |
|--------|---------|
| A | Hub only for individually approved Campaigns |
| B | Hub default for all text-only once plane ON |
| C | Hub standard for approved Campaigns; **every** Campaign still needs explicit allowlist |

### Recommendation: **Option C** (fail-closed)

* New Campaigns default **`legacy`**.
* Operator must: approve → allowlist → set `hub` **last**.
* No automatic “all text Campaigns go Hub.”
* Matches current architecture (`hub_cutover_prerequisites`) and PetSpot risk profile (125-recipient blasts).

Option B is rejected: too easy to route a large scheduled marketing Campaign accidentally.

---

## 5. Campaign control-plane operating model

### Options

| Model | Description |
|-------|-------------|
| 1 | Global + instance Campaign cutover **stay ON**; allowlist controls routing |
| 2 | Toggle Campaign cutover only during windows |
| 3 | Business-hours-only cutover |

### Recommendation: **Model 1** (standing capability + fail-closed allowlist)

Standing Production state after P5F governance activation (execution task — **not this design**):

```text
unified_outbound_enabled = True          # already (Discuss)
unified_outbound_purposes = discuss,campaign
campaign_cutover_enabled = True          # global
instance #1 campaign_cutover_enabled = True
campaign_hub_allowed_campaign_ids = <approved active IDs only>
new Campaign wa_outbound_mode = legacy   # default
```

**Why not Model 2/3:** P5E repeatedly toggling the whole plane is operationally heavy and error-prone for real weekly Campaigns. Allowlist + per-Campaign mode already prevent accidental Hub sends.

**Discuss impact:** none if Discuss flags/allowlist/#5/#10 untouched. Purposes become additive `discuss,campaign` (Discuss remains first).

**Accidental Hub send remains blocked unless all of:** plane ON + purposes include campaign + instance Campaign cutover + ID allowlisted + mode=`hub` + text-eligible + freeze/admit path.

---

## 6. Permanent allowlist recommendation

**Keep `whatsapp_hub.campaign_hub_allowed_campaign_ids` permanently** as the active-authorization set.

Semantics (critical — see §17):

> Allowlist = Campaigns **currently authorized to admit new Hub jobs**.  
> Not = “every historical Hub Campaign forever.”

After completion: **remove ID from allowlist**; set mode to `shadow` (preferred) or leave historical `hub` only if health rules ignore completed non-admitting Campaigns (prefer mode→shadow for clarity).

At PetSpot scale (~few Campaigns/week, IDs short-lived), CSV remains acceptable **with Ops helpers** (add/remove actions). Do not remove allowlist in favor of mode-only (mode alone is too weak against operator error).

---

## 7. CSV vs routing-policy model

| Approach | Verdict |
|----------|---------|
| CSV allowlist + Ops buttons | **Adopt for P5F-A** — smallest safe change |
| New `whatsapp.campaign.routing.approval` model | **Defer** unless Campaign creation volume grows or audit requires structured approval history |

If deferred model is needed later, fields would include: campaign_id, approved_by/at, instance_id, max_recipients, text_only, notes, revoked_at. Not justified at current inventory size (18 Campaigns, ~1 series/week).

**P5F-A minimum:** keep CSV; add Ops actions “Add to Hub allowlist” / “Remove from Hub allowlist” + optional chatter note for approval.

---

## 8. Approval / onboarding workflow

```text
1. Create Campaign (default legacy, text-only)
2. Load recipients / generate lines
3. Eligibility scan (Ops: attachments, send_mode, size band, phones)
4. Preview message (unfrozen)
5. Freeze lines (or freeze-on-first-admit)
6. Optional: shadow sample on a clone / subset (recommended for first customer Campaign)
7. Record approval (chatter / note)
8. Add Campaign ID to allowlist
9. Ensure control plane standing ON (Model 1)
10. Flip wa_outbound_mode legacy → hub LAST
11. Start → admit ≤ batch (5)
12. process_pending / health checkpoint
13. Continue batches if healthy
14. Complete Campaign
15. Remove ID from allowlist; set mode → shadow
16. Quarantine incomplete jobs only (sent preserved)
```

**Completed IDs:** remove from allowlist **manually (or Ops button) after completion** — prefer shrinking allowlist.

---

## 9. First real operational Campaign strategy

**Do not** Hub-cutover #10–14 as they sit today.

### Recommended first real Campaign

| Attribute | Value |
|-----------|-------|
| Type | **New** text-only immediate Campaign (content may reuse a low-risk template from #9-style messaging) |
| Recipients | **≤20** real customer phones (or staff+subset) — explicit business approval |
| Attachments | 0 |
| send_mode | **immediate** |
| batch | **5** |
| max_pending | **20** |
| Checkpoints | After first 5 sent; after complete |
| Rollback | mode→shadow, quarantine incomplete, remove allowlist |
| Shadow | Optional 3–5 line shadow clone first if content is new |

Success: same invariants as P5E (hash, no legacy, no dup, health green, Discuss green).

---

## 10. Volume expansion stages

| Stage | Recipients | Prerequisites | Batch / max_pending | Health | Exit |
|-------|------------|---------------|---------------------|--------|------|
| **F1** | ≤20 | Governance live; freeze; allowlist; plane ON | 5 / 20 | After 5 + final; 0 critical | 1 real Campaign 100% success |
| **F2** | ≤50 | F1 passed; no leakage/dups; Discuss healthy | 5 / 20 → consider 10 / 50 after evidence | Mid + final | ≥2 Campaigns clean |
| **F3** | ≤100 | F2 passed; fairness metrics clean | 10 / 50 | Every 25 admits or mid | ≥2 Campaigns clean |
| **F4** | Broader text (still allowlisted) | F3; Ops runbook; optional shadow skipped for repeats | 10–25 / 50–100 | Cron + Ops | Eligible text Campaigns use Hub by process |
| **Scheduled** | n/a | **P5F-E parity** | TBD | Separate | Not part of F1–F4 |

Current live series size (**125**) sits at **F3/F4 boundary** and is **scheduled/queue** → blocked until either (a) manual immediate subset, or (b) scheduled parity.

---

## 11. Backpressure tuning

Keep **5 / 20** until F1+F2 evidence.

| Next | When |
|------|------|
| 10 / 50 | After ≥2 real Campaigns ≤50 with 0 critical health, 0 starvation warnings, Discuss pending age always &lt;10m during Campaign |
| 25 / 100 | After F3 evidence; only if worker/provider stable and failure rate &lt;10% |

Do **not** restore 25/100 by default. Increases require explicit change + report note.

---

## 12. Queue fairness policy

* Campaign priority stays **3**; Discuss unchanged.
* Health already warns on Discuss starvation (`discuss_starvation_minutes=10`).
* P5E saw **zero** Discuss pending during soak.

### Recommendation for initial P5F

**Monitoring-only** automatic pause is **not** required for F1–F2.

**Operational guardrail:** if Discuss pending age &gt;10m **or** Campaign health warning `discuss_starvation`, operator **pauses Campaign admits** (pause Campaign / stop Start).

Revisit auto admission-stop after first real F2/F3 if starvation appears.

---

## 13. Supported send modes (P5F)

| Mode | Hub support | Policy |
|------|-------------|--------|
| **immediate** + manual Start/Resume | **Supported** | Primary Hub path |
| **queue** | **Conditional** | Allowed only when operator treats Start as “admit now to Hub queue” — **not** as legacy bridge rate-limit/schedule semantics. Prefer UI warning on Ops. |
| **scheduled** (`send_mode` or relying on `scheduled_date` for due time) | **Not supported** | Legacy only until P5F-E |

Hub always uses `whatsapp.outbound.message` unified bridge regardless of Campaign `send_mode`. UI must not imply scheduled due-time is honored on Hub.

---

## 14. Scheduled readiness plan

### Audit fact

Real PetSpot Campaigns (#10–14) are `state=scheduled`, `send_mode=queue`, with `scheduled_date`. Legacy path enqueues to `integration.outbound.queue` with `scheduled_at`. Hub path **does not** gate admission on `scheduled_date` (P5E warning already exists).

### When to implement parity

| Gate | Decision |
|------|----------|
| Before any P5F governance | **No** |
| Before first real ≤20 immediate Campaign | **No** |
| Before Hub-cutover of weekly 125 scheduled series | **Yes — blocker** |

### Slice: **P5F-E Scheduled parity** (design target)

```text
Campaign scheduled_date due
  → no Hub admit before due
  → at/after due: admit via existing batch/backpressure
  → or set outbound next_retry_at / scheduled field if introduced
```

Until then: scheduled Campaigns remain **legacy**.

---

## 15. Media exclusion

* Attachments/media → not Hub eligible (`text_eligible` / Ops `wa_hub_eligible`).
* mode=`hub` + media → block before admission; **no silent legacy fallback**.
* Legacy retains media path.
* P5G separate.

---

## 16. Render freeze operational UX

| Topic | Recommendation |
|-------|----------------|
| When freeze | Auto on first Hub admission via `get_frozen_or_freeze_body()` (already); optional explicit “Freeze all lines” Ops action before flip |
| Preview before freeze | Yes — preview uses freeze-or-render; prefer freeze-before-approve for customer Campaigns |
| Edit `campaign.message` after some lines frozen | Allowed for **authoring**; locked lines **unchanged**; new unfrozen lines use new template |
| Ops visibility | Show locked/unlocked counts on Campaign / Ops |
| Unlock / re-render | Admin-only; **only if** `hub_message_id` and `hub_outbound_id` empty **and** status pending |
| After Hub identity exists | **Never unlock**; never re-render that logical message |

---

## 17. Completed Campaign / allowlist cleanup

### Operating rule

1. On complete: remove Campaign ID from allowlist.
2. Set `wa_outbound_mode` → **`shadow`** (preferred historical marker) or `legacy`.
3. Quarantine only incomplete Hub jobs; preserve sent.

### Health semantics update (**required in P5F-A**)

Today `hub_not_allowlisted` flags **any** `wa_outbound_mode=hub` not on allowlist — conflicts with “shrink allowlist after complete” if mode left as `hub`.

**Required change:**

* Treat allowlist as **admission authorization**.
* `hub_not_allowlisted` critical only if Campaign is **admission-capable**:
  * mode=`hub` **and**
  * state in `running|paused|draft` with pending lines **or** active pending/processing Hub jobs for that Campaign
* Completed/cancelled Hub-mode without active jobs → **no critical** (info/ignore), especially after allowlist removal.
* Prefer Ops post-complete action: mode→shadow + remove allowlist (avoids ambiguity).

---

## 18. Health model updates for broader rollout

| Change | Priority |
|--------|----------|
| Active vs historical allowlist semantics (§17) | **P5F-A blocker** |
| Multiple simultaneous allowlisted Campaigns | Already OK; keep fail-closed per job |
| Pending volume thresholds | Keep; raise warn only with backpressure increases |
| Failure-rate window | Keep 24h ≥20% warning |
| Per-instance pending breakdown on health JSON | Nice-to-have |
| “Allowlisted but completed” hygiene warning | Optional warning to remove stale allowlist IDs |

---

## 19. Ops workflow

From **Campaign Hub Ops** (extend lightly in P5F-A):

| Action | Notes |
|--------|-------|
| Check eligibility | Show text/scheduled/size/allowlist/mode |
| Freeze lines | Optional pre-admit |
| Add / remove allowlist | Prefer over raw ICP edit |
| Activate Hub mode | Confirm eligibility; flip last |
| Pause / Resume / Quarantine | Existing |
| Remove allowlist after completion | One-click cleanup |

Direct CSV ICP edit remains emergency-only for system admins.

---

## 20. Continuous control-plane design

After governance activation (future execution):

```text
Discuss: unchanged (#5/#10 hub, allowlist 10,5)
purposes: discuss,campaign
campaign_cutover: True (global + instance #1)
allowlist: only active approved Campaign IDs
default new Campaign: legacy
Hub send requires: mode=hub ∩ allowlist ∩ text ∩ freeze ∩ plane
```

**Blast radius if operator sets mode=hub alone:** admission still fails (not allowlisted) → lines fail closed, no legacy fallback. Health alerts if left in bad state.

**Blast radius if allowlist wrong ID:** only that Campaign; quarantine + remove.

---

## 21. Rollback hierarchy

### One Campaign

1. Pause  
2. mode → shadow/legacy  
3. `service_quarantine_campaign`  
4. Remove from allowlist  
5. Never legacy-resend provider-accepted lines  

### Instance Campaign plane

1. Stop new admits (pause Hub Campaigns / clear allowlist)  
2. Quarantine active Campaign Hub jobs  
3. instance `campaign_cutover_enabled=False`  

### Entire Campaign Hub

1. Active Hub Campaigns → shadow  
2. Quarantine incomplete Campaign jobs  
3. Allowlist empty  
4. Global + instance Campaign cutover False  
5. purposes → `discuss` (optional but recommended for full OFF)  
6. Discuss untouched  

---

## 22. Legacy transport strategy

| Path | Use |
|------|-----|
| Hub | Approved eligible text Campaigns |
| Legacy `_send_via_evolution` / bridge queue | Non-approved, media, scheduled until parity, shadow observational sends |
| Deprecation | **Not in P5F** — candidate **P5H** only after F4 + scheduled parity + sustained clean health |

---

## 23. Delivery / read limitations

Current Hub Campaign “Sent” = **provider acceptance** → outbound `sent` → line `sent`.

Delivered/read are separate (webhook enrichment) and **not** a P5F blocker if UI/docs state:

> Campaign line **Sent** means WhatsApp provider accepted the message, not that the customer has opened it.

Recommend Ops/help text update in P5F-A (copy only).

---

## 24. Retry / failure policy

| Topic | Policy |
|-------|--------|
| Natural Hub retries | Acceptable within existing outbound retry; monitor retry_count |
| Failure-rate pause | Manual pause if health warning elevated failure ≥20% or any critical |
| Retry failed line | Existing `action_retry_failed` / `_hub_retry_allowed` — **no** retry if provider-accepted |
| Legacy resend of accepted Hub line | **Forbidden** |
| UX sufficiency for F1–F2 | **Yes** with Ops + health; revisit auto-pause later |

---

## 25. First P5F Production pilot design (do not execute here)

| Item | Spec |
|------|------|
| Cohort | New immediate text Campaign; ≤20 approved real recipients |
| Content | Low-risk operational/marketing text; 0 attachments |
| Plane | Model 1 ON for window or standing after P5F-A |
| Allowlist | Only that Campaign ID |
| Mode | legacy → hub last |
| Batch / max | 5 / 20 |
| Runs | Admit 5 → send → health → remaining → health |
| Success | 100% provider accept; hash 100%; 0 legacy/bridge/dup; Campaign+Discuss healthy |
| Rollback | §21 one-Campaign |
| After | mode→shadow; remove allowlist; keep plane per Model 1 decision |

---

## 26. P5F implementation slices

| Slice | Scope |
|-------|-------|
| **P5F-A** | Governance: allowlist lifecycle semantics in health; Ops add/remove allowlist; eligibility/scheduled warnings; freeze counts UX; Sent=accepted wording; standing control-plane runbook; tests |
| **P5F-B** | First real ≤20-recipient immediate text Campaign activation (execution) |
| **P5F-C** | Small text Campaigns ≤50 + optional batch 10/50 |
| **P5F-D** | Medium ≤100 / path toward weekly size with manual orchestration |
| **P5F-E** | Scheduled/queue due-time Hub parity (required before #10–14-style cutover) |
| **P5G** | Media (separate) |
| **P5H** | Legacy deprecation criteria (future) |

---

## 27. Blockers vs non-blockers

### Blockers to first real text Campaign (≤20 immediate)

* P5F-A health allowlist lifecycle fix (avoid false criticals / unsafe completed-hub semantics)
* Explicit customer approval + allowlist discipline
* Control plane Model 1 activation procedure
* Freeze + text-only gates (already exist)

### Blockers to continuous text Campaign operation

* Standing Model 1 + Ops allowlist hygiene
* Documented rollback
* Cron health clean under multi-Campaign allowlist

### Blockers to scheduled Campaigns (#10–14 pattern)

* **Hub scheduled/due-time parity (P5F-E)**
* Decision on stale past-due #10–14 (cancel vs legacy drain vs rebuild)

### Blockers to media

* Entire **P5G**

### Can wait

* Approval ORM model
* Auto Discuss-starvation admission stop
* Delivery/read Campaign projection
* Raising batch beyond 5/20
* Legacy deprecation

---

## 28. P5F completion criteria

Broader text Campaign Hub cutover is **complete** when:

1. Eligible **immediate** text Campaigns follow Hub by standard Ops process (approve → allowlist → hub last).
2. Allowlist shrinks after completion; health has 0 false criticals for historical Hub.
3. ≥1 real F1 and ≥1 F2 Campaign passed with P5E-class invariants.
4. Discuss remains healthy and unchanged in routing.
5. Legacy retained for unapproved / scheduled / media.
6. Rollback hierarchy rehearsed at least once on a real (or staged) Campaign.
7. Scheduled series still explicitly **out of scope** until P5F-E (documented).

---

## 29. Exact next implementation task

**Implement P5F-A — Broader Text Campaign Governance** (code + Test + Production upgrade with Campaign Hub **still fail-closed / or standing Model 1 OFF until explicit activate**):

1. Health: allowlist = admission authorization; do not critical completed Hub Campaigns merely missing from allowlist.
2. Ops: add/remove allowlist actions; locked/unlocked counts; eligibility clarity for scheduled/media.
3. Docs/runbook: Model 1 standing state; approval workflow; first F1 pilot checklist.
4. Automated tests for new health semantics + Ops helpers.
5. Production deploy **without** auto-activating first customer Campaign.

Then a **separate explicit activation task** for P5F-B (first ≤20 real Campaign).

---

## 30. Discuss remains unchanged

| Check | Design constraint |
|-------|-------------------|
| #5 / #10 modes | Must remain `hub` |
| Discuss allowlist | Must remain `10,5` |
| Discuss health | Must remain independently healthy |
| Discuss cutover / flags | Not modified by Campaign Ops |
| Campaign quarantine | purpose=`campaign` only |

---

## Final recommendation

**`READY TO IMPLEMENT P5F BROADER TEXT CAMPAIGN GOVERNANCE`**

Not ready to activate the first real customer Campaign in the same breath: live Production demand is **125-recipient scheduled/queue** series (#10–14), which are **Tier C** until either a new ≤20 immediate pilot (P5F-B) or scheduled parity (P5F-E). Governance/health allowlist lifecycle (P5F-A) must land first.

Do **not** start P5G. Do **not** change Production in this design task.
