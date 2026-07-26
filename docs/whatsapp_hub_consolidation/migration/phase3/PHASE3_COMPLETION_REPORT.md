# Phase 3 Completion Report — Unified Hub Outbound API

**Date:** 2026-07-23  
**Scope:** Phase 3 only (no Phase 4/5 cutover)  
**Plan:** [`HUB_PLATFORM_EVOLUTION_PLAN.md`](../../HUB_PLATFORM_EVOLUTION_PLAN.md)  
**Prior:** [`phase1_2/PHASE1_2_COMPLETION_REPORT.md`](../phase1_2/PHASE1_2_COMPLETION_REPORT.md)

---

## Confirmations

| Constraint | Status |
|------------|--------|
| No Campaign / Discuss / CRM cutover to Hub | **Confirmed** — `_send_via_evolution` unchanged |
| No Production cutover / upgrade | **Confirmed** — Prod still Hub `19.0.1.0.1`, bridge `19.0.1.1.1` |
| Feature flags default OFF | **Confirmed** — `whatsapp_hub.unified_outbound_enabled=False`; instance flag default False |
| Phase 1–2 mirror still works | **Confirmed** — UAT scenario E + Hub tests |
| Additive API only | **Confirmed** — `service_send_message` / `service_enqueue_message` |

---

## Architecture implemented

```text
Admin / future business caller (when flags ON)
  → whatsapp.outbound.message.service_send_message / service_enqueue_message
  → validate + admit
  → whatsapp.conversation.resolve_conversation
  → whatsapp.message (canonical, direction=out)
  → whatsapp.outbound.message (transport_mode=unified_bridge)
  → whatsapp.hub.transport.send_text
  → evolution.instance.send_whatsapp_text  (integration_bridge_core)
  → Evolution HTTP (one-shot)
  → enrich same whatsapp.message with provider id / status
```

**Legacy paths unchanged:**

```text
Campaign / Discuss / wizards → _send_via_evolution / integration.outbound.queue
Clinic notify → service_queue_outbound (transport_mode=legacy_direct, Hub HTTP)
```

---

## Exact files changed

### `whatsapp_hub` → `19.0.1.2.0`

| File | Change |
|------|--------|
| `models/whatsapp_outbound.py` | Unified API, flags, lifecycle, dual transport modes |
| `models/transport_adapter.py` | **New** Hub→bridge adapter |
| `models/whatsapp_instance.py` | `unified_outbound_enabled` |
| `models/__init__.py` | Import adapter |
| `data/whatsapp_hub_outbound_flags.xml` | ICP defaults OFF |
| `views/whatsapp_outbound_views.xml` | Trace fields |
| `views/whatsapp_instance_views.xml` | Instance flag |
| `tests/test_whatsapp_hub_unified_outbound.py` | **New** Phase 3 tests |
| `tests/__init__.py` | Import |
| `__manifest__.py` | Version + data file |

### `integration_bridge_core` → `19.0.1.1.2`

| File | Change |
|------|--------|
| `models/evolution_instance.py` | `send_whatsapp_text`, `send_whatsapp_text_for_purpose` (normalized one-shot; no key in return) |
| `__manifest__.py` | Version bump |

---

## Unified outbound API

### Signature

```python
env["whatsapp.outbound.message"].service_send_message({
    "destination": "2010...",          # phone or JID
    "body": "Hello",                   # or text=
    "client_request_id": "unique-1",   # required (or business_key)
    "related_model": "res.partner",    # recommended
    "related_res_id": 123,
    "purpose": "crm",                  # clinic|developer|crm|campaign|discuss|other
    "source_app": "hub",
    "partner_id": 123,
    "campaign_id": False,
    "campaign_line_id": False,
    "discuss_channel_id": False,
    "instance_id": hub_instance_id,    # optional
    "instance_reference": "evo-name",  # optional
    "message_type": "text",
    "send_now": True,                  # default True
    "max_retries": 3,
    "priority": 5,
    "name": "optional label",
    "business_key": False,             # optional explicit key
})

# Queue without immediate send:
env["whatsapp.outbound.message"].service_enqueue_message({...})
```

### Return

```python
{
  "ok": True,
  "duplicate": False|True,
  "message_id": int,
  "outbound_id": int,
  "conversation_id": int,
  "state": "pending"|"sent"|"failed"|...,
  "delivery_state": "...",
  "evolution_message_id": "...",
  "api": "service_send_message",
}
```

### Usage example (Test with flags on)

```python
env["ir.config_parameter"].sudo().set_param(
    "whatsapp_hub.unified_outbound_enabled", "True"
)
inst = env["whatsapp.instance"].browse(ID)
inst.unified_outbound_enabled = True

env["whatsapp.outbound.message"].sudo().service_send_message({
    "destination": "201003670502",
    "body": "Hub Phase 3 smoke",
    "client_request_id": "smoke-001",
    "related_model": "res.partner",
    "related_res_id": partner.id,
    "partner_id": partner.id,
    "purpose": "crm",
    "instance_id": inst.id,
})
```

---

## Canonical lifecycle

| Stage | `whatsapp.outbound.message.state` | `whatsapp.message.state` / `delivery_state` |
|-------|----------------------------------|---------------------------------------------|
| Admitted / queued | `pending` | `queued` / `pending` |
| Sending | `processing` | `queued` / `pending` |
| Transport OK | `sent` | `sent` / `sent` (+ `evolution_message_id`) |
| Temporary fail | `pending` (retry scheduled) | `queued` / `pending` + `error_message` |
| Permanent / max retries | `failed` | `failed` / `failed` |
| Later delivery webhooks | (unchanged) | via existing `update_delivery_status` |

---

## Idempotency rules

1. Prefer explicit `business_key`, else  
   `src:{related_model}:{related_res_id}:{client_request_id}`.
2. Replay with same key → `duplicate=True`, **zero** additional transport calls, same Hub message + outbound job.
3. New `client_request_id` → new message (even if body identical).
4. Body/timestamps are **not** uniqueness keys.
5. UniqueIndex on outbound `business_key` and message `business_key`.

---

## Retry ownership model

| Layer | Role |
|-------|------|
| **Hub** | Owns business intent, `whatsapp.outbound.message` retries (`max_retries`, `next_retry_at`, cron `process_pending`) |
| **Bridge** | One-shot `evolution.instance.send_whatsapp_text` — **no** bridge-queue retry for unified jobs |
| **Legacy clinic** | Still Hub direct HTTP (`legacy_direct`) with Hub retries |
| **Campaign queue** | Still `integration.outbound.queue` retries (unchanged) |

**No dual-retry** on the unified path: Hub does not leave pending bridge queue rows that the bridge cron would also retry.

---

## Hub ↔ bridge boundary

| Concern | Owner |
|---------|-------|
| Admission, validation, idempotency, conversation, canonical message, queue orchestration | `whatsapp_hub` |
| Evolution credentials / instance rows / one-shot HTTP | `integration_bridge_core.evolution.instance` |
| Normalized transport result | Adapter `whatsapp.hub.transport` |

Hub unified path **fails closed** if `evolution.instance` is missing (no silent use of Hub `api_key` for Phase 3 API).

---

## Feature flags / config

| Key | Default | Meaning |
|-----|---------|---------|
| `whatsapp_hub.unified_outbound_enabled` | `False` | Global gate for `service_send_message` |
| `whatsapp_hub.unified_outbound_purposes` | empty | If set (CSV), only listed purposes allowed |
| `whatsapp.instance.unified_outbound_enabled` | `False` | Per-instance gate when `instance_id` supplied |

`service_queue_outbound` (clinic legacy) is **not** gated by these flags.

---

## Message types

| Type | Phase 3 |
|------|---------|
| `text` | **Supported** |
| `media` / image / document / audio / video | Deferred — `ValidationError` |
| `buttons` / `template` | Deferred — `ValidationError` |

---

## Tests and results

**DB:** `whatsapp_hub_fresh`  
**Result:** `0 failed, 0 error(s) of 26 tests` (includes Phase 1–2 + Phase 3)

Evidence: `migration/phase3/tests_whatsapp_hub_rerun.log`

Covered: create message+queue, idempotent replay, new request id, instance isolation, provenance, failure, retry without new message, media reject, flag disabled, legacy `service_queue_outbound` unaffected.

---

## UAT evidence (Test only, mocked transport)

**DB:** `pet_spot_elsahel_test` (upgraded Hub `19.0.1.2.0`, bridge `19.0.1.1.2`)  
**File:** `migration/phase3/uat_phase3.txt`

| Scenario | Result |
|----------|--------|
| A — first API send | 1 message, 1 outbound `unified_bridge`, provider id `UATP3-1`, 1 transport call |
| B — same client_request_id | `duplicate=True`, `calls_delta=0` |
| C — new client_request_id | 2nd message, **same conversation** |
| D — fail then retry | same message id, ends `sent` |
| E — legacy `_send_via_evolution` | HTTP=1, `unified_invoked=0`, mirror Hub message created |
| Flag off blocks | `flag_blocks_when_off True` |
| **UAT_OK** | **True** |

Flags left **OFF** after UAT on Test.

---

## Phase 4 readiness recommendation

**Ready to begin Phase 4 design** (Discuss/Partner wrapper behind a **separate** cutover flag), because:

- Unified API exists and is idempotent.
- Bridge transport boundary is clear.
- Defaults remain OFF; legacy paths proven unchanged.

**Do not enable Phase 4 cutover** until Discuss-specific UAT and an explicit `whatsapp_hub.cutover_discuss` (or equivalent) flag plan is approved.

**Stopped after Phase 3. Phase 4 not started.**
