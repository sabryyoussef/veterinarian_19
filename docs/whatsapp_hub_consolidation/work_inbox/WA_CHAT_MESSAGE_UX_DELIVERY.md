# WhatsApp Chat Message UX — Delivery Report

**Module:** `whatsapp_hub`
**Version:** `19.0.1.13.0` → `19.0.1.14.0`
**Environments:** implemented + UAT on `pet_spot_elsahel_test`, then upgraded on `pet_spot_elsahel` (Production)
**Date:** 2026-07-26
**Plan:** `wa_chat_message_ux_ddd01ca1.plan.md` (not modified)

---

## 1. Objective

Replace the flat one-row-per-message list as the primary reading experience with a
WhatsApp-like conversation thread, add noise filters, and surface media as
chips/previews — starting from current Hub data (text + refs) and adding
Evolution-backed media preview.

---

## 2. What was delivered (by phase)

### Phase 1 — Readable conversation thread
- New OWL client action **Conversation Chat** (`whatsapp_hub_conversation_chat`):
  bubbles left/right by `direction`, sender labels, consecutive-sender grouping,
  newest page first, **Load older** pagination, focus/scroll to a specific message.
- New API `whatsapp.conversation.get_thread_messages(offset, limit, hide_noise,
  show_hidden, media_filter, before_id, focus_message_id)` returning chronological slices.
- Entry points: Conversation form **Chat** button, Message form/list **Open chat**
  (jumps + focuses the message), Conversations menu, dashboard **Conversations / Chat** link.

### Phase 1 — List improvements (kept for search/ops)
- New field `is_hidden` (+ `action_hide` / `action_unhide` / `action_toggle_hidden`).
- Search filters: **Hide noise** (default on), **Show hidden**, **Text only**,
  **Has media**, **Hide reactions/stickers**; group-by **Conversation** and **Media kind**.
- Messages action now defaults to Hide-noise + group-by-conversation.

### Phase 2 — Media like WhatsApp
- `media_kind` chips in bubbles (image/video/audio/document/sticker/reaction/unknown).
- **Load media preview** button → `action_fetch_media_preview` calls Evolution
  `getBase64FromMediaMessage`, caches bytes on `ir.attachment`, renders inline
  `<img>` / `<audio>` / `<video>` or a download link.
- New controller route `GET /whatsapp_hub/media/<id>` (auth=user, ACL-checked) that
  lazily fetches + streams cached media.
- New M2M `attachment_ids` (`whatsapp_message_ir_attachment_rel`) for the cache.

### Phase 3 — Ingest stores media
- `service_ingest_normalized` now accepts `media_type`, `media_url`,
  `media_base64`/`file_base64`, `mimetype`, `media_filename`; media-only messages
  are no longer skipped as `empty_text` (auto-captioned `[<type>]`), stored via
  `_attach_ingest_media` as an `ir.attachment` with `media_kind`/`has_media` set.

---

## 3. Files changed

| File | Change |
|------|--------|
| `models/whatsapp_message.py` | `is_hidden`, `attachment_ids`, `_noise_domain`, hide actions, `_thread_payload`, Evolution key + media fetch, `ensure_media_attachment`, `action_fetch_media_preview`, `_attach_ingest_media`, ingest media path |
| `models/whatsapp_conversation.py` | `action_open_chat`, `get_thread_messages` |
| `models/whatsapp_hub_dashboard.py` | added **Conversations / Chat** quick action |
| `controllers/whatsapp_ingress.py` | `GET /whatsapp_hub/media/<id>` |
| `views/whatsapp_conversation_views.xml` | Chat header button + `ir.actions.client` |
| `views/whatsapp_message_views.xml` | noise/media/hidden filters, media_kind column, form buttons, attachments widget |
| `views/whatsapp_hub_menus.xml` | Open Chat menu entry |
| `static/src/chat_thread/{chat_thread.js,.xml,.css}` | OWL chat component + template + styles |
| `__manifest__.py` | version bump + register chat assets |
| `tests/test_whatsapp_chat_thread.py` (+ `tests/__init__.py`) | new tests |

---

## 4. Before / After comparison

### 4.1 Reading experience

| Aspect | Before | After |
|--------|--------|-------|
| Primary reading UI | Flat list, 1 row = 1 message, newest-first | Chat thread: bubbles, chronological, sender grouping |
| Related messages | Not threaded | Grouped per conversation with **Load older** |
| Noise (reactions/stickers/empty) | Always shown | Hidden by default (toggle **Hide noise**) |
| Media | Text placeholder / `attachment_references` only | Chip + inline image/audio/video preview on demand |
| Hide a message | Not possible | **Hide** on bubble/form (`is_hidden`) |
| Triage filters | inbound/outbound/group/mention/attachment-ref | + Text only / Has media / Hide reactions-stickers / Show hidden + group-by conversation & media kind |
| Media source | none in Hub | Evolution `getBase64` cached on `ir.attachment`; ingest can store media directly |

### 4.2 Data-driven results (Test DB `pet_spot_elsahel_test`, 5,987 messages, 47 conversations)

Media classification already present across the store:

| media_kind | count |
|-----------|------:|
| none | 4,604 |
| audio | 770 |
| image | 407 |
| reaction | 126 |
| document | 37 |
| video | 32 |
| unknown | 10 |
| sticker | 1 |
| **has_media total** | **1,383** |
| **Evolution-fetchable (id + not none/reaction)** | **1,255** |

Per-conversation, measured through the real `get_thread_messages` API
(flat = old list count; hide_noise = new default thread; media/text = filter tabs):

| Conversation | Flat (before) | Hide-noise (after) | Media | Text-only | Noise removed |
|--------------|-------------:|-------------------:|------:|----------:|--------------:|
| Dev Needed (417) | 3,477 | 3,417 | 809 | 2,668 | 60 (1.7%) |
| Pet spot sahel branch (484) | 496 | 495 | 6 | 490 | 1 (0.2%) |
| Asta development (483) | 419 | 403 | 149 | 270 | 16 (3.8%) |

> Noise removed = reaction/sticker/empty-body messages now suppressed by default.
> The larger practical win is not row count but that **809 media items in Dev Needed
> are now previewable in-thread** instead of appearing as text placeholders, and the
> **Has media / Text only** tabs let an operator jump straight to the 809 vs 2,668.

---

## 5. Tests

`--test-tags=/whatsapp_hub:TestWhatsappChatThread,/whatsapp_hub:TestWhatsappMediaKind`
→ **0 failed, 0 error(s) of 6 tests**.

Covered: thread ordering + noise/hidden exclusion, `action_open_chat` (conversation
and message-focus), hide toggle, ingest-stores-media-base64 (attachment + media_kind).

---

## 6. Rollout notes

- **Test:** `whatsapp_hub` upgraded to 19.0.1.14.0; UAT passed on Dev Needed (3,477 msgs).
- **Production:** upgraded to 19.0.1.14.0. Two pre-existing `devhub_whatsapp` columns
  (`whatsapp_message.inbox_state`, `previous_inbox_state`) were missing on Prod and
  broke message reads; added them (`inbox_state` default `untriaged`, NOT NULL) and
  confirmed `get_thread_messages` returns rows. Both instances healthy (HTTP 200).
- No Campaign `wa.message.log` UI, Discuss cutover, or outbound-media changes (out of scope).

---

## 7. Out of scope (per plan)

- Multi-vendor `vendors[]`, loyalty, review submission UI.
- Full outbound media send.
- Discuss channel UI cutover.
- Backfilling historical Chatwoot-only media (no Evolution id → stays as chip).
