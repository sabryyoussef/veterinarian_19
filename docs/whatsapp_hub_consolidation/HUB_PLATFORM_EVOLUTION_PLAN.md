# WhatsApp Hub Platform Evolution Plan

**Status:** Plan only — no implementation  
**Date:** 2026-07-23  
**Canonical tree:** `/home/sabry/odoo_base/base_odoo_19/projects/pet_spot_elsahel`  
**Authoritative prior architecture:** [`ARCHITECTURE.md`](./ARCHITECTURE.md), [`FINAL_CONSOLIDATION_REPORT.md`](./FINAL_CONSOLIDATION_REPORT.md)

---

## 1. Executive summary

`whatsapp_hub` is already the **canonical inbound store** for a Production pilot JID, with a working outbound queue used by clinic group notify. CRM product features (campaigns, templates, Discuss partner chat, `wa.message.log`) still live in `evolution_whatsapp_chat` and still send **directly** to Evolution (or via `integration.outbound.queue`), with only a **best-effort create-time mirror** into Hub.

This plan evolves Hub into the **single WhatsApp platform / control plane** for all inbound and outbound traffic **without** uninstalling or replacing `evolution_whatsapp_chat`. That module remains the Campaign + Partner/Discuss **business UX**. `integration_bridge_core` remains the **token/auth + Evolution transport/config** layer (and generic multi-platform queue), unless a later phase proves Hub should call bridge as a pure adapter only.

**Constraint:** Production behavior stays unchanged until explicit feature-flag / cutover activation per path (DM, Discuss, campaign immediate, campaign queue, clinic DM/buttons).

---

## 2. Current architecture discovered (code-backed)

### 2.1 Module dependency map

```text
whatsapp_hub
  depends: base, mail, web, contacts
  soft-uses (no hard depends):
    - integration.bridge.token (HTTP /whatsapp_hub/ingest auth)
    - evolution.instance (config fallback / sync_from_evolution_instance)
    - devhub_whatsapp ingest group (optional ACL)

integration_bridge_core
  depends: base, web, mail, crm, contacts
  owns: tokens, /bridge/*, evolution.instance, integration.outbound.queue
  soft-calls when installed:
    - wa.message.log.update_delivery_status / mark_replied
    - whatsapp.message.update_delivery_status
    - partner._get_or_create_wa_channel → Discuss inbound

evolution_whatsapp_chat  (UI name: "WA Campaign")
  depends: base, mail, crm, contacts, integration_bridge_core, whatsapp_hub
  owns: wa.campaign, wa.campaign.line, evo.wa.template, wa.message.log,
        discuss.channel WA fields, send/bulk wizards
  soft: whatsapp.hub.compat.mirror_wa_message_log on wa.message.log.create

Consumers already on Hub:
  petspot_wa_intake     → depends whatsapp_hub; links whatsapp_message_id
  petspot_clinic_portal → petspot_notify_whatsapp_group prefers Hub outbound
  petspot_campaign_rewards → still integration.outbound.queue + direct Evolution URL
```

**Important finding:** Hub does **not** hard-depend on `integration_bridge_core`, yet Hub outbound (`whatsapp.outbound.message._send_one`) posts **directly** to Evolution `/message/sendText/{instance}` with `requests`. Bridge also owns a parallel generic queue and Evolution config. That is a **dual transport** risk to resolve carefully (prefer: Hub queue → bridge send adapter, keep credentials in one place).

### 2.2 Canonical vs legacy models

| Concern | Canonical (Hub) | Legacy / product |
|---------|-----------------|------------------|
| Message | `whatsapp.message` | `wa.message.log` |
| Group | `whatsapp.group` | (Chatwoot / ICP JIDs) |
| Contact | `whatsapp.contact` (+ optional `partner_id`) | `res.partner` |
| Conversation | `whatsapp.conversation` | `discuss.channel` (WA per partner) |
| Instance | `whatsapp.instance` | `evolution.instance` |
| Outbound queue | `whatsapp.outbound.message` | `integration.outbound.queue` |
| Events | `whatsapp.message.event` | — |
| Campaign | — | `wa.campaign` / `wa.campaign.line` |
| Templates | — | `evo.wa.template` |
| Compat | `whatsapp.hub.compat` (abstract) | mirror on log create |

### 2.3 Inbound entry points (all current)

| Path | Endpoint / method | Writes | Hub? |
|------|-------------------|--------|------|
| Production pilot | Evolution → Chatwoot bridge → n8n → `POST /whatsapp_hub/ingest` → `service_ingest_normalized` | `whatsapp.message` | Yes (pilot JID only) |
| Bridge CRM inbound | `POST /bridge/inbound` → `_handle_evolution` | CRM lead + Discuss `wa_post_inbound` + `wa.message.log` inbound | **No** Hub ingest |
| Bridge native webhook | `POST /bridge/evolution/webhook` | delivery status on log + Hub; `mark_replied` on upsert | Status only |
| Clinic intake | `/petspot/wa/intake` / intake service | business draft + optional Hub link | Partial |
| Dev Hub | `service_ingest_normalized` consumer | Dev Hub work | Not on Production pilot |

### 2.4 Outbound send paths that must eventually route through Hub

| Caller | File / symbol | Mechanism today |
|--------|---------------|-----------------|
| Discuss channel post | `evolution_whatsapp_chat/models/discuss_channel.py` → `_send_via_evolution` | Direct Evolution `sendText`/`sendMedia` |
| Quick send wizard | `whatsapp_send_wizard.py` | Immediate: `_send_via_evolution`; queue: `integration.outbound.queue` |
| Bulk wizard | `whatsapp_bulk_wizard.py` | Same dual path |
| Campaign immediate | `wa_campaign.py` `_process_campaign_queue` | `_send_via_evolution` + media helper |
| Campaign queue/scheduled | same | `integration.outbound.queue.create_outbound_message` |
| Clinic group notify | `petspot_clinic_portal/.../notify_mixin.py` | **Already prefers** `service_queue_outbound` |
| Clinic DM / buttons | same mixin | Direct Evolution (not Hub) |
| Campaign rewards | `petspot_campaign_rewards/.../survey_user_input.py` | `integration.outbound.queue` |
| Hub outbound itself | `whatsapp_hub/.../whatsapp_outbound.py` `_send_one` | Direct Evolution (bypasses bridge queue) |

### 2.5 Campaign lifecycle (as implemented)

1. UX: `wa.campaign` draft → load recipients → `wa.campaign.line` (`pending` / `skipped`).
2. Anti-dupe: prior lines on same campaign; optional `wa.message.log` “contacted recently”.
3. Start: `action_start_campaign` → `_process_campaign_queue`.
4. Immediate: `_send_via_evolution` → `_create_wa_log` → line `sent` + `wa_message_id`.
5. Queue/scheduled: create `integration.outbound.queue` rows; line marked `sent` when **queued** (not when Evolution ACKs) — status semantics diverge from Hub.
6. Delivery/read: Evolution webhook → `wa.message.log.update_delivery_status` (campaign line status sync depends on existing line helpers / reporting, not Hub).
7. Hub: only if `wa.message.log` create triggers `wa_message_log_hub.py` → `compat.mirror_wa_message_log` (immediate path creates log; queue path may log later or not uniformly).

### 2.6 Partner / CRM / Discuss send & receive

**Outbound:** Internal user `message_post` on channel with `wa_phone` → `_send_via_evolution` → log.

**Inbound (legacy CRM path):** `/bridge/inbound` Evolution handler → partner/lead → `wa_post_inbound` → inbound log + `mark_replied`.

**Inbound (platform path):** Chatwoot/n8n → Hub (pilot). Discuss is **not** fed from Hub ingest today.

### 2.7 Compatibility / mirror logic

`evolution_whatsapp_chat/models/wa_message_log_hub.py` inherits `wa.message.log.create` and calls `whatsapp.hub.compat.mirror_wa_message_log`.

`compat_bridge.py` behavior today:

- Match existing Hub row by `evolution_message_id` only.
- Else **create a new** `whatsapp.conversation` every time (no reuse by phone/partner).
- Dedupe key `walog:{id}:{wa_message_id|phone}` — unique per log row.
- Sets `wa_message_log_id` integer on Hub message.
- Does **not** set campaign, Discuss channel, related_model, instance, group JID for DMs, or partner M2O on message.
- Status updates on log do **not** re-enter mirror; delivery uses parallel webhook updates on both models when Evolution id matches.

### 2.8 Message flow maps

**Inbound (pilot):**

```text
WhatsApp → Evolution → chatwoot_evolution_bridge → Chatwoot
  → n8n chatwoot-ai-analysis → POST /whatsapp_hub/ingest
  → whatsapp.message (dedupe Chatwoot id preferred)
```

**Inbound (CRM/Discuss — parallel, not Hub-routed):**

```text
WhatsApp → Evolution → /bridge/inbound → CRM lead + discuss.channel + wa.message.log
```

**Outbound (CRM product — not Hub):**

```text
Campaign / Wizard / Discuss
  → _send_via_evolution OR integration.outbound.queue
  → Evolution
  → wa.message.log (+ optional Hub mirror on create)
```

**Outbound (clinic group — Hub preferred):**

```text
petspot_notify_whatsapp_group
  → whatsapp.outbound.message.service_queue_outbound
  → requests sendText (Hub-owned HTTP)
  → whatsapp.message (direction=out)
```

---

## 3. Target architecture

```text
Business UX (keep):
  evolution_whatsapp_chat  → Campaigns, templates, wizards, Discuss WA, reporting
  petspot_* / future ticket / AI / automations

Platform:
  whatsapp_hub
    - canonical whatsapp.message / group / contact / conversation
    - inbound ingest + routing hooks
    - outbound queue (only WA send admission point for Odoo)
    - delivery/retry/error control plane
    - feature flags for cutover

Transport / auth:
  integration_bridge_core
    - tokens, IP allowlists
    - evolution.instance (source of truth for credentials; Hub syncs)
    - Evolution HTTP adapter used by Hub (preferred end state)
    - non-WA platforms stay on integration.outbound.queue
```

**Target flows:**

```text
IN:  WA → Evolution → Chatwoot/n8n (and/or controlled direct) → Hub ingest
     → Hub routing → CRM / Discuss / intake / AI / ticket handlers

OUT: Business app → Hub service_queue_outbound (flags)
     → whatsapp.outbound.message → bridge Evolution adapter → WA
     → canonical whatsapp.message + optional legacy log mirror for UX
```

Final ownership:

| Layer | Module |
|-------|--------|
| Platform / SoT / routing / WA queue | `whatsapp_hub` |
| Campaign + Partner Discuss UX | `evolution_whatsapp_chat` |
| Transport / auth / Evolution config | `integration_bridge_core` |

---

## 4. Gap analysis

### 4.1 Metadata: can Hub be SoT today?

| Required metadata | Present? | Notes |
|-------------------|----------|-------|
| Provider / Evolution message id | Partial | Inbound improved; outbound sets when send succeeds |
| Evolution instance | Partial | `instance_id` / `instance_reference`; often empty on mirror |
| WhatsApp JID | Partial | `group_jid` / `sender_jid`; DM mirror often phone-only |
| Direction | Yes | `in` / `out` |
| Delivery status | Yes | `delivery_state` + `state` |
| Error status | Partial | On outbound queue, not first-class on message |
| Retry count | On outbound only | Not on `whatsapp.message` |
| Source business model / record | On outbound `related_*` only | **Missing on message** |
| Campaign | **No** | Need M2O or related via line |
| Discuss channel | **No** | |
| CRM partner | Via `whatsapp.contact.partner_id` only | Often unset on ingest/mirror |
| Timestamps | Yes | `message_timestamp`; outbound `sent_at` |
| Chatwoot ids | Yes (inbound) | |
| Idempotency | Yes inbound | Outbound dedupe is weak (`out:{queue_id}:…`) |
| Media | References text only | No first-class media send in Hub outbound |
| Buttons / interactive | **No** | Clinic buttons still direct Evolution |

### 4.2 Structural gaps blocking “central platform”

1. **Multiple Evolution HTTP clients** (`_send_via_evolution`, Hub `_send_one`, clinic mixin, rewards, queue worker).
2. **Two queues** with different semantics (`whatsapp.outbound.message` vs `integration.outbound.queue`).
3. **Mirror creates conversation sprawl** (new conversation per mirrored log).
4. **No Hub routing layer** after ingest (`_on_message_ingested` only writes an event).
5. **Parallel inbound** to Discuss/CRM bypasses Hub → dual SoT for partner chat.
6. **Campaign queue marks line `sent` at enqueue** vs Hub `sent` after HTTP success.
7. **Hub purpose enum** is `clinic|developer|other` — no `crm` / `campaign` / `discuss`.
8. **Feature flags** for per-path cutover do not exist yet.
9. **No link fields** campaign_line / channel / partner on canonical message.
10. **Media / sendButtons** not in Hub outbound API.

### 4.3 Duplicate / loop risks

| Risk | Mechanism | Mitigation in plan |
|------|-----------|--------------------|
| Duplicate Hub rows | Mirror + Hub outbound both create messages for same send | Single admission: either send-via-Hub (creates message) **or** mirror; never both for same Evolution id |
| Duplicate sends | Dual cutover without flag | Feature flag exclusive path |
| Webhook loops | fromMe upsert + outbound | Keep fromMe skip; do not re-ingest own sends as inbound |
| Retry storms | Both queues retry same payload | One queue owns WA retries |
| Mismatched IDs | Queue path without Evolution id until worker runs | Persist provider id back to campaign line + Hub; prefer Evolution id for delivery |
| Conversation duplication | Mirror always creates conversation | Reuse by contact phone / partner / Chatwoot conversation |

---

## 5. Phased implementation plan

### Phase 0 — Architecture audit and dependency map

**Objective:** Freeze a living inventory of deps, send paths, and flags; align team on target boundaries.

**Code / modules affected:** Docs only (+ optional inventory script). No runtime change.

**Models:** None.

**New artifacts:** This plan; optional `migration/platform_evolution/SEND_PATH_INVENTORY.md` generated from grep.

**Migration strategy:** N/A (documentation).

**Backward compatibility:** Full.

**Idempotency / retry / security:** Document current rules only.

**Test plan:** Checklist that every `_send_via_evolution` / `sendText` / `sendMedia` / `sendButtons` / `service_queue_outbound` / `create_outbound_message` path is listed.

**UAT:** Review with ops: pilot JID, n8n workflow, Evolution instances.

**Rollback:** Delete docs.

**Exit criteria:** Approved inventory + agreement that `evolution_whatsapp_chat` stays UX-only and Hub becomes admission control for WA sends.

---

### Phase 1 — Strengthen Hub canonical message model and idempotency

**Objective:** Make `whatsapp.message` rich enough to be SoT for CRM + platform traffic without changing send behavior.

**Modules:** `whatsapp_hub` (primary).

**Models affected:** `whatsapp.message`, `whatsapp.conversation`, `whatsapp.contact`, possibly `whatsapp.outbound.message`.

**Proposed fields / services (illustrative):**

- On `whatsapp.message`:
  - `related_model`, `related_res_id`
  - `partner_id` (related/stored from contact or direct)
  - `campaign_id`, `campaign_line_id` (optional M2O; soft if models absent)
  - `discuss_channel_id` (Integer or Many2one if mail installed — prefer Integer to avoid hard Discuss dep, or use optional inherit in evolution module)
  - `wa_message_log_id` keep; add inverse link on log later
  - `error_message`, `retry_count` (denormalized from outbound)
  - `source_app` Selection: `hub|campaign|discuss|wizard|clinic|rewards|n8n|other`
  - `client_request_id` / `idempotency_key` for outbound admission
- Outbound idempotency: prefer explicit `client_request_id` over body hash.
- Conversation reuse helpers: by Chatwoot id, group JID, contact phone, partner.

**Migration strategy:** Additive columns; post-migrate backfill `partner_id` from contact where possible. No cutover.

**Backward compatibility:** All new fields optional; ingest unchanged.

**Idempotency rules:**

- Inbound: keep Chatwoot-id primary; Evolution enrich-only (already implemented).
- Outbound: unique `(source_app, client_request_id)` when provided; else Evolution id when known; else outbound queue id.

**Retry rules:** Unchanged (still on outbound queue).

**Security:** Managers write new fields; ingest service unchanged; no public exposure of new fields.

**Test plan:** Extend `whatsapp_hub/tests/test_whatsapp_hub_ingest.py` for new fields + conversation reuse + outbound idempotency key.

**UAT:** Hub UI shows new columns empty for old rows; pilot ingest still works.

**Rollback:** Module downgrade / leave columns unused (safe).

**Exit criteria:** Schema + tests green; no Production send-path change; zero duplicate increase on pilot replay.

---

### Phase 2 — Complete legacy outbound mirroring into Hub (no send change)

**Objective:** Every successful legacy send that creates `wa.message.log` becomes a stable Hub row with correct conversation reuse and business links — **without** changing Evolution call sites.

**Modules:** `whatsapp_hub` (`compat_bridge.py`), `evolution_whatsapp_chat` (`wa_message_log_hub.py`, optionally set link fields on log create context).

**Models:** `whatsapp.hub.compat`, `whatsapp.message`, `wa.message.log`.

**Changes:**

- Strengthen `mirror_wa_message_log`:
  - Reuse conversation by partner/phone/DM.
  - Set partner, channel, related_model/res_id from log.
  - If Hub row exists by Evolution id **or** `wa_message_log_id`, update status fields instead of create.
  - Pass campaign line id when available (campaign path should write context on log create).
- Optionally: inherit `write` on `wa.message.log` for delivery_status → Hub (belt-and-suspenders with webhook).
- Feature flag ICP: `whatsapp_hub.mirror_wa_logs` default **True** (already effectively on).

**Migration strategy:** One-shot optional backfill script for recent logs missing Hub rows (manual, dry-run first). Not required for cutover.

**Backward compatibility:** UX unchanged; mirror failures still swallowed.

**Idempotency:** Never two Hub rows for same `wa_message_id` or same `wa_message_log_id`.

**Retry:** N/A.

**Security:** sudo mirror only from trusted create path.

**Test plan:** Unit tests: create log twice → one Hub message; delivery write syncs; conversation count stable.

**UAT:** Send from Discuss + campaign immediate; verify Hub row + single conversation per partner.

**Rollback:** Disable mirror ICP; Hub rows remain (read-only history).

**Exit criteria:** Sample Production/staging sends show ≥99% mirror coverage for new logs with Evolution id; no duplicate Hub messages; campaign UX unchanged.

---

### Phase 3 — Unified Hub outbound service/API (legacy flows still active)

**Objective:** Offer a complete `service_queue_outbound` contract that business modules **can** call, including media, purpose=`crm`/`campaign`/`discuss`, instance selection, client idempotency, and **adapter** to Evolution via bridge config — while legacy paths remain default.

**Modules:** `whatsapp_hub`; thin optional glue in `integration_bridge_core` (adapter method).

**Models:** `whatsapp.outbound.message` (+ media fields), possibly `whatsapp.outbound.media`.

**New service contract (sketch):**

```python
service_queue_outbound({
  destination, body,
  purpose, source_app, client_request_id,
  instance_id?, related_model?, related_res_id?,
  partner_id?, campaign_line_id?, discuss_channel_id?,
  media?: [{type, url, caption}],
  send_now?, priority?,
})
```

**Transport decision (recommended):** Hub queue worker calls a single adapter:

- Prefer `evolution.instance.get_config_*` + shared send helper living in bridge **or** Hub helper that only reads bridge config (avoid third HTTP implementation long-term).
- Do **not** yet delete `_send_via_evolution`.

**Feature flags (ICP / settings):**

- `whatsapp_hub.outbound_api_enabled` (default True for clinic already using it)
- `whatsapp_hub.use_bridge_evolution_adapter` (default False until tested)

**Migration strategy:** Additive API; clinic continues; no campaign/Discuss switch.

**Backward compatibility:** Existing `service_queue_outbound` callers keep working.

**Idempotency:** Enforce `client_request_id` uniqueness when provided.

**Retry:** Keep exponential/backoff on Hub queue; document max_retries; do not dual-enqueue to `integration.outbound.queue`.

**Security:** Keep Hub user/manager ACL; allow service users with explicit group for automation.

**Test plan:** Hub tests for media queue, idempotent requeue, adapter mock HTTP.

**UAT:** Manual Hub UI / RPC send to test number; parity with `_send_via_evolution` text send.

**Rollback:** Flag off adapter; clinic fallback already exists in mixin.

**Exit criteria:** Documented API; tests green; one staging send path proven; **no** default CRM cutover.

---

### Phase 4 — Migrate Partner / CRM / Discuss sends to Hub outbound

**Objective:** Discuss `message_post` and send wizard immediate/queue modes use Hub when flag on; UX identical.

**Modules:** `evolution_whatsapp_chat` (`discuss_channel.py`, `whatsapp_send_wizard.py`, `whatsapp_bulk_wizard.py`).

**Models:** `discuss.channel`, wizards; Hub outbound/message.

**Strategy:**

- Replace `_send_via_evolution` call sites with wrapper `_send_whatsapp(...)` that:
  - If `whatsapp_hub.cutover_discuss` / `cutover_wizard` → Hub `service_queue_outbound` (`source_app=discuss|wizard`, `client_request_id=mail.message id or uuid`).
  - Else legacy `_send_via_evolution`.
- When Hub path used: **skip** creating a second Hub row via mirror **or** make mirror no-op when `wa_message_log` already linked to Hub message (set log → hub id).
- Prefer creating `wa.message.log` from Hub post-send hook for reporting UX continuity (dual-write log as **projection**, Hub as SoT).

**Migration strategy:** Flag per company/ICP; start on staging; then Production DM test partners only if possible.

**Backward compatibility:** Flag off = today’s behavior.

**Idempotency:** `client_request_id` = Discuss mail message id / wizard line id.

**Retry:** Hub queue owns retries; Discuss should not re-post on user retry without new message.

**Security:** Unchanged Discuss ACLs; Hub send ACL must allow same users who can post to WA channels (grant Hub user group to WA operators or sudo inside controlled wrapper).

**Test plan:** Channel post with flag on/off; no double Evolution HTTP (mock); one Hub message; one log.

**UAT:** Partner chat round-trip; delivery status updates Hub + log; no duplicate WhatsApp bubbles.

**Rollback:** Disable cutover flags.

**Exit criteria:** Staging parity; Production flag on for Discuss with zero duplicate incidents over agreed window.

---

### Phase 5 — Migrate WA Campaign sending to Hub outbound (preserve UX)

**Objective:** `wa.campaign` / lines still drive UX and stats; transport becomes Hub queue.

**Modules:** `evolution_whatsapp_chat` (`wa_campaign.py`, `wa_campaign_line.py`); Hub outbound.

**Models:** Add `hub_outbound_id` / `whatsapp_message_id` on `wa.campaign.line` (recommended).

**Strategy:**

- Flag `whatsapp_hub.cutover_campaign_immediate` and `cutover_campaign_queue`.
- Immediate: Hub `send_now` with `campaign_line_id`, rate-limit delay kept in campaign processor.
- Queue/scheduled: enqueue Hub outbound with `next_retry_at` / scheduled field (add `scheduled_at` on Hub outbound if missing) instead of `integration.outbound.queue`.
- Align semantics: line `sent` only after Hub reports sent (or explicit `queued` status on line — prefer add `queued` to line selection for honesty).
- Reporting continues to read line statuses; delivery webhook updates Hub then propagates to line via Evolution id.

**Migration strategy:** Shadow mode optional: enqueue Hub **and** compare, without send (hard); prefer flag cutover on staging campaign only.

**Backward compatibility:** Flag off uses existing `_send_via_evolution` / bridge queue.

**Idempotency:** `client_request_id=campaign_line:{id}` ; anti-dupe business rules stay in campaign module.

**Retry:** Hub retries; campaign should not re-process lines already linked to pending/sent Hub outbound.

**Security:** Campaign managers need Hub send rights or sudo wrapper.

**Test plan:** Existing `test_wa_campaign.py` with flag matrix; no double send.

**UAT:** Small Production campaign to internal numbers; reporting rates match; mirror/log consistent.

**Rollback:** Flag off; unfinished Hub pendings cancel.

**Exit criteria:** Campaign UX unchanged; all new campaign sends create Hub messages; bridge queue no longer used for WA campaign when flags on.

---

### Phase 6 — Centralize retry, delivery status, errors, provider ACKs

**Objective:** Hub is control plane for delivery lifecycle; legacy models become projections.

**Modules:** `whatsapp_hub`, `integration_bridge_core` (webhook), `evolution_whatsapp_chat` (log/line sync).

**Models:** `whatsapp.message`, `whatsapp.outbound.message`, `whatsapp.message.event`; projections to log/line.

**Strategy:**

- Webhook `messages.update` → Hub first → propagate to `wa.message.log` and `wa.campaign.line` by Evolution id.
- Standardize status map (already similar; include SERVER_ACK etc. on both).
- Outbound failures write `error_message` on message; events `status_update`.
- Deprecate dual independent status writers once propagation proven.
- Clinic DM/buttons/rewards: schedule follow-on flags (same pattern as Phase 4–5).

**Migration strategy:** Feature flag `whatsapp_hub.status_authority=hub|legacy|dual` default `dual`, then `hub`.

**Idempotency:** Status transitions only forward (pending→sent→delivered→read; failed terminal unless explicit reset).

**Retry:** Single worker: Hub cron; disable WA processing in `integration.outbound.queue` when cutover complete (keep queue for non-WA platforms).

**Security:** Webhook remains token/IP as today; no widening.

**Test plan:** Simulated webhook sequence; assert Hub + log + line.

**UAT:** Read receipts visible in campaign reporting and Hub.

**Rollback:** `status_authority=dual` or `legacy`.

**Exit criteria:** No status divergence for 7 days on sampled messages; Hub always has Evolution id for outbound successes.

---

### Phase 7 — Central inbound routing from Hub to CRM / Discuss / AI / future ticketing

**Objective:** Hub ingest is the fan-out point; stop parallel silent CRM paths for traffic that should be governed.

**Modules:** `whatsapp_hub` (router service), consumers in `evolution_whatsapp_chat`, `petspot_wa_intake`, future ticket module, n8n remains external AI.

**Models:** New `whatsapp.routing.rule` (optional) or code hooks on `_on_message_ingested`.

**Strategy:**

- Expand ingest beyond pilot via existing n8n JID gates (ops-controlled).
- Router:
  - group JIDs → clinic / Dev Hub policies (stay outside Hub core).
  - DM JIDs → Discuss `wa_post_inbound` + optional CRM lead (move logic from `_handle_evolution` gradually).
- Flag `whatsapp_hub.route_dm_to_discuss`; when on, bridge `_handle_evolution` becomes no-op or Hub-only for those instances to avoid double post.
- Keep Chatwoot as inbox; Hub as Odoo SoT.

**Migration strategy:** Per-instance / per-JID flags; never big-bang all inboxes.

**Idempotency:** Router must be idempotent (`consumer_notified` event per consumer key).

**Retry:** Router failures logged; do not re-create CRM leads on replay (dedupe keys).

**Security:** Router runs as ingest/superuser; business creates respect record rules.

**Test plan:** Ingest DM fixture → one Discuss post; replay → no second post.

**UAT:** Partner replies appear once in Discuss and once in Hub.

**Rollback:** Disable route flags; re-enable bridge handler.

**Exit criteria:** Chosen Production DMs/groups routed only via Hub without duplicate Discuss/CRM posts.

---

### Phase 8 — Remove obsolete duplicate transport logic (after parity + UAT)

**Objective:** Delete or hard-deprecate direct Evolution send helpers **only after** all flags on and UAT signed.

**Modules:** `evolution_whatsapp_chat` (thin wrappers remain calling Hub), `whatsapp_hub` (single adapter), `integration_bridge_core` (WA queue path disabled or adapter-only).

**Do NOT:** uninstall `evolution_whatsapp_chat`; remove Campaign/Discuss UX; remove bridge tokens.

**Remove / quarantine candidates:**

- Direct `requests.post` in Discuss/wizards/campaign (replace with Hub-only wrappers).
- Duplicate status updates once Hub is authority.
- Optional: stop mirroring create if Hub always writes log projection itself.

**Migration strategy:** Dead-code behind `assert flag` → remove in a later release.

**Exit criteria:** Grep shows no business-module Evolution `sendText` except Hub/bridge adapter; UAT checklist signed; rollback still possible via previous release tag.

---

## 6. Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Double WhatsApp send during cutover | Critical | Exclusive feature flags; integration tests asserting single HTTP |
| Conversation / message duplication from weak mirror | High | Phase 1–2 conversation reuse + Evolution id uniqueness |
| Campaign “sent” means queued vs delivered | Medium | Line status model alignment in Phase 5 |
| Credential drift (Hub instance vs evolution.instance) | High | Sync job + prefer bridge as config SoT |
| Discuss loop (inbound posted as user) | Medium | Keep author/internal checks; Hub router posts as partner |
| fromMe outbound appearing as inbound in Hub | Medium | Never ingest fromMe; outbound-only create path |
| ACL: Hub send group missing for CRM users | Medium | Explicit group grant in Phase 4/5 |
| Media/buttons feature gap | Medium | Phase 3 API before cutting clinic buttons |
| Production pilot scope creep | High | Keep JID gates; separate inbound expansion from outbound cutover |

---

## 7. Recommended first implementation phase

**Start with Phase 1 (schema + idempotency), then Phase 2 (mirror hardening)** before any cutover flags.

Rationale from code:

- Mirror already runs but creates fragile Hub rows (new conversation each time, weak business links).
- Cutover without SoT metadata will make debugging duplicates impossible.
- Clinic already uses Hub outbound; CRM does not — mirror parity is the safest bridge to Phase 3–5.

**Do not** start with Phase 4/5 cutover or Phase 8 deletions.

---

## 8. Exact files / modules likely to change

### Phase 1–3 (platform)

- `whatsapp_hub/models/whatsapp_message.py`
- `whatsapp_hub/models/whatsapp_outbound.py`
- `whatsapp_hub/models/whatsapp_conversation.py`
- `whatsapp_hub/models/whatsapp_contact.py`
- `whatsapp_hub/models/compat_bridge.py`
- `whatsapp_hub/models/whatsapp_message_event.py`
- `whatsapp_hub/security/*`
- `whatsapp_hub/views/whatsapp_message_views.xml`
- `whatsapp_hub/tests/test_whatsapp_hub_ingest.py`
- Possibly new: `whatsapp_hub/models/whatsapp_routing.py`, settings/ICP data XML
- `integration_bridge_core/models/evolution_instance.py` (adapter helper)
- `integration_bridge_core/controllers/bridge_unified.py` (status authority later)

### Phase 2 / 4 / 5 (UX module — keep installed)

- `evolution_whatsapp_chat/models/wa_message_log_hub.py`
- `evolution_whatsapp_chat/models/wa_message_log.py`
- `evolution_whatsapp_chat/models/discuss_channel.py` (`_send_via_evolution` wrapper)
- `evolution_whatsapp_chat/models/whatsapp_send_wizard.py`
- `evolution_whatsapp_chat/models/whatsapp_bulk_wizard.py`
- `evolution_whatsapp_chat/models/wa_campaign.py`
- `evolution_whatsapp_chat/models/wa_campaign_line.py`
- `evolution_whatsapp_chat/tests/test_wa_campaign.py`

### Adjacent consumers (later flags)

- `petspot_clinic_portal/models/notify_mixin.py` (DM/buttons)
- `petspot_campaign_rewards/models/survey_user_input.py`
- `petspot_wa_intake/models/petspot_wa_intake.py` (already Hub-aware)

### Docs / ops

- `docs/whatsapp_hub_consolidation/ARCHITECTURE.md` (update after Phase 3)
- n8n `chatwoot-ai-analysis` (inbound JID expansion only — separate approval)

---

## 9. Success criteria checklist (this planning task)

1. Inspected and referenced real implementation — **Yes** (sections 2–4).
2. Dependency and message-flow map from code — **Yes** (§2).
3. Identified all direct Evolution send paths — **Yes** (§2.4).
4. Identified Hub SoT gaps — **Yes** (§4).
5. Safe phased plan with per-phase exit/rollback — **Yes** (§5).
6. Final target ownership clear — **Yes** (§3).
7. No implementation in this task — **Yes**.

---

## 10. Open decisions (resolve before Phase 3 coding)

1. Should Hub **hard-depend** on `integration_bridge_core` for tokens + Evolution config, or keep soft coupling?
2. Is `wa.message.log` long-term a **projection** of Hub (recommended) or a permanent parallel store?
3. Campaign line: add explicit `queued` state vs keep marking `sent` at enqueue?
4. Inbound DM authority: Hub router vs keep `/bridge/inbound` until Phase 7?
5. Media/buttons: in scope for Phase 3 API or Phase 3.1?

---

*End of plan.*
