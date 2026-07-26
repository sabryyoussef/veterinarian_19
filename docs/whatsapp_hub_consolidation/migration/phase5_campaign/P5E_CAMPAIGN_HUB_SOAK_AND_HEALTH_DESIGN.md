# P5E — Campaign Hub Low-Volume Soak, Health Monitoring, and Operational Hardening

**Date:** 2026-07-23  
**Status:** DESIGN ONLY — **no Production changes in this task**  
**Modules (baseline):** `whatsapp_hub` **19.0.1.8.0**, `evolution_whatsapp_chat` **19.0.1.17.0**  
**Decision:** **`READY TO IMPLEMENT P5E CAMPAIGN HUB SOAK FOUNDATION`**

Baselines:

- Phase 5 design: [`PHASE5_CAMPAIGN_HUB_MIGRATION_DESIGN.md`](./PHASE5_CAMPAIGN_HUB_MIGRATION_DESIGN.md)
- P5D activation: [`P5D_CONTROLLED_CAMPAIGN_HUB_PILOT_ACTIVATION_REPORT.md`](./P5D_CONTROLLED_CAMPAIGN_HUB_PILOT_ACTIVATION_REPORT.md)
- P5D design: [`P5D_CONTROLLED_CAMPAIGN_HUB_PILOT_DESIGN.md`](./P5D_CONTROLLED_CAMPAIGN_HUB_PILOT_DESIGN.md)
- Discuss health pattern: E3 / `whatsapp.discuss.hub.health`

---

## 0. Non-goals (this document)

- Do **not** enable Campaign Hub cutover / allowlist / purposes in Production.
- Do **not** modify Discuss routing, allowlist `10,5`, #5/#10 modes, or E3 Discuss health.
- Do **not** start broader text Campaign cutover (P5F).
- Do **not** implement media / Meta templates (P5G).
- Do **not** implement scheduled Hub Campaign parity as part of soak activation.
- Do **not** auto-rollback from health cron.

---

## 1. Rendering pipeline audit

### Code fact (root cause of P5D PLACEHOLDER)

`wa.campaign._render_message_for_line(line)` **always** starts from **`self.message`** (Campaign-level), then optionally personalizes placeholders when `personalise=True`:

```text
body = self.message or ''
if personalise: replace {name}/{first}/{company}/{phone}
return body
```

It **never reads** `line.message` as input.

Every processor path then does:

```text
rendered = _render_message_for_line(line)
line.message = rendered   # overwrite
… send/admit with rendered …
```

So any pre-populated per-line body (P5D Pilot 01/02/03) is discarded at process time.

### Comparison table

| Path | Source of body | When rendered | Persisted where | Personalization |
|------|----------------|---------------|-----------------|-----------------|
| **Legacy immediate** | `campaign.message` via `_render_message_for_line` | At process/send time | Overwrites `line.message`; passed to `_send_via_evolution` | If `personalise` |
| **Legacy queue/scheduled** | Same | At enqueue time | Overwrites `line.message`; payload text in `integration.outbound.queue` | If `personalise` |
| **Shadow preview** | Same render, then `service_preview_campaign_line(..., body=rendered)` | At shadow process time | Preview JSON + shadow evidence; line.message overwritten; legacy send uses rendered | If `personalise` |
| **Hub P5B path** | Same render, then `service_admit_campaign_line(..., body=rendered)` | At Hub admission | Overwrites `line.message`; Hub message/job `body` frozen at admit | If `personalise` |

### Implications

* Hub **retry** already uses the frozen outbound job `body` (good — once admitted).
* **Re-admission** path for broken refs re-calls `_render_message_for_line` again → can diverge if Campaign template changed.
* Preview/shadow and Hub admit currently agree **with each other** only because both re-render from Campaign message at that moment — they do **not** honor a manually edited line body.
* Changing `campaign.message` mid-flight can change not-yet-admitted lines; already-admitted Hub jobs keep prior body.

### Source-of-truth recommendation

**C — Hybrid with explicit rendered snapshot (freeze-before-admit)**

Rule:

> The exact message previewed/approved for a Campaign line must equal the exact text sent by Hub.  
> Do not silently recompute a different body later.

Operational model:

1. **Authoring source** remains Campaign-level `message` (+ `personalise` placeholders).  
2. Before Hub eligibility / admission, **freeze** a per-line immutable snapshot.  
3. Hub preview, admit, retry, and health compare against that snapshot only.  
4. Changing Campaign template after freeze must **not** mutate admitted logical messages.

---

## 2. Rendered-content identity and immutability

### Recommended fields on `wa.campaign.line`

| Field | Type | Purpose |
|-------|------|---------|
| `rendered_body` | Text | Immutable snapshot used for Hub admit/send |
| `rendered_body_hash` | Char(64) | SHA256 of stripped body (compare/health) |
| `rendered_at` | Datetime | When snapshot was frozen |
| `rendered_locked` | Boolean | True after freeze; blocks re-render |

Reuse of existing `line.message`:

* Keep `message` as the operator-visible personalised text.  
* On freeze: set `message = rendered_body` (same content) for UX continuity.  
* Hub path must call admit with **`body=line.rendered_body`** (or locked `message`), **not** a fresh `_render_message_for_line`.

### Freeze API (conceptual)

`whatsapp.campaign.hub.routing.service_freeze_campaign_line(campaign, line)` or Campaign method:

1. If `rendered_locked` and hash present → no-op (idempotent).  
2. Else `body = _render_message_for_line(line)` once.  
3. Write `rendered_body`, `rendered_body_hash`, `rendered_at`, `rendered_locked=True`, `message=body`.  
4. Return body.

### Hub path change (mandatory semantics)

```text
freeze if not locked
preview/admit using frozen body only
never re-render for Hub-linked or locked lines
```

### Classification

| Item | Timing |
|------|--------|
| Freeze fields + Hub/shadow use frozen body | **Mandatory before P5E Production soak activation** |
| Health check: line hash vs Hub message body | Required with health service (same P5E foundation) |
| UI “re-freeze” for draft lines only | Nice-to-have; can wait until Ops polish |
| Backfill historical lines | Not required for soak |

**Verdict:** rendering fix is a **P5E foundation blocker**, not deferrable to P5F.

---

## 3. P5E soak purpose

Validate sustained Campaign Hub behavior beyond the 3-line P5D pilot:

* freeze/render correctness under multiple processor runs  
* admission batching + backpressure  
* projection + compat convergence at modest volume  
* Campaign health visibility without Discuss interference  
* pause/resume/cancel ops  

### Recommended evidence target (smallest meaningful)

| Metric | Target |
|--------|--------|
| Successful Hub Campaign lines | **15** (range 10–25) |
| Distinct soak Campaigns | **2** short-lived test Campaigns (e.g. 7 + 8 lines) |
| Processor runs | ≥ **3** separate Start/Resume cycles |
| Duplicate sends | **0** |
| Legacy leakage on Hub Campaigns | **0** |
| Dual queue (`integration.outbound.queue` for Hub lines) | **0** |
| Jobs outside allowlist | **0** |
| Discuss health | remains **healthy** |
| Render hash agreement | **100%** of soak lines |

Recipients: controlled/test DMs only (reuse `201000059085` pattern). No customer bulk.

---

## 4. Soak Campaign strategy

| Option | Description | Verdict |
|--------|-------------|---------|
| A | Permanent dedicated Hub soak Campaign | Optional later; not first |
| B | Fresh short-lived test Campaigns per batch | **Select for early P5E** |
| C | One real low-risk operational Campaign | **Defer** until after B soak + health green |

**Staged approach:**

1. **P5E-B:** implement foundation (render freeze + health + Ops + conservative ICP).  
2. **P5E soak activation (separate task):** 2× Option B test Campaigns, Option B restore after each (Campaign control plane OFF) unless explicitly keeping soak ON.  
3. **P5E-C (optional):** only after soak evidence, consider one carefully allowlisted real text Campaign — still not bulk.

Do **not** approve customer bulk Campaigns in P5E.

---

## 5. Activation control model (Campaign plane only)

During an approved soak window:

| Control | Value |
|---------|-------|
| Discuss flags / allowlist / #5/#10 | **unchanged** |
| `unified_outbound_purposes` | `discuss,campaign` (additive) |
| `campaign_cutover_enabled` | True |
| Instance #1 `campaign_cutover_enabled` | True |
| `campaign_hub_allowed_campaign_ids` | **only** approved soak Campaign ID(s) |
| Soak Campaign `wa_outbound_mode` | `hub` (flip **last**) |
| All other Campaigns | `legacy` or `shadow` |
| `campaign_admit_batch_size` | conservative (see §12) |
| `max_pending_campaign_jobs` | conservative (see §12) |

Allowlist remains **fail-closed**. Empty allowlist ⇒ no Hub Campaign admits.

**Default after each early soak Campaign:** restore Campaign plane OFF (same as P5D Option B), unless product explicitly chooses a soak-on window with health cron already live.

---

## 6. Campaign health service design

Keep `whatsapp.discuss.hub.health` **Discuss-only**.

### New model

`whatsapp.campaign.hub.health` (singleton + mail.activity mixin), parallel to Discuss health.

### Checks (minimum)

| # | Check |
|---|--------|
| 1 | Hub-mode Campaign is allowlisted |
| 2 | Allowlisted Campaign ID exists / active |
| 3 | `purpose=campaign` Hub job with `campaign_id` outside allowlist |
| 4 | Stale pending/processing Campaign job > threshold |
| 5 | Duplicate Campaign `business_key` |
| 6 | Duplicate provider / `evolution_message_id` among Campaign jobs |
| 7 | Hub-mode Campaign legacy leakage (`_send_via_evolution` / bridge queue / `send_origin=legacy` for that campaign) |
| 8 | Line `sent` but Hub outbound not `sent` |
| 9 | Hub outbound `sent` but line not projected `sent` |
| 10 | Missing/inconsistent `hub_message_id` / `hub_outbound_id` |
| 11 | Compat log missing / wrong `hub_message_id` / wrong provenance |
| 12 | `walog:*` twin for Hub-first Campaign business key |
| 13 | Campaign pending volume above threshold |
| 14 | Backpressure active longer than threshold |
| 15 | Discuss starvation signal (Campaign pending high while Discuss pending aged) |
| 16 | Rendered-body/hash mismatch: line snapshot ≠ Hub message body |

**Never** from health cron: send, retry, quarantine, mode/flag/allowlist mutation.

---

## 7. Health severity and thresholds

### Critical

* Hub Campaign not allowlisted  
* Campaign job outside allowlist  
* Duplicate provider send / duplicate business key  
* Legacy leakage on Hub Campaign  
* Lifecycle divergence after provider acceptance (Hub sent ↔ line not sent, or reverse with Hub refs)  
* Rendered payload mismatch (locked hash ≠ Hub body hash)  
* Stuck `processing` without provider ID > **15 minutes**  

### Warning

* Pending/processing age > **30 minutes** but < critical stuck rule  
* Pending Campaign jobs ≥ **15** (soft) / ≥ max_pending (hard warning)  
* Backpressure active > **2 consecutive health runs**  
* Compat metadata gap (log missing but Hub sent) without twin  
* Failure rate in last 24h ≥ **20%** of Campaign Hub attempts  
* Discuss oldest pending > **10 minutes** while Campaign pending > 0 (starvation watch)

### Practical ICP defaults (design)

| ICP | Suggested default |
|-----|-------------------|
| `whatsapp_hub.campaign_health_stale_minutes` | 30 |
| `whatsapp_hub.campaign_health_stuck_processing_minutes` | 15 |
| `whatsapp_hub.campaign_health_pending_warn` | 15 |
| `whatsapp_hub.discuss_starvation_minutes` | 10 |

---

## 8. Health cron design

| Item | Recommendation |
|------|----------------|
| Frequency | **Every 30 minutes** |
| Rationale | Campaign traffic is bursty; hourly is slow for stuck processing; 15m is noisier during drafts. 30m matches Discuss E3 cadence family without overlapping identity. |
| Behavior | Read-only detection + optional admin activity |
| Activities | Deduped by issue fingerprint; summary prefix **`Campaign Hub Health CRITICAL`** (never “Discuss Hub Health”) |
| Separation | Separate model, menu, cron XML id |

---

## 9. Campaign Hub Ops view

Lightweight admin surface: **Campaign Hub Ops** (list on `wa.campaign` with Hub annotations, or dedicated transient/computed model).

### Columns (per Campaign)

* name / state / `wa_outbound_mode`  
* allowlisted?  
* Hub instance ref  
* total / pending / sent / failed lines  
* Hub jobs / pending Hub / failed Hub  
* last Hub send  
* recent max retry_count  
* legacy leakage count  
* health badge  
* rendering warning (unlocked lines / hash mismatch)  
* attachment/media eligibility warning  

### Drill-downs

Campaign lines · Hub outbound jobs · canonical messages · `wa.message.log` · shadow evidence · **Quarantine Campaign** action (manager-only; not from cron).

No heavy analytics dashboard.

---

## 10. Queue fairness and starvation

### Current worker facts

* Outbound model `_order = priority desc, id asc`  
* Discuss jobs typically priority **5** (default)  
* Campaign Hub jobs priority **3**  
* Cron: `process_pending(50)` every **5 minutes**  

⇒ Discuss already outranks Campaign in the shared Hub worker. Good baseline.

### Metrics to expose (health + Ops)

* oldest pending Discuss job age  
* oldest pending Campaign job age  
* pending counts by purpose  
* Campaign share of last N processed jobs  
* per-instance queue depth  

### Starvation rule (P5E)

**Monitoring + admission backpressure first** — no complex scheduler rewrite.

Rule for Ops/health **warning**:

> If any `purpose=discuss` job is pending > `discuss_starvation_minutes` **and** Campaign pending > 0 → warn “Campaign may compete; verify Discuss drain”.

Optional **soft admission pause** (code, still P5E-optional):

> While Discuss pending age > threshold, `service_admit_campaign_line` / Hub processor refuses new admits with backpressure error (remaining lines stay pending).

Prefer implementing as health warning + documented operator pause in first soak; add automatic admit-stop only if soak shows real Discuss aging.

---

## 11. Backpressure recommendations

Current Production defaults: batch **25**, max pending **100** — too high for first soak.

### P5E soak recommendations

| ICP | Soak value | Notes |
|-----|------------|-------|
| `campaign_admit_batch_size` | **5** | Small observable batches |
| `max_pending_campaign_jobs` | **20** | Fail closed early |
| Per-instance | Use existing pending count scoped by instance in `backpressure_ok` | Already instance-aware in routing |

Behavior (already largely implemented):

* admission stops cleanly on backpressure  
* remaining lines stay `pending`  
* resume continues; Hub-linked lines reuse jobs (idempotent)  
* Discuss jobs untouched  

Restore to 25/100 only after P5F readiness, not automatically after each soak.

---

## 12. Campaign soak lifecycle

```text
1. Create soak Campaign (legacy), text-only, controlled recipients
2. Validate eligibility (no attachments)
3. Freeze rendered snapshots for all lines (mandatory)
4. Verify preview body == frozen body
5. Set batch=5, max_pending=20
6. purposes → discuss,campaign
7. Campaign cutovers ON (global + instance #1)
8. Allowlist = soak Campaign id only
9. Flip Campaign → hub LAST
10. Admit small batch (Start/Resume)
11. Let Hub cron/_send_one process; verify health
12. Continue next batch only if Campaign+Discuss health clean
13. Complete Campaign
14. Capture evidence matrix
15. Default: Option B restore (Campaign plane OFF; pilot→shadow)
```

---

## 13. Pause / resume / cancel (operational model)

| Action | Behavior |
|--------|----------|
| **Pause** | `state=paused`; Hub processor stops new admits; already-admitted Hub jobs continue via Hub cron |
| **Resume** | `state=running`; continue unadmitted pending; reuse Hub-linked jobs; **do not re-render locked lines** |
| **Cancel** | stop admissions; `service_quarantine_campaign`; preserve provider-accepted; **never** legacy-resend accepted lines |

### UAT scenarios (Test)

1. Pause mid-batch: no new admits; in-flight Hub send completes.  
2. Resume: remaining pending admit without duplicate business keys.  
3. Cancel with mixed pending+sent: sent preserved; pending quarantined.  

---

## 14. Retry / failure thresholds

* **Do not** inject provider failure in Production unless explicitly authorized.  
* Use **Test** for failure injection (temp fail → retry; permanent → line failed).  

### Production soak observation thresholds

| Signal | Action |
|--------|--------|
| Natural temp retry, resolves | Continue; note in evidence |
| Permanent fail rate ≥ 20% of batch | Pause Campaign; investigate |
| Stuck processing uncertain > 15m | Campaign-only quarantine of that job; health critical |
| Any duplicate provider / business key | Immediate Campaign-only rollback |
| Discuss health critical | Systemic Campaign rollback (preserve Discuss) |

---

## 15. Scheduled Campaign readiness

### Code fact

* `send_mode=scheduled` only sets `scheduled_at` on **legacy** `integration.outbound.queue`.  
* Hub path admits when `_process_campaign_queue_hub` runs; it does **not** honor `scheduled_date` as a Hub delay.  

### Decision

**P5E soak = manual / immediate orchestration only.**

Scheduled Hub parity = **separate readiness gate before P5F** (or explicit P5E.1), not part of low-volume soak.

Ops: if Campaign is Hub + `send_mode=scheduled`, show warning “Scheduled time not applied on Hub path — use manual start”.

---

## 16. Media / attachments exclusion

* Hub remains **text-only** (`text_eligible` / empty `attachment_ids`).  
* Hub mode + attachments → prerequisites fail → lines fail; **no silent legacy fallback**.  
* Legacy Campaigns keep existing attachment behavior.  
* Ops badge: `Not Hub eligible: attachments/media`.

---

## 17. Delivery / read limitations

* Campaign line `delivered` / `read` projection is not fully wired end-to-end for Hub.  
* **Not a P5E soak blocker.**  
* Success definition for soak: provider acceptance ⇒ Hub outbound `sent` ⇒ line `sent`.  
* Delivery/read remain later enrichment (document in Ops as reporting limitation).

---

## 18. Test / UAT design (before Production soak)

### Rendering

* personalized freeze snapshot  
* preview body == frozen body  
* admit body == frozen body == Hub message body  
* retry uses same outbound body  
* Campaign template change after lock does not change Hub job body  
* pre-written `line.message` without freeze must not be silently preferred **unless** freeze copies it by explicit policy (recommended: freeze always from `_render_message_for_line` **or** optional “use line.message if set & unlocked” — prefer Campaign template as authoring source, freeze once)

### Health

* healthy allowlisted Hub Campaign  
* Hub Campaign not allowlisted → critical  
* stale job → warning/critical by age  
* lifecycle divergence → critical  
* legacy leakage → critical  
* rendered-body mismatch → critical  
* activity fingerprint dedupe  

### Queue

* batch size 5  
* max pending 20 stops admits  
* Discuss priority still drains first (`priority desc`)  
* no Campaign-created Discuss regressions  

### Lifecycle

* pause / resume / cancel+quarantine  
* idempotent continuation  

---

## 19. Production soak evidence requirements

Per soak Campaign:

* Campaign ID/name, line count, approved recipients  
* freeze hashes (sample or all)  
* Hub messages / jobs / provider IDs  
* sent/failed/pending counters  
* retries, duplicates, legacy leakage, bridge queue delta  
* render hash agreement rate  
* Campaign health last_status + fingerprint  
* Discuss health last_status  
* allowlist contents during soak  
* post-soak control plane state  

---

## 20. P5E success criteria

1. Rendering source-of-truth fixed (freeze) and proven.  
2. Preview/frozen snapshot equals Hub message body for soak lines.  
3. ≥ **15** successful Hub Campaign lines (or documented 10+ with zero defects).  
4. Zero duplicate sends.  
5. Zero legacy leakage.  
6. Zero jobs outside allowlist.  
7. Zero dual-queue behavior for Hub lines.  
8. Lifecycle projection correct.  
9. Campaign counters correct.  
10. Health detects synthetic Test anomalies.  
11. Production Campaign health clean during/after soak.  
12. Discuss remains healthy.  
13. Backpressure works at soak ICP values.  
14. No meaningful Discuss starvation.  
15. Pause/resume/cancel operational.  
16. Non-approved Campaigns remain legacy/shadow.  
17. Media Campaigns excluded from Hub.

---

## 21. P5F readiness gate

Broader text Campaign cutover requires:

* P5E soak **PASSED**  
* Campaign health cron operational in Production  
* rendering freeze correctness fixed  
* queue fairness acceptable (Discuss not starved)  
* **scheduled Hub semantics decision implemented or explicitly deferred with Ops block**  
* rollback proven (Campaign-only + systemic)  
* text-only eligibility enforced  

Media **not** required for text-only P5F (media = P5G).

---

## 22. Minimum implementation recommendation

### Required before any P5E Production soak

1. **Rendering freeze** on `wa.campaign.line` + Hub/shadow/admit use frozen body  
2. Tests for freeze immutability / preview=admit=send  
3. Conservative ICP defaults documented (batch 5 / max 20) — applied only at soak activation  

### Required to call P5E “foundation complete” (may land same implementation task)

4. `whatsapp.campaign.hub.health` model + service checks  
5. Campaign health cron (30m)  
6. Campaign Hub Ops list + quarantine drill-down  
7. Health tests (allowlist, leakage, mismatch, divergence, dedupe)  

### During soak (activation task, not this design)

8. Apply control plane + allowlist + freeze + run soak batches  
9. Evidence report + default Option B restore  

### Can wait until P5F

* Automatic admit-stop on Discuss starvation  
* Scheduled Hub parity  
* Permanent soak Campaign (Option A)  
* Real operational Campaign (Option C)  

### Can wait until P5G

* Media / attachments Hub transport  
* Delivery/read projection expansion  

---

## Exact next implementation task

**Implement P5E Campaign Hub Soak Foundation only:**

1. Add line freeze fields + freeze service; change Hub + shadow processors to use frozen body (no silent re-render after lock).  
2. Add `whatsapp.campaign.hub.health` + 30-minute cron + fingerprint activities.  
3. Add Campaign Hub Ops view (lightweight).  
4. Add automated tests for rendering freeze + health anomaly detection + backpressure/pause-resume regressions.  
5. **Do not** enable Production Campaign flags/allowlist/purposes.  
6. **Do not** start Production soak in the foundation task (soak = separate activation after foundation green on Test).

---

## Final Production configuration matrix (unchanged by this design)

| Control | Must remain |
|---------|-------------|
| Campaign cutover | False |
| Allowlist | empty |
| Instance Campaign cutover | False |
| purposes | `discuss` |
| #5 / #10 | hub |
| Discuss allowlist | `10,5` |
| Discuss health | healthy |

---

## Final recommendation

**`READY TO IMPLEMENT P5E CAMPAIGN HUB SOAK FOUNDATION`**

Not ready to activate Production soak until the rendering freeze lands and Test UAT for freeze+health is green.  
Not ready for P5F.  
This design does **not** activate Campaign Hub or modify Discuss.
