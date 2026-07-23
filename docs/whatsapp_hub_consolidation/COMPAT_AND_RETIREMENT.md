# WhatsApp Hub — Compatibility & Retirement (W-C6 / W-C8)

## Compatibility bridges (active)

| Legacy | Behavior after consolidation |
|--------|------------------------------|
| `evolution_whatsapp_chat` | Depends on `whatsapp_hub`; mirrors `wa.message.log` → `whatsapp.message` |
| `/bridge/evolution/webhook` | Still public; updates both `wa.message.log` and `whatsapp.message` delivery status |
| `/whatsapp_hub/ingest` | New HTTP wrapper for Chatwoot-normalized events (token auth) |
| `GET /whatsapp_hub/health` | Health probe |
| `devhub_whatsapp.service_ingest_message` | Calls hub ingest first, then Dev Hub intake logic |
| `petspot.wa.intake.create_from_webhook` | Calls hub ingest; stores `whatsapp_message_id` |
| `petspot.notify.mixin` | Prefers hub outbound queue; falls back to direct Evolution |

## W-C8 retirement status (2026-07-23)

**No modules uninstalled on Production.** No release/worktree snapshots deleted.

### Gate checklist (must all be green before any uninstall)

| # | Gate | Status |
|---|------|--------|
| 1 | Hub installed + dual-write / consumer link verified on non-prod | **DONE** — see `UAT_EVIDENCE.md` |
| 2 | Replay twice → one hub row; Dev Hub + clinic link same `whatsapp_message_id` | **DONE** |
| 3 | n8n calls `service_ingest_normalized` or `/whatsapp_hub/ingest` for pilot groups | **DONE (pilot only)** — see `LIVE_PILOT_REPORT.md` |
| 4 | Message counts reconciled on prod-like DB after n8n cutover | **PENDING** |
| 5 | CRM campaign / Discuss UAT green with hub present | **PARTIAL** — outbound wrapper live; full CRM UI UAT after n8n |
| 6 | Signed approval to change Production | **NOT requested** |

### Allowed now (non-prod only)

1. Keep `evolution_whatsapp_chat` as thin meta depending on hub (already).
2. Prefer hub ingest/outbound in all new code.
3. Do **not** uninstall `evolution_whatsapp_chat`, `petspot_wa_intake`, or bridge modules on Production.
4. Do **not** delete git tags / release snapshots used for rollback.

### After gates 3–6 (future, separate approval)

1. Stop writing to legacy-only paths where hub is authoritative.
2. Uninstall empty shells on **non-prod first**, reconcile counts.
3. Only then consider Production change under explicit sign-off.
4. Never delete rollback reference trees.

## Production safety

Production DB `pet_spot_elsahel` (:8027) was **not** modified during this consolidation UAT.  
`whatsapp_hub` remains **absent** on Production.
