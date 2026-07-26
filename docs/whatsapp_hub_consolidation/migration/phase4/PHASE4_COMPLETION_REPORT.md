# Phase 4 Completion Report — Discuss Shadow + Flagged Hub Cutover

**Date:** 2026-07-23  
**Scope:** Phase 4 only (4A shadow + 4B flagged Discuss cutover)  
**Plan:** [`HUB_PLATFORM_EVOLUTION_PLAN.md`](../../HUB_PLATFORM_EVOLUTION_PLAN.md)  
**Prior:** [`phase3/PHASE3_COMPLETION_REPORT.md`](../phase3/PHASE3_COMPLETION_REPORT.md)

---

## Confirmations

| Constraint | Status |
|------------|--------|
| Campaign send path unchanged | **Confirmed** — still `_send_via_evolution`; UAT H + test 21 |
| No Production upgrade / activation | **Confirmed** — Prod Hub `19.0.1.0.1`, chat `19.0.1.10.1`, bridge `19.0.1.1.1` |
| No global Discuss cutover | **Confirmed** — channel default `legacy`; ICPs OFF |
| All cutover flags OFF after UAT | **Confirmed** — see flags below |
| No Campaign cutover started | **Confirmed** |
| Text-only Hub path | **Confirmed** — attachments rejected in `hub` mode |

**Test flags after UAT:**

```text
whatsapp_hub.unified_outbound_enabled = False
whatsapp_hub.discuss_cutover_enabled = False
whatsapp_hub.unified_outbound_purposes = (empty)
instance.unified_outbound_enabled = False
instance.discuss_cutover_enabled = False
discuss.channel.wa_outbound_mode = legacy (restored)
```

---

## Current Discuss call graph discovered

```text
discuss.channel.message_post
  → super().message_post                    # creates mail.message first
  → guards: skip_wa_outbound / wa_phone / message_type in (comment,email)
            / author is internal user / non-empty body or attachments
  → _send_whatsapp_discuss_message(...)     # Phase 4 single router
       ├─ mode=legacy  → _send_via_evolution once
       │                   → requests.post Evolution sendText/sendMedia
       │                   → _create_wa_log (send_origin=legacy, mail_message_id)
       │                   → wa.message.log create → Hub mirror (walog:{id})
       ├─ mode=shadow  → service_preview_send_message (no enqueue/transport)
       │               → _send_via_evolution once (same as legacy)
       │               → whatsapp.discuss.shadow evidence row
       └─ mode=hub     → prerequisites (global+instance flags)
                       → service_send_message (business_key=discuss:{ch}:{mm})
                       → Hub message + unified_bridge outbound + transport
                       → compatibility wa.message.log (send_origin=hub_unified,
                          hub_message_id) → mirror reuses same Hub message
                       → NEVER _send_via_evolution
```

**Detection:** `wa_phone` set (not enterprise `channel_type='whatsapp'`).  
**Timing:** `mail.message` exists before transport; `wa.message.log` after successful legacy send (or after Hub admit/send for hub mode).  
**Inbound:** `wa_post_inbound` uses `skip_wa_outbound=True` (separate from outbound hooks).  
**Campaign / wizards:** still call `_send_via_evolution` directly (no Discuss wrapper).

---

## Architecture implemented

### Phase 4A — Shadow

- One Discuss orchestration method: `_send_whatsapp_discuss_message`.
- Preview API: `whatsapp.outbound.message.service_preview_send_message` (validation only; no jobs, no Evolution, no idempotency reservation).
- Evidence model: `whatsapp.discuss.shadow` + manager menu “Discuss Shadow Reports”.

### Phase 4B — Flagged Hub cutover

- Channel field `wa_outbound_mode`: `legacy` | `shadow` | `hub` (default `legacy`).
- Hub mode requires **all** of:
  1. `whatsapp_hub.unified_outbound_enabled`
  2. `whatsapp_hub.discuss_cutover_enabled`
  3. instance `unified_outbound_enabled`
  4. instance `discuss_cutover_enabled`
  5. channel `wa_outbound_mode=hub`
- Missing prerequisites → clear pre-admission error; **no silent legacy fallback**.
- Post-admission / transport failure → Hub owns retry; **no legacy fallback**.

---

## Exact files changed

### `whatsapp_hub` → `19.0.1.3.0`

| File | Change |
|------|--------|
| `models/whatsapp_outbound.py` | `service_preview_send_message` |
| `models/whatsapp_discuss_shadow.py` | **New** shadow evidence model |
| `models/whatsapp_message.py` | `discuss_business_key()` |
| `models/whatsapp_conversation.py` | purpose `discuss` |
| `models/whatsapp_instance.py` | `discuss_cutover_enabled` (default False) |
| `models/compat_bridge.py` | purpose=discuss for channels; Hub convergence via `hub_message_id` / `discuss:*` key; never overwrite `discuss:` business_key with `walog:` |
| `models/__init__.py` | import shadow |
| `data/whatsapp_hub_outbound_flags.xml` | ICP `whatsapp_hub.discuss_cutover_enabled=False` |
| `views/whatsapp_discuss_shadow_views.xml` | **New** |
| `views/whatsapp_instance_views.xml` | discuss cutover flag |
| `views/whatsapp_hub_menus.xml` | shadow menu |
| `security/ir.model.access.csv` | shadow ACL (manager RW, user R) |
| `__manifest__.py` | version + views |

### `evolution_whatsapp_chat` → `19.0.1.12.0`

| File | Change |
|------|--------|
| `models/discuss_channel.py` | wrapper, modes, hub/shadow/legacy routing, UX mapping, `skip_wa_outbound` |
| `models/wa_message_log.py` | `mail_message_id`, `hub_message_id`, `send_origin` |
| `models/wa_message_log_hub.py` | sync extra provenance fields |
| `views/discuss_channel_wa_views.xml` | admin channel mode |
| `tests/test_whatsapp_discuss_phase4.py` | **New** Phase 4 tests |
| `tests/__init__.py` | import |
| `__manifest__.py` | version + view |

---

## Routing modes and flag hierarchy

```text
Effective mode = channel.wa_outbound_mode (default legacy)

If mode=hub:
  require global unified + global discuss_cutover
       + instance unified + instance discuss_cutover
  else → fail safely (no transport, no legacy fallback)

If mode=shadow:
  preview Hub candidate → legacy send once → store shadow row

If mode=legacy (or flags OFF with non-hub modes):
  legacy _send_via_evolution only
```

---

## Shadow-mode design and evidence model

Preferred flow (implemented):

```text
Discuss request
→ build Hub candidate (discuss business key, purpose=discuss, instance, JID)
→ service_preview_send_message (no enqueue)
→ legacy _send_via_evolution once
→ wa.message.log mirrors into Hub
→ whatsapp.discuss.shadow compares candidate vs mirrored conversation/purpose/JID
```

Classifications include: `matched`, `unsupported_message_type`, `missing_instance`, `invalid_destination`, `provenance_mismatch`, `conversation_mismatch`, `canonical_identity_mismatch`, `validation_error`, `legacy_only`.

---

## Discuss business identity rule

```text
discuss:{channel_id}:{mail_message_id}
```

- Same Discuss `mail.message` → same Hub business key (idempotent replay).
- New Discuss message → new key.
- Body/timestamps are not the primary key.
- Shadow preview and Hub cutover use the same key.

---

## Canonical message / `wa.message.log` convergence

| Record | Role |
|--------|------|
| `whatsapp.message` | **Canonical** lifecycle authority |
| `wa.message.log` | Compatibility / CRM-Discuss projection |

**Hub-first (cutover):** create Hub message with `discuss:{ch}:{mm}` → create log with `hub_message_id` + `send_origin=hub_unified` → mirror finds Hub message and enriches (`wa_message_log_id`); does **not** replace `discuss:` key with `walog:`.

**Legacy-first:** log creates Hub row with `walog:{id}`; shadow compares conversation/purpose/destination (not requiring equal business keys).

---

## Lifecycle and error mapping

| Hub state | Discuss UX |
|-----------|------------|
| `sent` / delivery sent\|delivered\|read | Success; update `wa_last_outbound` |
| `failed` | Failure note (no credentials) |
| `pending`/`processing` without provider id (e.g. temp fail after `send_now`) | Failure note: Hub will retry; no legacy fallback |
| Pre-admission (flags/type/instance) | Failure note; no Hub job; no legacy fallback when mode=`hub` |

Do **not** report “sent” merely because Hub admitted the message.

---

## Safe fallback policy

| Category | Behavior |
|----------|----------|
| Safe pre-admission (flags off, unsupported type, missing instance) | Error to user; **no** automatic legacy fallback when channel mode is `hub` |
| Post-admission / uncertain transport | Stay on Hub retry/reconciliation; **never** call `_send_via_evolution` |

---

## Supported / unsupported Discuss types

| Type | legacy/shadow | hub |
|------|---------------|-----|
| Plain text | Supported (current Discuss path) | Supported via unified API |
| Attachments / media | Legacy path still text-only (pre-existing); shadow records preview | **Explicit rejection** — no silent text-only send |

---

## Loop and duplicate-prevention strategy

- Hub mode never calls `_send_via_evolution`.
- Compat log create does not send.
- Mirror reuses Hub message via `hub_message_id` / `discuss:*` / `wa_message_log_id`.
- Failure notifications use `skip_wa_outbound` + `message_type=notification`.
- Inbound posts use `skip_wa_outbound`.
- Idempotent Hub replay returns `duplicate=True` without second transport.
- Context guards: `whatsapp_hub_mirroring`, `whatsapp_hub_skip_mirror`.

---

## Tests and results

**DB:** `whatsapp_hub_fresh`

| Suite | Result |
|-------|--------|
| Phase 4 Discuss (`whatsapp_discuss_p4`) | **0 failed, 0 error(s) of 11 tests** |
| Phase 1–3 Hub (`/whatsapp_hub`) | **0 failed, 0 error(s) of 26 tests** |

Evidence: `tests_phase4_discuss.log`, `tests_phase1_3_rerun.log`

---

## UAT evidence (Test only, mocked HTTP/transport)

**DB:** `pet_spot_elsahel_test` (Hub `19.0.1.3.0`, chat `19.0.1.12.0`)  
**File:** `uat_phase4.txt`

| Scenario | Result |
|----------|--------|
| A — Legacy baseline | 1 legacy HTTP, 0 Hub transport, 1 log, 1 Hub mirror, 0 unified jobs |
| B — Shadow | 1 legacy, 0 Hub transport/jobs, shadow `matched`, purpose `discuss` |
| C — Hub text | 0 legacy, 1 Hub transport, 1 Hub message, 1 outbound, 1 compat log linked |
| D — Idempotent replay | `duplicate=True`, 0 extra transport |
| E — Second message | 2 Hub messages, **same conversation** |
| F — Fail + Hub retry | 0 legacy; pending→sent; same message id |
| G — Attachment in hub | 0 legacy, 0 Hub transport |
| H — Campaign regression | `_send_via_evolution` once; 0 Hub transport |
| **UAT_OK** | **True** |

Flags left **OFF**; channel modes restored to `legacy`.

---

## Campaign paths remain unchanged

- `wa.campaign` / wizards still import and call `_send_via_evolution`.
- Return signature of `_send_via_evolution` remains `(success, response, wa_message_id)`.
- Discuss flags do not gate Campaign sends.

---

## Recommendation — limited Production shadow pilot

**Technically ready for a limited Production *shadow* pilot** (channel `wa_outbound_mode=shadow` on 1–2 WA channels only), because:

- Shadow never calls Hub transport or creates Hub outbound jobs.
- Legacy send remains the only transport.
- Evidence is structured and admin-only.
- Rollback = set channel back to `legacy`.

**Not recommended yet:** Production `hub` cutover or global Discuss enablement — needs a defined pilot cohort, monitoring of shadow `matched` rate, and an explicit change window.

**This Phase 4 delivery does not enable any Production pilot.**

---

## Stopped here

- Phase 4 implementation + Test UAT complete.
- **Do not** start Campaign cutover.
- **Do not** upgrade or activate Production.
- **Do not** enable global Discuss cutover.
