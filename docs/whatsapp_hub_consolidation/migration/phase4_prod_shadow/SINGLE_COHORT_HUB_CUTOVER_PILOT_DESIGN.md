# Single-Cohort Hub Cutover Pilot — Design Only

**Date:** 2026-07-23  
**Status:** DESIGN ONLY — **no Production changes in this task**  
**Cohort:** Discuss channel **#10** (`openlowtest` / `Testopenclow`)  
**Decision:** **READY TO ACTIVATE SINGLE-COHORT PILOT** (activation is a separate explicit task)

Evidence baseline: [`OPENLOWTEST_SHADOW_EVIDENCE_REPORT.md`](./OPENLOWTEST_SHADOW_EVIDENCE_REPORT.md)

---

## 0. Non-goals (this document)

- Do **not** enable cutover flags.
- Do **not** set any channel to `hub`.
- Do **not** send Hub pilot messages.
- Do **not** start Campaign migration / Phase 5.
- Do **not** change Production behavior while writing this plan.

---

## 1. Exact current prerequisite flags and their scope

### 1.1 Production snapshot (read-only, current)

| Config | Current value |
|--------|----------------|
| Modules | Hub `19.0.1.3.0`, chat `19.0.1.12.0`, bridge `19.0.1.1.2` |
| `whatsapp_hub.unified_outbound_enabled` | `False` |
| `whatsapp_hub.discuss_cutover_enabled` | `False` |
| `whatsapp_hub.unified_outbound_purposes` | empty (= all purposes allowed **if** unified is later ON) |
| `whatsapp.instance` #1 `sabry min` | `unified_outbound_enabled=False`, `discuss_cutover_enabled=False`, `is_default=True` |
| Channel #5 | `shadow` |
| Channel #10 | `shadow`, `wa_phone=120363411424964076@g.us` |
| Channels in `hub` | **0** |
| `unified_bridge` jobs | **0** |
| Shadow matched / other | **11 / 0** |
| Conversation #8 | `remote_jid=120363411424964076@g.us`, `purpose=discuss`, `instance_reference=sabry min` |
| Hub group #1 | same JID (`prod-cutover-synth`) |

### 1.2 Code-enforced hierarchy for Discuss Hub mode

Source: `discuss.channel._wa_hub_cutover_prerequisites` + `_send_whatsapp_discuss_message`.

Channel #10 enters Hub transport **only if all** of the following are true:

| # | Control | Required for Hub send |
|---|---------|------------------------|
| 1 | Channel `#10.wa_outbound_mode` | **`hub`** |
| 2 | ICP `whatsapp_hub.unified_outbound_enabled` | `True` |
| 3 | ICP `whatsapp_hub.discuss_cutover_enabled` | `True` |
| 4 | Resolved Hub instance (`sabry min`) `unified_outbound_enabled` | `True` |
| 5 | Same instance `discuss_cutover_enabled` | `True` |

Additionally, `service_send_message` re-checks (2) and (4) via `_assert_unified_outbound_enabled`.

Missing any prerequisite while mode=`hub` → **pre-admission failure** (user-facing error note). **No** `_send_via_evolution`. **No** Hub job.

### 1.3 Why other traffic stays off Hub when globals/instance flags are ON

| Caller | Routing owner | Effect of enabling globals + `sabry min` instance flags |
|--------|---------------|--------------------------------------------------------|
| Discuss channel `#10` | `wa_outbound_mode` | Uses Hub **only after** mode flipped to `hub` (last step) |
| Discuss channel `#5` | `wa_outbound_mode=shadow` | Stays on **legacy** `_send_via_evolution` + preview; does **not** call `service_send_message` |
| New Discuss WA channels | field default `legacy` | Stay legacy until explicitly changed |
| Campaign / wizards | direct `_send_via_evolution` | **Ignore** Discuss channel modes and Discuss cutover ICPs |
| Clinic / other | `service_queue_outbound` (`legacy_direct`) | **Not gated** by unified flags; unchanged |

**Blast-radius note:** Turning ON `whatsapp_hub.unified_outbound_enabled` unlocks the Hub API for any privileged caller that explicitly invokes `service_send_message`. Today Production has **no automatic non-Discuss caller**. Discuss remains channel-mode gated.

### 1.4 Recommended tighter scope (optional but preferred)

Before activation, set:

```text
whatsapp_hub.unified_outbound_purposes = discuss
```

Empty CSV currently means “all purposes”. Restricting to `discuss` prevents accidental Hub API use with `purpose=crm|campaign|clinic` even if someone calls the API while flags are ON.

---

## 2. Exact activation sequence

Preferred principle: **enable prerequisites first, flip cohort last**.

### Step A0 — Fresh backup (mandatory before any flag change)

```text
Stop or quiesce as per project procedure if required
pg_dump -Fc pet_spot_elsahel → .migration_backups/p4_hub_cohort_<UTC>/
Record baselines (section 3)
```

### Step A1 — Pre-cutover hard gate (section 3)

PASS required. Stop if FAIL.

### Step A2 — Optional purpose allow-list

```text
ICP whatsapp_hub.unified_outbound_purposes = discuss
```

### Step A3 — Global prerequisites

```text
ICP whatsapp_hub.unified_outbound_enabled = True
ICP whatsapp_hub.discuss_cutover_enabled  = True
```

At this point: **still no Hub Discuss traffic** (no channel in `hub`).

### Step A4 — Instance prerequisites (only `sabry min` / id=1)

```text
whatsapp.instance(1).unified_outbound_enabled = True
whatsapp.instance(1).discuss_cutover_enabled  = True
```

Still no Hub Discuss traffic until channel mode changes.

### Step A5 — Verify isolation before flip

```sql
SELECT id, wa_outbound_mode FROM discuss_channel
 WHERE wa_phone IS NOT NULL AND wa_phone != '';
-- expect: #5 shadow, #10 shadow, zero hub

SELECT COUNT(*) FROM discuss_channel WHERE wa_outbound_mode='hub';
-- expect: 0
```

### Step A6 — Flip cohort last

```text
discuss.channel #10 wa_outbound_mode = hub
```

**Only now** can Discuss posts on #10 call `service_send_message`.

### Step A7 — Immediate post-flip sanity (no customer messages yet)

Confirm flags + modes (section 15 matrix “After A6”). Then run the 3-message pilot (section 6).

---

## 3. Exact rollback sequence

### Preferred immediate rollback (routing first)

```text
discuss.channel #10 wa_outbound_mode = shadow
```

**Why `shadow` (not `legacy`):** restores legacy `_send_via_evolution` as sole sender **and** keeps shadow evidence collection on the same cohort without losing the observation path.

### Then quarantine admitted Hub jobs (mandatory if any pending/processing)

See section 12. Do this **immediately** after mode flip-back if any Hub jobs for channel #10 are not `sent`/`failed`/`cancelled`.

### Then optionally disable higher-level flags (after quarantine)

Order (narrow → wide):

1. `whatsapp.instance(1).discuss_cutover_enabled = False`
2. `whatsapp.instance(1).unified_outbound_enabled = False`
3. `ICP whatsapp_hub.discuss_cutover_enabled = False`
4. `ICP whatsapp_hub.unified_outbound_enabled = False`
5. Optionally clear or leave `unified_outbound_purposes`

Channel #5 remains `shadow` throughout (no change required).

---

## 4. Blast-radius analysis

| Surface | During pilot (flags ON + #10=`hub`) | Risk |
|---------|-------------------------------------|------|
| Channel #10 OpenLow group | Hub unified path | **Intended** |
| Channel #5 Bridge Test DM | Shadow → legacy send | Unchanged |
| Future WA Discuss channels | Default `legacy` | Unchanged |
| Campaign sends | `_send_via_evolution` | Unchanged |
| Clinic `service_queue_outbound` | `legacy_direct` | Unchanged |
| Manual/API `service_send_message` | Enabled if caller has access | Mitigate with `unified_outbound_purposes=discuss` |
| Hub outbound cron `process_pending` | Retries **unified_bridge** pending jobs | Only jobs already admitted; quarantine on rollback |

**Smallest blast radius achieved by:** purpose allow-list + only one channel in `hub` + flip channel last / rollback channel first.

---

## 5. Pre-cutover hard gate

### Pass/fail checklist

| # | Check | Pass condition |
|---|-------|----------------|
| G1 | Service | `pet_spot_elsahel.service` **active** |
| G2 | Evolution | `GET/POST` health or `sendText` dry probe to known group **not** required; at least Manager/`fetchInstances` shows `sabry min` **open** |
| G3 | Instance resolve | `_wa_resolve_hub_instance()` → instance id **1** `sabry min` |
| G4 | Outage | No widespread WA send failure in last hour; Evolution connection **open** |
| G5 | Unified queue clean | `COUNT(*) WHERE transport_mode='unified_bridge' AND state IN ('pending','processing')` = **0** |
| G6 | Channel #10 JID | `wa_phone = '120363411424964076@g.us'` |
| G7 | Group / conversation | Hub group #1 JID match; conversation #8 still `purpose=discuss`, same remote JID |
| G8 | No hub channels | `COUNT(wa_outbound_mode='hub') = 0` **before** A6 |
| G9 | Shadow health | Channel #10 shadow rows all `matched`; `COUNT(classification!='matched' AND channel_id=10)=0` |
| G10 | Backup | Fresh dump under `.migration_backups/` **after** shadow evidence, **before** flag changes (new dump preferred; existing `p4_shadow_pilot_20260723T113020Z` is insufficient alone once pilot starts) |
| G11 | Baselines recorded | Section 5.1 numbers written to evidence file |
| G12 | Modules | Hub ≥ `19.0.1.3.0`, chat ≥ `19.0.1.12.0`, bridge ≥ `19.0.1.1.2` |

**Gate rule:** any FAIL → **do not activate**. Fix or abort.

### 5.1 Baselines to record immediately before A3

```text
T0_unified_bridge_total
T0_unified_bridge_pending
T0_shadow_matched / T0_shadow_other
T0_hub_mode_channels
T0_wa_log_count
T0_whatsapp_message_count
T0_conversation_8_message_count
channel_5_mode, channel_10_mode, flags, instance flags
```

---

## 6. Three-message pilot procedure (design — do not execute here)

### Messages (plain text only)

| Seq | Body |
|-----|------|
| 01 | `OpenLow Hub Cutover Pilot 01` |
| 02 | `OpenLow Hub Cutover Pilot 02` |
| 03 | `OpenLow Hub Cutover Pilot 03` |

### How to send

1. Open Odoo Discuss channel **#10** (or WA channel form that posts into it).
2. Post each message as an **internal user** via normal composer (`message_type=comment`).
3. **Do not** call `service_send_message` from shell for the happy path (shell may be used only for verification queries).
4. **No** media, attachments, templates, buttons.
5. Wait for each message’s Hub job to reach `sent` (or hard-fail) before sending the next.
6. After each message, run section 7–9 checks.

---

## 7. Expected record lineage (per message)

```text
mail.message M
  business_key = discuss:10:{M.id}

→ whatsapp.outbound.message.service_send_message(send_now=True)
    → whatsapp.conversation #8  (reuse: instance sabry min + JID + purpose=discuss)
    → whatsapp.message H
         business_key = discuss:10:{M.id}
         purpose = discuss
         source_app = discuss
         discuss_channel_id = 10
         related_model = mail.message
         related_res_id = M.id
    → whatsapp.outbound.message O
         transport_mode = unified_bridge
         business_key = discuss:10:{M.id}
         discuss_channel_id = 10
         message_id = H
    → whatsapp.hub.transport.send_text
    → evolution.instance.send_whatsapp_text   (one-shot)
    → Evolution HTTP accept → provider id P

→ wa.message.log L (compatibility)
     send_origin = hub_unified
     hub_message_id = H
     mail_message_id = M.id
     channel_id = 10
     phone = 120363411424964076@g.us
     wa_message_id = P

→ mirror_wa_message_log(L)
     finds H via hub_message_id / discuss:* key
     enriches H.wa_message_log_id = L.id
     does NOT create second whatsapp.message
     does NOT overwrite business_key discuss:* with walog:*
```

**Exclusivity:** `_send_via_evolution` call count for that Discuss action = **0**.  
No `integration.outbound.queue` row for the same Discuss send.

---

## 8. Idempotency / convergence verification

Run after each pilot message (`M`, `H`, `O`, `L`, `P` as above):

```sql
-- Business key shape
SELECT id, business_key, wa_message_log_id, purpose, remote_jid, conversation_id
  FROM whatsapp_message
 WHERE business_key = 'discuss:10:' || <M.id>::text;
-- expect: exactly 1 row; business_key starts with discuss:10:; conversation_id = 8

-- No walog duplicate for same logical send
SELECT COUNT(*) FROM whatsapp_message
 WHERE business_key = 'walog:' || <L.id>::text;
-- expect: 0  (or if present, must be SAME id as H — should not happen)

-- Compat link
SELECT id, hub_message_id, mail_message_id, send_origin, wa_message_id
  FROM wa_message_log WHERE id = <L.id>;
-- expect: hub_message_id = H.id, mail_message_id = M.id, send_origin = hub_unified

-- Outbound job
SELECT id, state, transport_mode, business_key, evolution_message_id, retry_count
  FROM whatsapp_outbound_message
 WHERE business_key = 'discuss:10:' || <M.id>::text;
-- expect: 1 row, unified_bridge, state=sent, evolution_message_id = P

-- Replay safety (optional API check, not a second Discuss post)
-- service_send_message same business_key → duplicate=True, transport not re-invoked
```

---

## 9. Transport exclusivity verification

Per message:

| Check | Expected |
|-------|----------|
| Hub `unified_bridge` jobs with that business_key | **1** |
| Job state after success | `sent` |
| Provider / Evolution message IDs unique across 01–03 | **3 unique** |
| Legacy `_send_via_evolution` for that post | **0** (no new `send_origin=legacy` log for that `mail_message_id`) |
| `integration.outbound.queue` created for that Discuss post | **0** |
| Dual retry (bridge queue + Hub) | **None** — bridge one-shot only |

Aggregate after batch:

```sql
SELECT COUNT(*) FROM whatsapp_outbound_message
 WHERE transport_mode='unified_bridge' AND discuss_channel_id=10;
-- expect: +3 vs T0

SELECT COUNT(*) FROM whatsapp_outbound_message
 WHERE transport_mode='unified_bridge' AND discuss_channel_id IS DISTINCT FROM 10;
-- expect: 0 new

SELECT COUNT(*) FROM discuss_channel WHERE wa_outbound_mode='hub';
-- expect: 1 (#10 only)
```

---

## 10. Retry / failure validation recommendation

**Recommendation: run failure/retry on Test (`pet_spot_elsahel_test`), not Production.**

| Environment | Approach |
|-------------|----------|
| **Test** | Mock `WhatsappHubTransport.send_text` temporary fail → assert pending retry, same `H`/`O`, no `_send_via_evolution`; then mock success → same records, one final provider id |
| **Production** | **Success-only** 3-message pilot; do **not** inject transport failures against live Evolution |

**Rationale:** Production failure injection risks real double-send ambiguity and pollutes the customer-visible OpenLow group with error/retry noise. Phase 4 Test already covered post-admission no-legacy-fallback.

Production still observes natural failures if they occur — then apply stop conditions (section 11) and rollback.

---

## 11. Monitoring and stop conditions

### Watch during pilot window

- `whatsapp.outbound.message`: `state`, `retry_count`, `next_retry_at`, `error_message`, `evolution_message_id`, `transport_mode`
- `whatsapp.message`: `state`, `delivery_state`, `business_key`, `evolution_message_id`, `conversation_id`
- `wa.message.log`: `send_origin`, `hub_message_id`, `wa_message_id`
- Channel modes / ICP / instance flags
- Evolution HTTP accept (provider id present)
- Unexpected new `send_origin=legacy` logs on channel #10 during Hub window
- Unique constraint / duplicate `business_key` errors in logs

### Immediate rollback triggers

Rollback channel #10 → `shadow` **immediately** if any of:

1. Duplicate WhatsApp provider send for one `mail.message`
2. Second `whatsapp.message` for same `discuss:10:{mm}`
3. Any `_send_via_evolution` / `send_origin=legacy` for a Hub-mode post on #10
4. Wrong JID or instance on Hub message / job
5. Unexplained stuck `processing` > 2 minutes without resolution
6. Post-admission path somehow falls back to legacy (must not happen; treat as critical if observed)
7. Any new `unified_bridge` job with `discuss_channel_id != 10`
8. Channel other than #10 found in `hub` mode

---

## 12. Rollback handling for already-admitted Hub jobs

### Risk

Hub cron `whatsapp.outbound.message.process_pending` can still send `pending` unified jobs **even after** channel #10 returns to `shadow`. That can cause a late Hub send that operators might also “retry” manually via Discuss → **double-send risk**.

### Required rollback procedure for jobs

Immediately after `wa_outbound_mode=shadow` on #10:

```sql
-- Identify admitted incomplete jobs for cohort
SELECT id, state, business_key, evolution_message_id, retry_count, next_retry_at
  FROM whatsapp_outbound_message
 WHERE discuss_channel_id = 10
   AND transport_mode = 'unified_bridge'
   AND state IN ('pending', 'processing');
```

**Actions:**

| Job state | Action |
|-----------|--------|
| `pending` (no provider id) | Set `state='cancelled'`, clear `next_retry_at`, note in `error_message`=`cohort rollback quarantine` |
| `processing` | Wait ≤60s for completion; if still processing, cancel if safe / mark failed; **do not** leave pending retry |
| `sent` with provider id | Leave; treat as done — **do not** resend same Discuss message via legacy |
| `failed` | Leave failed; do not legacy-resend same `mail.message` |

**Discuss UX rule after rollback:** do **not** re-post the same text as a “retry” of a message that already has a Hub `sent` provider id. New user text creates a new `mail.message` / new business key (safe).

Optional: temporarily pause Hub outbound cron during quarantine window (if operationally available), then restore.

---

## 13. Success criteria (single-cohort Hub pilot)

Pilot **PASSED** only if all hold:

1. Only channel #10 used Hub (`wa_outbound_mode=hub` exclusively).
2. Channel #5 remained `shadow`; no other channel entered `hub`.
3. Campaign path unchanged (still `_send_via_evolution`).
4. 3/3 pilot messages: **zero** legacy transport.
5. 3/3: exactly **one** Hub `unified_bridge` transport success each.
6. 3/3: non-empty Evolution/provider message IDs.
7. 3/3: exactly one canonical `whatsapp.message` each with `discuss:10:{mm}`.
8. 3/3: compatibility logs `send_origin=hub_unified` converge to same Hub ids.
9. All three reuse conversation **#8** (unless resolver bug — treat as FAIL).
10. No duplicate provider sends.
11. No duplicate Hub messages.
12. No `unified_bridge` jobs outside cohort.
13. No uncontrolled retries (`retry_count` stays 0 on success path).
14. Rollback procedure documented and job-quarantine steps verified as ready (dry-run query OK).

Delivered/read receipts are **not** required within the pilot window; transport **acceptance** (`state=sent` + provider id) is the success bar.

---

## 14. Post-pilot decision matrix

### A. PILOT FAILED

- Set channel #10 → `shadow`
- Quarantine incomplete Hub jobs (section 12)
- Disable instance + global cutover flags
- Investigate; no expansion

### B. PILOT PARTIAL

- Set channel #10 → `shadow`
- Preserve Hub messages / jobs / logs as evidence
- Fix on Test; repeat controlled 3-message pilot later

### C. PILOT PASSED

- Still **do not** expand globally
- **Default recommendation after pass:** return channel #10 → `shadow` and disable cutover flags until an explicit “leave in Hub” approval
- Alternative (requires explicit human approval): leave #10 in `hub` with flags ON for extended soak — still one cohort only
- Next phase would be **controlled Discuss cohort expansion design**, not Campaign

---

## 15. Exact Production configuration before / after each planned step

| Step | Global unified | Global discuss cutover | Inst#1 unified | Inst#1 discuss | Ch#5 | Ch#10 | Hub sends possible on #10? |
|------|----------------|------------------------|----------------|----------------|------|-------|----------------------------|
| **Now (baseline)** | False | False | False | False | shadow | shadow | No |
| After A2 purposes=`discuss` | False | False | False | False | shadow | shadow | No |
| After A3 globals ON | True | True | False | False | shadow | shadow | No |
| After A4 instance ON | True | True | True | True | shadow | shadow | No |
| After A6 cohort flip | True | True | True | True | shadow | **hub** | **Yes** |
| Immediate rollback | True* | True* | True* | True* | shadow | **shadow** | No (Discuss); quarantine jobs |
| Full rollback | False | False | False | False | shadow | shadow | No |

\*Higher-level flags may still be True briefly after routing rollback; job quarantine must run before relying on “safe idle”.

---

## 16. Activation-task runbook (for the next explicit task)

1. Fresh DB dump + baselines.  
2. Execute gate G1–G12.  
3. Optional: set `unified_outbound_purposes=discuss`.  
4. Enable globals → enable instance #1 flags → verify zero `hub` channels.  
5. Set channel #10 → `hub`.  
6. Send Pilot 01–03 via Discuss UI; verify lineage after each.  
7. Aggregate exclusivity + conversation reuse checks.  
8. Apply decision matrix A/B/C.  
9. Prefer return #10 to `shadow` + disable flags unless soak approved.

---

## Final recommendation

**READY TO ACTIVATE SINGLE-COHORT PILOT**

Rationale: shadow validation 11/11 matched; routing hierarchy isolates Hub to channel mode; cohort JID/conversation/#10 mapping is proven; Campaign/clinic paths do not consume Discuss cutover flags; rollback is configuration-first with an explicit Hub-job quarantine rule.

**This task stops here — no flags changed, no channel switched to `hub`, no messages sent.**
