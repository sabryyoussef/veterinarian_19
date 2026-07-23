# WhatsApp Hub Consolidation

Canonical addon tree: `base_odoo_19/projects/pet_spot_elsahel`

| Doc | Purpose |
|-----|---------|
| `BASELINE.json` | W-C0 pinned versions / DB matrix |
| `UAT_EVIDENCE.md` | W-C7 fresh + multi-consumer proofs |
| `LIVE_PILOT_REPORT.md` | Live n8n → Hub pilot (Phases 1–12) |
| `COMPAT_AND_RETIREMENT.md` | W-C6 bridges + W-C8 retirement gates |

## Ownership boundary

- **`whatsapp_hub`**: generic Odoo WhatsApp platform (instance, group, contact, conversation, message, outbound).
- **Consumers**: `devhub_whatsapp`, `petspot_wa_intake`, `petspot_clinic_portal`, CRM / `evolution_whatsapp_chat`.
- **Outside Odoo**: Evolution, n8n, Chatwoot, chatwoot_evolution_bridge.

## Safety

- Do not install/upgrade on Production (`pet_spot_elsahel` :8027) until signed off.
- Canonical ingress remains Chatwoot-normalized → `whatsapp.message.service_ingest_normalized`.
