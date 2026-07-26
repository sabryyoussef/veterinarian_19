# Phase 1–2 Completion Report — WhatsApp Hub Canonical Store + Mirror Hardening

**Date:** 2026-07-23  
**Scope:** Phase 1 + Phase 2 only (no Phase 3+)  
**Plan:** [`HUB_PLATFORM_EVOLUTION_PLAN.md`](../HUB_PLATFORM_EVOLUTION_PLAN.md)

---

## Confirmation (hard constraints)

| Constraint | Status |
|------------|--------|
| No outbound cutover (Campaign / Discuss / CRM → Hub send) | **Confirmed** — legacy `_send_via_evolution` / `integration.outbound.queue` unchanged as send paths |
| No Phase 3+ API / cutover flags | **Confirmed** |
| Production sending behavior unchanged | **Confirmed** — Production DB `pet_spot_elsahel` **not** module-upgraded; still on Hub `19.0.1.0.x` schema |
| Test environment upgraded | **Yes** — `pet_spot_elsahel_test` → Hub `19.0.1.1.0`, chat `19.0.1.11.0` |
| Fresh lab DB upgraded | **Yes** — `whatsapp_hub_fresh` |

---

## Exact code changes

### `whatsapp_hub` (19.0.1.0.1 → 19.0.1.1.0)

| File | Change |
|------|--------|
| `models/whatsapp_conversation.py` | Deterministic `resolve_conversation()`; `remote_jid`, `purpose`, `identity_key`, `instance_reference`, `partner_id`; UniqueIndex on `identity_key` |
| `models/whatsapp_message.py` | Provenance + lifecycle fields; `find_canonical_message()`; `apply_delivery_status()`; UniqueIndexes on `business_key`, `wa_message_log_id`, Evolution `(provider, instance_reference, provider_message_id)`; ingest sets `source_app`/`purpose`/`remote_jid`/`business_key` |
| `models/compat_bridge.py` | Full idempotent mirror + status sync; conversation reuse; campaign/channel enrichment; manual `service_backfill_wa_message_logs(dry_run=True)` |
| `models/whatsapp_outbound.py` | Metadata-only: uses conversation resolver + provenance fields on queue create (**send path unchanged**) |
| `views/whatsapp_message_views.xml` | Show new provenance/lifecycle fields |
| `views/whatsapp_conversation_views.xml` | Show identity fields |
| `migrations/19.0.1.1.0/pre-migrate.py` | Audit duplicate `evolution_message_id` groups (log only, no auto-merge) |
| `tests/test_whatsapp_hub_mirror.py` | New Phase 1–2 tests |
| `tests/__init__.py` | Import new tests |
| `__manifest__.py` | Version bump |

### `evolution_whatsapp_chat` (19.0.1.10.1 → 19.0.1.11.0)

| File | Change |
|------|--------|
| `models/wa_message_log.py` | Optional `campaign_id`, `campaign_line_id` for Hub provenance |
| `models/wa_message_log_hub.py` | Mirror on create **and** write; loop guards (`whatsapp_hub_mirroring` / `whatsapp_hub_skip_mirror`) |
| `models/discuss_channel.py` | `_send_via_evolution` / `_create_wa_log` accept optional campaign refs (**HTTP send unchanged**) |
| `models/wa_campaign.py` | Pass `campaign_id` / `campaign_line_id` into log create on immediate send |
| `__manifest__.py` | Version bump |

---

## Models / fields added or changed

### `whatsapp.conversation`

- `remote_jid`, `purpose`, `identity_key`, `instance_reference`, `partner_id`
- API: `normalize_remote_jid`, `resolve_conversation`, `find_or_create_from_payload` → resolver

### `whatsapp.message`

- Lifecycle: `sent_at`, `delivered_at`, `read_at`, `error_message`, `retry_count`
- Identity: `remote_jid`, `business_key`, `client_request_id`
- Provenance: `source_app`, `purpose`, `related_model`, `related_res_id`, `partner_id`, `campaign_id`, `campaign_line_id`, `discuss_channel_id`, `queue_id`
- Kept / reused: `provider`, `provider_message_id`, `evolution_message_id`, `instance_id`, `instance_reference`, `direction`, `state`, `delivery_state`, `wa_message_log_id`, `dedupe_key`

### `wa.message.log`

- `campaign_id`, `campaign_line_id` (optional)

---

## Final canonical identity rules

1. **Inbound Chatwoot/n8n:** `dedupe_key` from Chatwoot account + message id (+ group); `business_key = chatwoot:{account}:{message_id}`; Evolution id is enrich-only.
2. **Evolution provider (when instance known):** uniqueness via `(provider=evolution, instance_reference, provider_message_id)` UniqueIndex.
3. **Legacy mirror:** `business_key = walog:{wa.message.log.id}` + UniqueIndex on `wa_message_log_id` → **one Hub message per log**.
4. **Future outbound business key:** `src:{model}:{res_id}:{client_request_id}` (used by Hub outbound queue metadata today).

Lookup order (`find_canonical_message`):  
`wa_message_log_id` → `business_key` → Evolution `(provider, instance, provider_message_id)` → Evolution id alone → Chatwoot message id → `dedupe_key`.

---

## Final conversation identity rules

```text
identity_key = SHA256( instance_key | normalized_remote_jid | purpose )
instance_key = id:{whatsapp.instance.id} | ref:{instance_name} | default
```

- Same instance + same JID + same purpose → **one** conversation.
- Different instances → isolated.
- Different purposes (`crm` vs `campaign` vs `chatwoot`) → isolated.
- Chatwoot threads still prefer `(chatwoot_account_id, chatwoot_conversation_id)` when present.

Phone digits normalize to `{digits}@s.whatsapp.net`; groups keep `@g.us`.

---

## Idempotency strategy

| Path | Key |
|------|-----|
| Ingest | Existing Chatwoot-preferring `dedupe_key` + `business_key` |
| Mirror create | `wa_message_log_id` / `walog:{id}` |
| Mirror write / status | Update same row via `apply_delivery_status` (forward-only) |
| Provider id later | Enrich `evolution_message_id` on same row |

Repeated mirror / status writes never create a second Hub message for the same log.

---

## Loop-prevention strategy

1. Hub writes during mirror use context `whatsapp_hub_mirroring=True`.
2. `wa.message.log` create/write skips Hub mirror when `whatsapp_hub_mirroring` or `whatsapp_hub_skip_mirror` is set.
3. Mirror **never** calls Evolution / Hub `action_send` / outbound queue.
4. Hub message updates do **not** create `wa.message.log`.

---

## Tests added and results

**DB:** `whatsapp_hub_fresh`  
**Command:** `--test-tags=/whatsapp_hub`  
**Result:** `0 failed, 0 error(s) of 16 tests` (22 including resolver cases in stats)

Coverage includes:

1. Mirror twice → one Hub message  
2. Status update → same Hub message  
3. Provider id backfill → same message  
4. Same JID → one conversation  
5. Different JIDs → different conversations  
6. Same JID different instances → isolated  
7. Campaign refs preserved  
8. Discuss channel id preserved  
9. Mirror does not call outbound HTTP  
10. No recursive Hub↔log loop  
11. Pilot ingest still idempotent  
12. (Campaign/Discuss send path) still `_send_via_evolution` — verified in UAT  

**Note:** `/evolution_whatsapp_chat` suite still has **pre-existing** flaky asserts (`completed` vs `running` when default queue mode finishes immediately). Not introduced by Phase 1–2; outbound still uses bridge queue.

Evidence logs:

- `migration/phase1_2/tests_whatsapp_hub_rerun.log`
- `migration/phase1_2/upgrade_fresh.log`
- `migration/phase1_2/upgrade_test.log`

---

## UAT evidence (Test only)

**DB:** `pet_spot_elsahel_test`  
**File:** `migration/phase1_2/uat_test_shell.txt`

| Check | Result |
|-------|--------|
| Legacy `_send_via_evolution` used (mocked HTTP) | 2 HTTP calls |
| Hub outbound queue untouched | `outbound_delta 0` |
| Two partner messages → 2 Hub msgs | ids 4, 5 |
| Same conversation reused | `unique_conversations 1` |
| Discuss channel preserved | `discuss_channel_id=8` |
| Status → delivered on same Hub row | message 4 |
| Campaign log → Hub campaign refs | `campaign_hub … purpose=campaign` |
| `UAT_OK` | **True** |

No real WhatsApp radio traffic was sent (HTTP mocked).

---

## Duplicate / historical data discovered

| Environment | Finding |
|-------------|---------|
| `pet_spot_elsahel_test` after upgrade | `evo_id_dups=0`, `walog_dups=0`; small baseline (`msg_count` grew after UAT) |
| Production | **Not scanned/upgraded** |

No automatic historical backfill or merge was performed. Manual tool available:

```python
env['whatsapp.hub.compat'].service_backfill_wa_message_logs(limit=200, dry_run=True)
```

---

## Migration / cleanup performed

- Module upgrade on `whatsapp_hub_fresh` and `pet_spot_elsahel_test` only.
- Pre-migrate audit script logs duplicate Evolution ids if any (none on Test).
- **No Production `-u`.**
- **No automatic backfill of historical logs.**

---

## Phase 3 readiness recommendation

**Phase 3 is safe to begin design/implementation of the unified Hub outbound API** (additive, flag-off by default), because:

- Canonical metadata + idempotency keys exist.
- Mirror is reliable and loop-safe.
- Conversation sprawl for new mirrored traffic is fixed.

**Do not enable Campaign/Discuss cutover flags yet** (Phase 4–5). Phase 3 should remain API-only until UAT of the adapter is signed.

---

## Exit criteria checklist

1. Hub metadata for origin/transport — **PASS**  
2. One legacy log → one Hub message — **PASS**  
3. Repeated mirror idempotent — **PASS**  
4. Status updates same row — **PASS**  
5. Conversation sprawl fixed (new traffic) — **PASS**  
6. Same JID/context reuses conversation — **PASS**  
7. Different instances isolated — **PASS**  
8. Pilot ingest works — **PASS**  
9. Campaign/Discuss outbound unchanged — **PASS**  
10. No duplicate sends — **PASS** (UAT)  
11. No recursive sync loop — **PASS**  
12. Tests + Test UAT — **PASS**  

**Stopped after Phase 1 and Phase 2. Phase 3 not started.**
