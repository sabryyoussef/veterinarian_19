# E2 — Second-Channel Hub Pilot Design (Channel #5)

**Date:** 2026-07-23  
**Status:** DESIGN ONLY — **no Production changes in this task**  
**Cohort:** Discuss channel **#5** (Sabry Bridge Test DM) as second Hub channel  
**Ongoing soak:** Channel **#10** remains Hub (do not modify)  
**Decision:** **`READY TO ACTIVATE E2 SECOND-CHANNEL PILOT`** (activation is a separate explicit task)

Evidence baselines:

- E1 soak: [`E1_EXTENDED_HUB_SOAK_REPORT.md`](./E1_EXTENDED_HUB_SOAK_REPORT.md)
- #5 shadow: [`E1_CHANNEL5_SHADOW_EVIDENCE_REPORT.md`](./E1_CHANNEL5_SHADOW_EVIDENCE_REPORT.md)
- Read-only precheck: `e2_design_precheck.txt`

---

## 0. Non-goals (this document)

- Do **not** add `#5` to the allowlist.
- Do **not** switch `#5` to `hub`.
- Do **not** send E2 pilot messages.
- Do **not** modify `#10` routing or soak flags.
- Do **not** start Campaign migration / Phase 5.
- Do **not** change Production ICP/flags/modes while writing this plan.

---

## 1. Current Production prerequisite state (read-only verified)

### 1.1 Exact values (2026-07-23 design precheck)

| Item | Current value |
|------|----------------|
| HTTP Production `:8027` | **200** |
| `#10` mode / phone | **`hub`** / `120363411424964076@g.us` |
| `#5` mode / phone | **`shadow`** / `201000059085` |
| Hub-mode channel IDs | **`[10]`** (count = 1) |
| `whatsapp_hub.discuss_hub_allowed_channel_ids` | **`10`** → parse **`[10]`** |
| `whatsapp_hub.unified_outbound_enabled` | **`True`** |
| `whatsapp_hub.discuss_cutover_enabled` | **`True`** |
| `whatsapp_hub.unified_outbound_purposes` | **`discuss`** |
| Instance #1 `sabry min` unified / Discuss | **`True` / `True`** |
| `#5` Hub prerequisites | **FAIL** — `channel 5 is not in discuss_hub_allowed_channel_ids=[10]` |
| `#5` shadow matched / mismatches | **10 / 0** |
| `#5` `unified_bridge` jobs | **0** |
| Pending/processing `unified_bridge` | **0** |
| Jobs outside allowlist (≠10) | **0** |
| Conversation **#7** | `purpose=discuss`, `remote_jid=201000059085@s.whatsapp.net`, instance `sabry min` |
| Conversation **#8** | `purpose=discuss`, `remote_jid=120363411424964076@g.us`, instance `sabry min` |
| Recent `#10` Hub jobs | ids 12–14 `sent`, retry=0 (E1 soak tail) |
| `service_quarantine_discuss_channel` | **available** |
| Campaign send path | **`_send_via_evolution`** only (no `service_send_message` in campaign send) |
| Evolution Odoo record | `evolution.instance` #3 `Clinic (sabry min)`, `active=True` (no connection-state field in model; openness proven by live E1/#5 shadow sends) |

### 1.2 Allowlist enforcement (code)

Source: `_parse_discuss_hub_allowlist` + `_wa_hub_cutover_prerequisites` in `evolution_whatsapp_chat/models/discuss_channel.py`.

When Discuss cutover is ON:

| Allowlist condition | Behavior |
|---------------------|----------|
| Empty / missing | Fail-closed — **no** Hub Discuss transport |
| Malformed | Fail-closed |
| Channel id absent | Fail-closed with explicit error |
| Channel id present + flags + `wa_outbound_mode=hub` | Hub admission allowed |

`#5` today fails Hub **because it is not allowlisted** (and remains `shadow`, so the Hub path is not selected). Flags alone are insufficient.

### 1.3 ICP reload requirement

`ir.config_parameter.get_param` reads the database on each call.

**No Odoo restart / worker reload is required** for allowlist or flag ICP changes to take effect on the next Discuss send.

---

## 2. Hard gate (must all PASS before activation)

| # | Gate | Pass criterion |
|---|------|----------------|
| G1 | Service healthy | `:8027/web/login` → 200 |
| G2 | Evolution `sabry min` usable | `evolution.instance` active **and** recent successful outbound on that instance (prefer a live text probe to Bridge Test or confirm latest `#10` Hub `sent` &lt; 24h); if Evolution Manager shows disconnected → **FAIL** |
| G3 | `#10` Hub healthy | mode=`hub`; last Hub jobs `sent` with retry=0; no unexplained pending/failed spike |
| G4 | `#5` shadow | matched **≥10**, mismatches **0** |
| G5 | `#5` identity | `wa_phone=201000059085`; conversation **#7** stable |
| G6 | Unified queue | pending/processing = **0**, or every row understood and not Discuss-ambiguous |
| G7 | Allowlist | exactly raw `10`, parse `[10]` |
| G8 | Hub-mode channels | exactly **`#10`** only |
| G9 | Quarantine | `hasattr(..., 'service_quarantine_discuss_channel')` |
| G10 | Fresh backup | new `pg_dump -Fc` under `.migration_backups/` recorded with size + exit 0 |
| G11 | Campaign isolated | campaign still imports `_send_via_evolution` |

**Any FAIL → do not activate E2.**

---

## 3. Exact allowlist transition

| Phase | ICP value | Parsed | `#5` transport |
|-------|-----------|--------|----------------|
| Before E2 | `10` | `[10]` | Legacy once (shadow) |
| After allowlist expand, `#5` still shadow | `10,5` | `[10,5]` | Still legacy once (mode≠hub) |
| After `#5` → hub | `10,5` | `[10,5]` | Hub only |
| `#5`-only rollback | `10` | `[10]` | Legacy (shadow) |

Parser expectation after expand:

```text
_parse_discuss_hub_allowlist(env) == [10, 5]
```

Order of IDs in CSV may be `10,5` (preferred) or `5,10`; parser returns integer list — assert **set equality `{10,5}`** and **len==2**. Prefer storing exactly **`10,5`** for operational consistency.

---

## 4. Exact activation sequence (smallest / safest)

**Do not toggle global or instance flags** — they are already ON for `#10` soak.

```text
1. Fresh Production DB backup (G10).
2. Run hard gate G1–G11; abort on any FAIL.
3. Record T0 snapshot:
     modes, allowlist, hub-mode count, pending unified,
     jobs counts for discuss_channel_id in (5,10),
     conv #7/#8 message counts.
4. Set allowlist:
     whatsapp_hub.discuss_hub_allowed_channel_ids = "10,5"
5. Verify parse == [10, 5] (or set {10,5}).
6. KEEP #5 wa_outbound_mode = shadow.
7. Isolation probe (optional but recommended):
     assert #5 Hub prerequisites would now PASS if mode were hub
       (ok=True from _wa_hub_cutover_prerequisites)
     assert #5 mode still shadow → one controlled shadow post still uses
       _send_via_evolution once and creates ZERO unified_bridge jobs for #5.
     (Skip probe if traffic risk; then rely on code assertion only.)
8. Flip LAST:
     discuss.channel #5 wa_outbound_mode = hub
9. Leave #10 = hub unchanged.
10. Commit; re-snapshot:
     hub-mode channels = {5,10}
     allowlist = 10,5
11. Run 3-message E2 pilot (section 5).
```

No module upgrade expected if E1 hardening (`19.0.1.4.0` / `19.0.1.13.0`) already deployed.

---

## 5. Three-message pilot procedure

| seq | Body (plain text) | Path |
|-----|-------------------|------|
| 01 | `Bridge Hub Pilot 01` | Discuss `message_post` on channel **#5** only |
| 02 | `Bridge Hub Pilot 02` | same |
| 03 | `Bridge Hub Pilot 03` | same |

Rules:

- Normal Odoo Discuss path only (shell `message_post` with admin user is OK if UI unavailable; must not call `service_send_message` directly for happy path).
- No media / attachments / templates / buttons.
- Sequential; verify after each message before next.
- Controlled `#10` sends **not** required; organic `#10` Hub traffic allowed.

Hard-stop after any failed verification (section 10).

---

## 6. Expected record lineage (each `#5` pilot message)

```text
mail.message M  (res_model=discuss.channel, res_id=5)
  → business_key = discuss:5:{M.id}
  → whatsapp.message (exactly one)
       purpose=discuss
       source_app=discuss
       discuss_channel_id=5
       related_model=mail.message
       related_res_id=M.id
       conversation_id=7
       remote_jid ≈ 201000059085@s.whatsapp.net (normalized)
       instance = sabry min
  → whatsapp.outbound.message (exactly one)
       transport_mode=unified_bridge
       business_key=discuss:5:{M.id}
       discuss_channel_id=5
       state=sent, retry_count=0 (happy path)
  → bridge one-shot transport (exactly one accept)
  → unique evolution_message_id / provider id
  → wa.message.log (exactly one)
       send_origin=hub_unified
       hub_message_id → canonical Hub message
       mail_message_id=M
  → mirror converges same Hub message
       Hub.wa_message_log_id = log.id
       ZERO walog:{log.id} twin
       ZERO _send_via_evolution
       ZERO new integration.outbound.queue row for this post
```

---

## 7. Multi-cohort isolation checks

| Check | Expectation |
|-------|-------------|
| Allowlist | exactly `{10,5}` |
| Hub-mode set | exactly `{5,10}` |
| `#10` messages | conversation **#8**, JID `…076@g.us`, biz `discuss:10:*` |
| `#5` messages | conversation **#7**, JID `201000059085@…`, biz `discuss:5:*` |
| Cross-link | no `#5` mail → conv #8; no `#10` mail → conv #7 |
| Business keys | no collision between `discuss:10:*` and `discuss:5:*` namespaces |
| Jobs outside `{5,10}` | **0** new `unified_bridge` with other `discuss_channel_id` |
| `#10` soak | mode stays `hub`; no forced mode/flag/allowlist regression |

---

## 8. Transport exclusivity checks

### Per `#5` pilot message

| Metric | Expect |
|--------|--------|
| Hub unified transport calls | **1** |
| `_send_via_evolution` | **0** |
| Provider accepts | **1** unique id |
| Legacy bridge queue delta | **0** |
| Canonical Hub messages for biz key | **1** |
| Compat log `send_origin` | `hub_unified` only |
| Retry count | **0** on success |

### Aggregate (pilot)

| Metric | Expect |
|--------|--------|
| New `#5` `unified_bridge` jobs | **+3** |
| New `#5` Hub messages | **+3** |
| Unique provider IDs | **3** |
| Jobs with `discuss_channel_id ∉ {5,10}` | **0** |
| Legacy leakage on `#5` while hub | **0** |

Instrument with patches/counters on `_send_via_evolution` and Hub `send_text` as in E1 (optional but recommended).

---

## 9. Rollback — `#5` only (preferred if `#10` still healthy)

**Key difference from E1 full rollback:** leave global/instance flags **ON** and leave `#10` in **`hub`**.

```text
1. discuss.channel #5: hub → shadow
2. env['whatsapp.outbound.message'].service_quarantine_discuss_channel(
       5, reason="E2 rollback")
3. Allowlist: "10,5" → "10"
4. Verify parse == [10]
5. Verify hub-mode channels == {10} only
6. Do NOT disable instance/global flags
7. Confirm #10 still hub; pending #5 incomplete jobs cancelled/reconciled
```

### Quarantine handling by job state (`#5` only)

| State | Action |
|-------|--------|
| `pending` / retry scheduled | → `cancelled`; clear `next_retry_at` |
| `processing` + provider id | treat as `sent`; do not legacy-resend |
| `processing` without provider id | uncertain → cancel + clear retry; manual review |
| `sent` | leave |
| `failed` | leave; **no** automatic legacy resend |
| Idempotent re-run | counts `already_cancelled` / `already_sent` |

**Mandatory:** mode→shadow alone does **not** stop already-admitted Hub jobs; quarantine is required.

---

## 10. Systemic rollback (both cohorts)

Use if Hub issue appears on **both** `#10` and `#5`, or root cause is platform-wide.

```text
1. Stop admission: #5 → shadow, #10 → shadow
2. Quarantine: service_quarantine_discuss_channel(5, ...)
               service_quarantine_discuss_channel(10, ...)
3. Allowlist: set "" (fail-closed) OR leave "10" only after #5 removed —
   preferred systemic: set "" then disable flags
4. Instance #1: unified_outbound_enabled=False, discuss_cutover_enabled=False
5. Global: unified_outbound_enabled=False, discuss_cutover_enabled=False
6. Confirm hub-mode count=0; pending Discuss unified=0 or only sent/failed residual
7. Preserve evidence; do not Campaign-fallback the same mail.message IDs
```

Safe order rationale: stop new Hub admission → kill incomplete admitted jobs → remove capability flags.

---

## 11. Stop conditions

### Immediate `#5`-only rollback

- Duplicate provider send or duplicate canonical Hub message for a biz key  
- Any `_send_via_evolution` on a `#5` Hub-mode post  
- Any `#5` Hub-mode compat log with `send_origin=legacy`  
- Wrong JID / instance / conversation (≠ #7)  
- Unexpected pending/processing after send_now happy path  
- `unified_bridge` job for non-allowlisted channel  
- Allowlist parse ≠ `{10,5}` during pilot  
- Compat log fails to converge (`hub_message_id` / `wa_message_log_id`)  
- Unexplained retries (`retry_count>0` on success path)

### Escalate to systemic rollback

Same class of failure also observed on `#10`, or shared transport/instance outage creating duplicate-send risk.

---

## 12. Success criteria (pilot PASSED)

All must hold:

1. `#10` remains `hub` and healthy.  
2. `#5` is the only newly added Hub channel (hub-mode set = `{5,10}`).  
3. Allowlist exactly `10,5` (set `{10,5}`).  
4. 3/3 `#5` pilot messages use Hub only.  
5. 3/3 legacy transport count = 0.  
6. 3/3 unique provider IDs.  
7. 3/3 exactly one canonical Hub message each.  
8. 3/3 compat logs converge.  
9. All three reuse conversation **#7**.  
10. No duplicates.  
11. No legacy leakage.  
12. No uncontrolled retries.  
13. No jobs outside allowlist.  
14. `#10` conversation **#8** / job baselines unaffected by the `#5` batch (no forced regressions).

---

## 13. Post-pilot state options

### Option A — Passed, continue two-channel soak (recommended default)

| Item | Value |
|------|--------|
| `#10` | `hub` |
| `#5` | `hub` |
| Allowlist | `10,5` |
| Global + instance flags | remain **ON** |
| Campaign | unchanged |

Recommend **Option A** after a clean 3/3 — mirrors E1 “leave cohort soaking” once quarantine and allowlist isolation are proven.

### Option B — Passed but conservative

| Item | Value |
|------|--------|
| `#5` | → `shadow` + quarantine `#5` |
| Allowlist | → `10` |
| `#10` | remains `hub` |
| Flags | remain ON |

Use Option B if operator wants minimal dual-cohort window or monitoring bandwidth is limited.

**Recommended default: Option A** if all success criteria pass.

---

## 14. Campaign isolation (explicit)

E2 requires **zero** changes to:

- `wa.campaign` / `wa.campaign.line`  
- Campaign `_send_via_evolution` path  
- Campaign templates / bulk send  
- Integration bridge campaign queues  

Do **not** start Phase 5.

---

## 15. Exact Production configuration matrix

| Config | Before E2 (now) | During E2 pilot | After PASS (Option A) | After `#5`-only rollback |
|--------|-----------------|-----------------|------------------------|---------------------------|
| Allowlist | `10` | `10,5` | `10,5` | `10` |
| `#10` mode | `hub` | `hub` | `hub` | `hub` |
| `#5` mode | `shadow` | `hub` | `hub` | `shadow` |
| Global unified | ON | ON | ON | ON |
| Global Discuss cutover | ON | ON | ON | ON |
| Instance #1 flags | ON | ON | ON | ON |
| Purposes | `discuss` | `discuss` | `discuss` | `discuss` |
| Campaign | `_send_via_evolution` | same | same | same |

Systemic rollback ends with both channels `shadow`, allowlist empty or fail-closed, flags OFF.

---

## 16. Final execution runbook (activation task only)

```text
A. Backup Production DB → record path/size/exit.
B. Hard gate G1–G11 → abort if any FAIL.
C. Snapshot T0.
D. ICP allowlist = "10,5"; verify parse {10,5}.
E. Confirm #5 still shadow; optional shadow probe = legacy once, hub jobs #5 = 0.
F. #5 wa_outbound_mode = hub; #10 unchanged.
G. Snapshot T1: hub-mode={5,10}.
H. Send Bridge Hub Pilot 01 → verify lineage + exclusivity + isolation.
I. Send Bridge Hub Pilot 02 → same.
J. Send Bridge Hub Pilot 03 → same.
K. Aggregate: +3 #5 Hub jobs; 0 outside {5,10}; #10 healthy.
L. If PASS → Option A (leave both hub) OR Option B (rollback #5 only).
M. If FAIL → #5-only rollback (section 9) or systemic (section 10).
N. Write E2 activation report; stop. Do not start Campaign / Phase 5 / E3.
```

Verification snippet (activation task):

```python
# After each pilot message M on channel 5:
biz = f"discuss:5:{M.id}"
assert Message.search_count([("business_key", "=", biz)]) == 1
assert Out.search_count([("business_key", "=", biz), ("transport_mode", "=", "unified_bridge")]) == 1
assert Log.search([("mail_message_id", "=", M.id)]).send_origin == "hub_unified"
assert Message.search_count([("business_key", "=", f"walog:{log.id}")]) == 0
assert Channel.browse(10).wa_outbound_mode == "hub"
assert _parse_discuss_hub_allowlist(env) == [10, 5]  # or set equal
```

---

## Final recommendation

**`READY TO ACTIVATE E2 SECOND-CHANNEL PILOT`**

Rationale: `#5` shadow ≥10/0; allowlist fail-closed + quarantine available; `#10` Hub soak healthy; flags already ON; no pending unified jobs; Campaign isolated. Activation remains a **separate explicit task** — this document changes nothing in Production.
