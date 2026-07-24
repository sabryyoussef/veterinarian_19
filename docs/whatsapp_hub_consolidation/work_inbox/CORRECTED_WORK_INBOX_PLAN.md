# WhatsApp Work Inbox — Corrected Implementation Plan

**Status:** Approved for Test implementation  
**Date:** 2026-07-24  
**Canonical tree:** `/home/sabry/odoo_base/base_odoo_19/projects/pet_spot_elsahel`  
**Branch:** `feature/wa-work-inbox`  
**Supersedes:** chat-for-every-conversation / auto-noise / `work_created` inbox-state plans

---

## 1. Executive summary

Deliver a **WhatsApp Work Inbox** (OWL triage UI) in `devhub_whatsapp` with context around a focused message, manual Inbox states, and a Create Work wizard that links one or many same-conversation Hub messages to `dev.work.item` via `dev.work.source.message`.

Production is **out of scope** for this delivery.

## 2. Corrections vs prior plan

| ID | Correction |
|----|------------|
| A | Historical messages default **`untriaged`**, not `new`. New ingest → `new`. No bulk flood. |
| B | `inbox_state` is triage only. Work linkage is separate (`work_item_ids` via source messages). After create: default **`actioned`**, wizard may keep **`pending`**. |
| C | Source of truth = `dev.work.source.message` (+ `whatsapp_message_id`). Not a single M2O as SoT. |
| D | Context = before + focus + after; Load older **and** Load newer. |
| E | Multi-select in **context panel** (same `conversation_id`). |
| F | Restore uses `previous_inbox_state` + inbox event audit. |
| G | `media_kind` / `has_media` in **`whatsapp_hub`**. Inbox/work fields in **`devhub_whatsapp`**. |

## 3. Test activation policy (from DB counts)

Test DB `pet_spot_elsahel_test` volumes (2026-07-24):

- total **3731**; d7=278; d30=1182; d90=2962
- with_body=3731; with_att=49

**Recommended / locked policy:**

1. Existing rows → `untriaged` (column default / migration default).
2. Successful **new** ingest create → `new` (via context flag `whatsapp_inbox_admit_new`; never on dedupe update).
3. Historical entry only via **Add to Work Inbox** or Inbox actions from Messages/Conversation.
4. **No** date-cutoff bulk admit (d30 alone is 1182 — would flood the default Inbox).
5. Backfill only `media_kind` / `has_media`.

**Safest activation method:** Prefer policy above. Do not use a date cutoff unless a future ops decision explicitly accepts flooding risk and records the cutoff.

## 4. Work creation default (Dev Hub workflow)

After Create Work from the wizard:

- Default post-create Inbox state: **`actioned`**
- Wizard may keep messages **`pending`** when follow-up is still required
- Linked Work phase/status is shown independently (not an Inbox state)

## 4. Data model

### whatsapp_hub (`whatsapp.message`)

- `media_kind`: none|image|video|audio|document|sticker|reaction|unknown (stored)
- `has_media`: Boolean (stored)

### devhub_whatsapp (`whatsapp.message` inherit)

- `inbox_state`: untriaged|new|pending|ignored|actioned (default untriaged)
- `previous_inbox_state`
- computed: `has_work_item`, `work_item_count`, `primary_work_item_id`, `work_item_ids`
- `dev.whatsapp.inbox.event` audit log

### devhub_work (`dev.work.source.message`)

- `whatsapp_message_id` Many2one nullable, indexed, ondelete=set null

## 5. Module ownership

- `whatsapp_hub`: media classification + soft entry helpers
- `devhub_whatsapp`: Work Inbox OWL, inbox_state, wizard, navigation
- `devhub_work`: additive source-message FK + Open WhatsApp Context

No new bridge module.

## 6. Phases in this delivery

- **Phase 1:** Work Inbox + context window + triage + media chips
- **Phase 2:** Create Work wizard + bi-nav + multi-message + duplicate policy

Out of this delivery: Evolution media download, Campaign/Discuss/outbound changes, Production upgrade.

## 7. Environment

| Role | DB | Service | Port |
|------|-----|---------|------|
| **Test (target)** | `pet_spot_elsahel_test` | `pet_spot_elsahel_test.service` | **8028** |
| Production (excluded) | `pet_spot_elsahel` | `pet_spot_elsahel.service` | 8027 |

## 8. Go/no-go for Production

Not requested. Test UAT + report only; wait for explicit human approval.
