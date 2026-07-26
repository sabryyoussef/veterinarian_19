# P5D — Controlled Production Campaign Hub Pilot Design

**Date:** 2026-07-23  
**Status:** DESIGN ONLY — **no Production changes in this task**  
**Modules (baseline):** `whatsapp_hub` **19.0.1.8.0**, `evolution_whatsapp_chat` **19.0.1.17.0**  
**Decision:** **`READY TO ACTIVATE P5D CONTROLLED CAMPAIGN HUB PILOT`**  
(activation is a **separate explicit task** — this document must not flip flags, allowlist, purposes, or send)

Baselines:

- Phase 5 design: [`PHASE5_CAMPAIGN_HUB_MIGRATION_DESIGN.md`](./PHASE5_CAMPAIGN_HUB_MIGRATION_DESIGN.md)
- P5B adapter: [`P5B_CAMPAIGN_HUB_ADAPTER_COMPLETION_REPORT.md`](./P5B_CAMPAIGN_HUB_ADAPTER_COMPLETION_REPORT.md)
- P5C shadow: [`P5C_CONTROLLED_CAMPAIGN_SHADOW_COMPLETION_REPORT.md`](./P5C_CONTROLLED_CAMPAIGN_SHADOW_COMPLETION_REPORT.md)

---

## 0. Non-goals (this document)

- Do **not** enable Campaign Hub cutover / instance Campaign cutover.
- Do **not** add Campaign #16 (or any Campaign) to `campaign_hub_allowed_campaign_ids`.
- Do **not** add `campaign` to `unified_outbound_purposes`.
- Do **not** change Discuss routing, allowlist `10,5`, #5/#10 modes, or health.
- Do **not** send WhatsApp messages.
- Do **not** start P5E (health cron / soak / media / scheduled parity).

---

## 1. Recommended pilot Campaign choice

### Decision: **B — Create a fresh dedicated P5D pilot Campaign**

| Option | Verdict |
|--------|---------|
| A — Reuse Campaign **#16** (`P5C Controlled Campaign Shadow (PROD)`) | **Reject** for Hub pilot |
| B — New dedicated P5D Campaign | **Select** |

### Why not #16

* #16 has **10** shadow lines, P5C shadow evidence (including `legacy_send_completed` / `replay_skipped`), and synthetic partners from a **mocked** provider path.
* Mixing Hub-first `campaign:{id}:{line}` identity with prior shadow/legacy observational history muddies lineage and counters.
* #16 should remain `shadow` (or later restored to `legacy`) as a P5C artifact — not flipped to Hub.

### Pilot Campaign specification (to create at activation time)

| Field | Value |
|-------|--------|
| Name | `P5D Controlled Campaign Hub Pilot (PROD)` |
| `wa_outbound_mode` | create as **`legacy`**, flip to **`hub` last** (after flags/allowlist) |
| `send_mode` | **`immediate`** (Hub path ignores legacy send_mode for transport; keep immediate for operational clarity) |
| Lines | **exactly 3** |
| Attachments | **none** |
| Bodies | `Campaign Hub Pilot 01` / `02` / `03` (plain text; no templates/buttons/media) |
| Recipients | dedicated controlled test DMs only (see §2) |

**Recommended Campaign choice:** fresh dedicated P5D Campaign with **exactly 3 text-only lines**.

---

## 2. Real-send destination strategy

### Policy

P5D **requires real Evolution provider acceptance**.  
Mocked `_send_via_evolution` / mocked Hub transport is **not** acceptable for final P5D success.

P5C Production evidence proved candidate/legacy equivalence and Hub-zero guarantees, **not** live Evolution acceptance for Campaign. P5D closes that gap via Hub → bridge one-shot → real provider ID.

### Recommended destinations

Use **DM-only** E.164 phones on instance **`sabry min`** (Hub instance #1 / Evolution Clinic instance).

| Priority | Destination | Notes |
|----------|-------------|-------|
| **Primary** | `201000059085` (partner **#469** — Sabry Bridge Test DM; proven on Discuss #5 Hub) | Safest known controlled number |
| Line strategy | **3 lines → same approved test DM** via 3 partner rows that share `phone=201000059085` (or one partner + two clones) | Avoids accidental bulk; bodies still unique (`Pilot 01..03`) |
| Alternate | Additional operator-approved personal/test DMs only | Must be explicitly listed in activation T0 before send |
| **Not for P5D** | Customer CRM lists, Meta templates, media | Forbidden |
| **Not for P5D** | Group JID (e.g. Discuss #10 group) | Hub Campaign candidate currently normalizes digits → `@s.whatsapp.net`; group `@g.us` is **unsafe** until Campaign JID normalization is fixed (out of P5D scope) |

### Instance

* One Evolution instance only: **`sabry min`**
* Hub resolve: purpose=`campaign` instance if present, else default (`is_default`) — Production today uses instance #1 `sabry min` as default; ensure that instance has `unified_outbound_enabled=True` and (at activation) `campaign_cutover_enabled=True`

### If real send is not safe/available at activation time

Hard-gate failure → **do not activate**. Re-evaluate as `NOT READY` for that activation window (does not invalidate this design).

---

## 3. Hard gate (all must PASS)

Any failure → **no activation**.

| # | Gate | Pass criterion |
|---|------|----------------|
| 1 | Production service | HTTP `:8027` healthy (login 200) |
| 2 | Evolution `sabry min` | Active / usable / open (probe: recent Discuss Hub sent jobs or live Evolution connectivity check) |
| 3 | Discuss health | `whatsapp.discuss.hub.health.last_status = healthy` |
| 4 | #5 / #10 | both `wa_outbound_mode = hub` |
| 5 | Discuss allowlist | `whatsapp_hub.discuss_hub_allowed_channel_ids = 10,5` |
| 6 | Campaign cutover | currently **`False`** before activation starts |
| 7 | Campaign allowlist | currently **empty** before activation starts |
| 8 | Instance #1 Campaign cutover | currently **`False`** before activation starts |
| 9 | Purposes | currently exactly **`discuss`** before activation starts |
| 10 | Campaign Hub jobs | `purpose=campaign` pending/processing count = **0** |
| 11 | Pilot Campaign | text-only, `attachment_ids` empty |
| 12 | Pilot lines | exactly **≤3** eligible pending lines (target **3**) |
| 13 | Destinations | stable E.164 test DMs only; operator-confirmed |
| 14 | Backup | fresh Production `pg_dump` taken immediately before flag flips |
| 15 | Quarantine | `whatsapp.outbound.message.service_quarantine_campaign` available |
| 16 | Tests | P5B + P5C (+ P5A) suites green on Test |
| 17 | Batch control | `whatsapp_hub.campaign_admit_batch_size` set to **`1`** for pilot window |
| 18 | Discuss isolation precheck | no change planned to Discuss ICPs/modes |

---

## 4. Exact activation sequence

**Preferred future sequence** (execute only in a dedicated activation task):

1. Fresh Production backup.  
2. Hard gate (§3) — abort on any fail.  
3. Record **T0** snapshot (flags, allowlist, purposes, #5/#10, health, campaign job counts, pilot Campaign id/lines).  
4. Create pilot Campaign + 3 pending lines (still `wa_outbound_mode=legacy`).  
5. Set `campaign_admit_batch_size=1`.  
6. Purpose transition: `discuss` → **`discuss,campaign`** (additive only).  
7. Enable global `whatsapp_hub.campaign_cutover_enabled=True`.  
8. Enable instance #1 `campaign_cutover_enabled=True`.  
9. Allowlist: `campaign_hub_allowed_campaign_ids = "<pilot_campaign_id>"` only.  
10. Keep **every other** Campaign `legacy` (#16 remains `shadow` or `legacy` — **not** hub).  
11. Flip pilot Campaign `wa_outbound_mode` → **`hub` LAST**.  
12. Process **one line at a time** (§7): admit → Hub send → verify → next.  
13. After line 03 success + idempotency checks → decide post-pilot Option A/B (§18).

**Do not** toggle Discuss cutover, Discuss allowlist, or #5/#10 modes.

ICP changes take effect on next call (no restart required), same as Discuss E2.

---

## 5. Allowlist transition

| Phase | `campaign_hub_allowed_campaign_ids` |
|-------|-------------------------------------|
| Pre-activation | empty (fail-closed) |
| Activation | **only** `<pilot_campaign_id>` |
| Post Option B | empty again |
| Post Option A | remains pilot id only |

### Expected behavior

| Case | Result |
|------|--------|
| Pilot Campaign mode=`hub` + allowlisted + flags ON | Hub admit allowed |
| Any other Campaign mode=`hub` but not allowlisted | Hub blocked (`ok=False`); lines fail; **no** legacy fallback |
| Other Campaigns mode=`legacy` | unchanged legacy path |
| Discuss traffic | unaffected (separate allowlist / purpose=`discuss`) |

---

## 6. Purpose transition

| Phase | `unified_outbound_purposes` |
|-------|------------------------------|
| Pre | `discuss` |
| During pilot | **`discuss,campaign`** |
| Post Option B | `discuss` |
| Post Option A | `discuss,campaign` |

Rules:

* Always **additive** when enabling (`discuss` must remain).  
* Never remove `discuss` during Campaign rollback.  
* Removing `campaign` must leave exactly `discuss`.

---

## 7. Three-line pilot procedure

### Architecture note

`_process_campaign_queue_hub` admits up to `campaign_admit_batch_size` (default **25**).  
For P5D, set ICP **`whatsapp_hub.campaign_admit_batch_size = 1`** so Start/Resume admits **one** pending line per invocation.

Hub transport is owned by Hub outbound (`_send_one` / cron). Admission alone must **not** mark line sent.

### Per-line loop (L = 01, then 02, then 03)

1. Confirm exactly one pending line remains “next” (or pause after first admission).  
2. `action_start_campaign` / `action_resume_campaign` / `_process_campaign_queue` once → admit **one** line.  
3. Verify post-admission (§9): still `pending`, `hub_message_id` + `hub_outbound_id` set.  
4. Trigger Hub send for that outbound job only (`_send_one` or wait for Hub cron — prefer explicit operator `_send_one` for evidence timing).  
5. Verify provider acceptance + line projection to `sent` (§8–9).  
6. Idempotency safe replay (§11).  
7. Only then proceed to next line.

Bodies:

```text
Campaign Hub Pilot 01
Campaign Hub Pilot 02
Campaign Hub Pilot 03
```

Do **not** bulk-admit all three while batch size is 1; do **not** raise batch size during pilot.

---

## 8. Expected record lineage (per line L)

```text
wa.campaign.line L
  → business_key = campaign:{campaign_id}:{L.id}
  → exactly 1 whatsapp.message
       purpose=campaign, source_app=campaign
       campaign_id, campaign_line_id
       related_model=wa.campaign.line, related_res_id=L.id
       partner/destination/instance correct
  → exactly 1 whatsapp.outbound.message
       transport_mode=unified_bridge, priority=3
       same business_key, campaign refs
       state: pending → (processing) → sent
  → 1 bridge one-shot Evolution execution
  → 1 real provider message ID
  → 1 wa.message.log
       send_origin=hub_unified
       campaign_id, campaign_line_id
       hub_message_id, wa_message_id=provider ID
  → mirror converges to SAME canonical Hub message
```

### Forbidden for pilot lines

* `walog:*` twin canonical message  
* `_send_via_evolution` / `_send_media_evolution`  
* `integration.outbound.queue` row for the line  
* duplicate provider call / duplicate business_key  

---

## 9. Lifecycle verification

| Stage | Line status | Hub refs | Notes |
|-------|-------------|----------|-------|
| Before admission | `pending` | empty | |
| Immediately after admission | **still `pending`** | `hub_message_id` + `hub_outbound_id` set | Must **not** be `sent` yet |
| After provider accepted | `sent` | same Hub ids | `wa_message_id` + `sent_date` set |
| Temporary Hub retry (if natural) | non-sent | same job | Hub owns retry; **no** legacy fallback |
| Permanent fail / exhausted | `failed` | job failed | no new logical identity |

Do **not** inject failure in Production. Observe only if natural.

---

## 10. Counter verification

Use a **dedicated** Campaign with **only** the 3 pilot lines.

After all success:

| Counter | Expected |
|---------|----------|
| total lines | 3 |
| sent | 3 |
| failed | 0 |
| pending | 0 |
| Campaign state | `completed` (when no pending remain **and** all projected sent) |

Do not judge counters from #16 or mixed campaigns.

---

## 11. Idempotency verification

After each successful line (and again after all three):

* Safe replay: `action_resume_campaign` / `_process_campaign_queue` **without** resetting sent lines to pending.  
* Verify: no new `whatsapp.message`, no new outbound job, no new provider send, no new `hub_unified` log, same `hub_message_id` / `hub_outbound_id` on the line.

**Forbidden in Production:** writing a sent line back to `pending` to force re-send.

---

## 12. Queue exclusivity

For the 3 pilot lines aggregate:

| Metric | Expected |
|--------|----------|
| Hub outbound jobs (`purpose=campaign`, pilot campaign_id) | **3** |
| `integration.outbound.queue` delta for pilot lines | **0** |
| `_send_via_evolution` for pilot lines | **0** |
| `_send_media_evolution` | **0** |
| Real provider sends / provider IDs | **3** |
| Retry owner | **Hub only** |

---

## 13. Discuss isolation checks

During and after pilot:

| Control | Must remain |
|---------|-------------|
| #5 mode | `hub` |
| #10 mode | `hub` |
| Discuss allowlist | `10,5` |
| Discuss health | `healthy` |
| Discuss cutover / unified Discuss flags | unchanged |
| purpose=`discuss` job routing | unchanged |

Purpose CSV must be **`discuss,campaign`** (never replace `discuss` with `campaign` alone).

---

## 14. Campaign-only rollback

If pilot fails but Discuss remains healthy:

1. Pilot Campaign `wa_outbound_mode` → **`shadow`** (or `legacy` if shadow evidence not needed).  
2. `service_quarantine_campaign(pilot_id, reason="P5D rollback")`.  
3. Remove pilot id from `campaign_hub_allowed_campaign_ids` (→ empty).  
4. Instance #1 `campaign_cutover_enabled=False`.  
5. Global `campaign_cutover_enabled=False`.  
6. Purposes: remove `campaign`, leave **`discuss`**.  
7. Restore `campaign_admit_batch_size` to default **25** (unless intentionally kept).

Do **not** change Discuss allowlist / #5 / #10 / Discuss flags.

---

## 15. Selective rollback vs sent messages

Operator behavior for pilot Hub jobs:

| Job / line state | Action |
|------------------|--------|
| `sent` + provider ID | **Leave sent**; never legacy-resend same line |
| `pending` / retry scheduled | Quarantine (cancel incomplete) |
| `processing` + provider ID | Treat as accepted → ensure `sent` projection; do not re-send |
| `processing` without provider ID | **Uncertain** — quarantine / hold; **no** automatic duplicate retry until reconciled |
| `failed` | Preserve evidence; **no** automatic legacy resend |

Quarantine API already encodes sent/uncertain/cancelled semantics for `purpose=campaign` only.

---

## 16. Systemic Campaign rollback

If Campaign Hub control plane itself is unsafe:

1. Stop Hub Campaign admissions (cutover OFF + allowlist empty).  
2. All Hub-mode Campaigns → `shadow`/`legacy`.  
3. Quarantine **all** incomplete `purpose=campaign` jobs.  
4. Instance Campaign cutover OFF.  
5. Global Campaign cutover OFF.  
6. Purposes remove `campaign`, preserve **`discuss`**.  

Discuss must remain operational (#5/#10 hub, allowlist `10,5`).

---

## 17. Immediate stop conditions

Rollback immediately if any:

* Duplicate provider send  
* Duplicate Campaign business key / canonical message  
* `_send_via_evolution` called for a Hub pilot line  
* Bridge queue created for a Hub pilot line  
* Compatibility log `send_origin=legacy` for Hub pilot send  
* Wrong campaign/line provenance  
* Wrong destination or instance  
* Admission marks line `sent` before provider acceptance  
* Provider accepts but line never projects `sent`  
* `walog:*` twin canonical message  
* Unexpected `retry_count > 0` on happy path  
* Campaign Hub job created for non-allowlisted Campaign  
* Discuss health becomes critical  

---

## 18. Success criteria

P5D passes only if:

1. One dedicated Campaign only is Hub-enabled.  
2. Campaign allowlist contains only that pilot id.  
3. 3/3 lines route through Hub only.  
4. 3/3 get **real** provider acceptance IDs.  
5. 3/3 lines become `sent` only after provider acceptance.  
6. 3/3 unique canonical Hub messages.  
7. 3/3 unique Hub outbound jobs.  
8. 3/3 compatibility logs converge (`hub_unified` → same Hub message).  
9. Legacy transport count = 0 for pilot lines.  
10. Legacy bridge queue delta = 0 for pilot lines.  
11. Duplicate sends = 0.  
12. Idempotent replay creates no extra sends/jobs/logs.  
13. Campaign counters: sent=3, failed=0, pending=0.  
14. No Campaign jobs outside allowlist.  
15. Discuss unchanged and healthy.

---

## 19. Post-pilot recommendation

### Options

| Option | State |
|--------|-------|
| **A — Soak** | Pilot stays `hub`; allowlist keeps pilot id; flags ON; purposes `discuss,campaign`; all others legacy |
| **B — Restore Campaign-off** | Pilot → `shadow`; quarantine incomplete; allowlist empty; flags OFF; purposes `discuss` |

### Recommendation: **Option B**

Rationale: first **live** Campaign Hub send; P5C Production did not prove Evolution for Campaign; keep control plane fail-closed until P5E soak design. Dedicated pilot Campaign can remain `shadow` for observation without leaving Campaign Hub globally enabled.

(Option A only if product explicitly wants a permanent test soak Campaign — not default.)

---

## 20. Production pilot evidence requirements

### Per line (01–03)

| Field | Capture |
|-------|---------|
| Campaign ID | |
| Campaign line ID | |
| business_key | `campaign:{id}:{line_id}` |
| Hub message ID | |
| Hub outbound job ID | |
| provider ID | |
| compatibility log ID | |
| line status before admission | |
| line status after admission | |
| final line status | |
| outbound `retry_count` | |
| legacy send count | must be 0 |
| bridge queue delta | must be 0 |

### Aggregate

* Hub sends / legacy sends / provider IDs / duplicates  
* Campaign counters  
* jobs outside allowlist (must be 0)  
* Discuss health + #5/#10 modes + Discuss allowlist  

---

## 21. Exact activation runbook (future task checklist)

```text
[ ] 1. Stop if any hard gate fails (§3)
[ ] 2. pg_dump Production → backups/pet_spot_elsahel_pre_p5d_<ts>.dump
[ ] 3. Record T0 (flags, purposes, allowlists, health, job counts)
[ ] 4. Create Campaign "P5D Controlled Campaign Hub Pilot (PROD)"
       - 3 partners/phones to approved test DM(s)
       - bodies Pilot 01..03, no attachments
       - wa_outbound_mode=legacy, generate lines, verify pending=3
[ ] 5. ICP campaign_admit_batch_size=1
[ ] 6. ICP unified_outbound_purposes: discuss → discuss,campaign
[ ] 7. ICP campaign_cutover_enabled=True
[ ] 8. Instance #1 campaign_cutover_enabled=True
[ ] 9. ICP campaign_hub_allowed_campaign_ids=<pilot_id>
[ ] 10. Confirm all other Campaigns not hub; #16 not allowlisted
[ ] 11. Flip pilot wa_outbound_mode=hub
[ ] 12. Line 01: admit → verify pending+refs → Hub _send_one → verify sent+provider+log
[ ] 13. Line 01: idempotent processor replay
[ ] 14. Line 02: same
[ ] 15. Line 03: same
[ ] 16. Aggregate evidence matrix (§20)
[ ] 17. Discuss isolation recheck
[ ] 18. Apply Option B (default) unless explicitly choosing A
[ ] 19. Write P5D activation completion report
[ ] 20. Do not start P5E
```

---

## 22. Final Production configuration matrix

### Pre-activation (current / must match before start)

| Control | Value |
|---------|-------|
| `campaign_cutover_enabled` | False |
| `campaign_hub_allowed_campaign_ids` | empty |
| Instance #1 `campaign_cutover_enabled` | False |
| `unified_outbound_purposes` | `discuss` |
| Normal Campaigns | `legacy` |
| Campaign #16 | `shadow` (leave; do not Hub) |
| purpose=campaign Hub jobs | 0 |
| #5 / #10 | hub |
| Discuss allowlist | `10,5` |
| Discuss health | healthy |

### During pilot (transient)

| Control | Value |
|---------|-------|
| `unified_outbound_purposes` | `discuss,campaign` |
| `campaign_cutover_enabled` | True |
| Instance #1 `campaign_cutover_enabled` | True |
| `campaign_hub_allowed_campaign_ids` | `<pilot_id>` only |
| `campaign_admit_batch_size` | `1` |
| Pilot Campaign mode | `hub` |
| All other Campaigns | `legacy` (#16 not hub) |
| #5 / #10 / Discuss allowlist | **unchanged** |

### Post-pilot recommended (Option B)

| Control | Value |
|---------|-------|
| Pilot mode | `shadow` |
| Allowlist | empty |
| Campaign cutovers | False / False |
| purposes | `discuss` |
| batch size | `25` (restore) |
| Discuss | unchanged / healthy |

---

## Final recommendation

**`READY TO ACTIVATE P5D CONTROLLED CAMPAIGN HUB PILOT`**

Conditions already satisfied for **design readiness**:

* P5B Hub adapter + projection + compat convergence implemented and Test-validated  
* P5C observational shadow green (Test + Prod architecture)  
* Fail-closed Campaign control plane exists  
* Real controlled DM destination available (`201000059085`)  
* Same Evolution instance already proven for Discuss Hub live sends  
* Sequential admission achievable via `campaign_admit_batch_size=1`  
* Quarantine + rollback paths defined  

**Activation remains a separate task.** This design does **not** activate Campaign Hub, does **not** change Production flags/allowlist/purposes, does **not** send messages, and does **not** start P5E.

If at activation time Evolution is down, test destinations are unavailable, or hard gate fails → abort that window as not ready to activate (design still stands).
