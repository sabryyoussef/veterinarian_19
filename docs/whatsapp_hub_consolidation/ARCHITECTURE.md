# WhatsApp Canonical Architecture (Authoritative)

**Status:** Active reference for future WhatsApp development  
**Date:** 2026-07-23  
**Canonical Odoo tree:** `/home/sabry/odoo_base/base_odoo_19/projects/pet_spot_elsahel`  
**Canonical Odoo module:** `whatsapp_hub`  
**Platform evolution plan:** [`HUB_PLATFORM_EVOLUTION_PLAN.md`](./HUB_PLATFORM_EVOLUTION_PLAN.md)  
**Phase 1–2 completion:** [`migration/phase1_2/PHASE1_2_COMPLETION_REPORT.md`](./migration/phase1_2/PHASE1_2_COMPLETION_REPORT.md)  
**Phase 3 completion (unified outbound API, flags OFF):** [`migration/phase3/PHASE3_COMPLETION_REPORT.md`](./migration/phase3/PHASE3_COMPLETION_REPORT.md)

---

## EXTERNAL TRANSPORT

```text
WhatsApp
  → Evolution API
  → chatwoot_evolution_bridge (/webhook/evolution)
  → Chatwoot (conversation + message)
  → n8n (chatwoot-ai-analysis)
  → normalized event
```

Evolution remains the WhatsApp radio/provider. Chatwoot remains the shared inbox. n8n remains orchestration / AI / routing. None of these are replaced by Odoo.

---

## ODOO CANONICAL LAYER

```text
n8n WhatsApp Hub Ingest
  → POST /whatsapp_hub/ingest  (token auth via integration_bridge_core)
  → whatsapp.message.service_ingest_normalized
  → whatsapp_hub models
```

### Canonical models

| Concern | Model |
|---------|--------|
| Message | `whatsapp.message` |
| Group / JID | `whatsapp.group` |
| Contact / sender | `whatsapp.contact` |
| Conversation | `whatsapp.conversation` |
| Instance | `whatsapp.instance` (sync target; Evolution instance still live in bridge) |
| Outbound queue | `whatsapp.outbound.message` |
| Compat mirror | `whatsapp.hub.compat` |

### Canonical ingress

- HTTP: `/whatsapp_hub/ingest`
- Health: `/whatsapp_hub/health`
- RPC: `whatsapp.message.service_ingest_normalized`

### Deduplication key priority

1. **Prefer Chatwoot message id** when present (stable across Enrichment).
2. Else Evolution / provider message id.
3. Secondary lookup by `chatwoot_message_id` for older rows.
4. Optional: backfill `evolution_message_id` on duplicate when previously empty.

Evolution id is **optional metadata**, never mandatory when Chatwoot id exists.

### Group identity

- Canonical store: `whatsapp.group.jid` (`@g.us`)
- Routing/policy (pilot JIDs, Dev Hub whitelist, clinic filters) stay **outside** Hub

### Conversation identity

- Canonical store: `whatsapp.conversation` keyed by Chatwoot conversation / group
- Discuss channels remain CRM/UI concern in `evolution_whatsapp_chat`

### Outbound contract (intended)

```text
Business module
  → whatsapp_hub outbound API (service_queue_outbound)
  → whatsapp.outbound.message
  → Evolution or Chatwoot adapter
```

**Governed exception (keep):**

```text
Dev Hub
  → devhub_outbox
  → Chatwoot / n8n
```

Do not bypass Chatwoot governance for Dev Hub replies.

Global Production outbound cutover is **not** declared complete; clinic group notify prefers Hub; CRM/campaigns/Discuss/DM/buttons keep existing paths for now.

---

## BUSINESS CONSUMERS

```text
whatsapp_hub
  ├── devhub_whatsapp          (Dev Hub intake policy)
  ├── petspot_wa_intake        (clinic draft intake)
  ├── petspot_clinic_portal    (portal + notify mixin)
  ├── CRM / campaigns          (via evolution_whatsapp_chat)
  └── future consumers
```

### Extension / consumer pattern

1. Call Hub ingest (or receive Hub message id from upstream).
2. Link business record with `whatsapp_message_id` M2O when useful.
3. Keep business rules, whitelist, drafts, campaigns, rewards **outside** Hub.
4. Prefer Hub outbound for new WhatsApp text sends when safe; do not duplicate sends.

---

## COMPATIBILITY MODULES

| Module | Role |
|--------|------|
| `integration_bridge_core` | Tokens, `/bridge/*`, Evolution instance, generic outbound queue, CRM webhook lead path |
| `evolution_whatsapp_chat` | Campaigns, templates, Discuss UI, `wa.message.log`, Hub mirror |
| `petspot_wa_intake` | Clinic business intake + Hub link |

These remain installed. Retirement is separately gated.

---

## MODULES NOT SAFE TO RETIRE

- `evolution_whatsapp_chat` — owns `wa.campaign`, `wa.campaign.line`, `evo.wa.template`, Discuss WA
- `integration_bridge_core` — auth tokens, bridge routes, generic queue, Evolution instance
- `petspot_wa_intake` — clinic HTTP + draft confirm domain
- `petspot_clinic_portal`, `petspot_vet_feedback`, `petspot_campaign_rewards` — business products

---

## PRODUCTION PILOT SCOPE (current)

- Hub ingest **ON** only for: `120363411424964076@g.us` (Testopenclow)
- Dev Hub intake from n8n: **OFF** (observe-only)
- Non-pilot JIDs: unchanged (no Hub ingest)
- Stage 2 expansion: documented separately; **disabled** until explicit approval
