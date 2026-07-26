# Phase 5A — Campaign Hub Foundation — Completion Report

**Date:** 2026-07-23  
**Decision:** P5A foundation implemented  
**Design:** [`PHASE5_CAMPAIGN_HUB_MIGRATION_DESIGN.md`](./PHASE5_CAMPAIGN_HUB_MIGRATION_DESIGN.md)

## Delivered

| Item | Detail |
|------|--------|
| Design doc | `docs/.../phase5_campaign/PHASE5_CAMPAIGN_HUB_MIGRATION_DESIGN.md` |
| Identity | `campaign_business_key(campaign_id, line_id)` → `campaign:{id}:{line_id}` |
| Flags (default OFF) | `whatsapp_hub.campaign_cutover_enabled`, `campaign_hub_allowed_campaign_ids` (empty fail-closed), `max_pending_campaign_jobs=100`, `campaign_admit_batch_size=25` |
| Instance | `whatsapp.instance.campaign_cutover_enabled` (default False) |
| Campaign | `wa.campaign.wa_outbound_mode` ∈ legacy/shadow/hub (default **legacy**) |
| Line soft refs | `hub_message_id`, `hub_outbound_id` |
| Adapter stub | `whatsapp.campaign.hub.routing` — preview/eligibility/backpressure; **never sends** |
| Shadow model | `whatsapp.campaign.shadow` + menu |
| Quarantine | `service_quarantine_campaign(campaign_id)` — purpose=campaign only; Discuss untouched |
| Modules | `whatsapp_hub` **19.0.1.6.0**, `evolution_whatsapp_chat` **19.0.1.15.0** |

## Explicit non-changes

- `_process_campaign_queue` still uses `_send_via_evolution` / bridge queue only
- No Campaign Hub send activated
- Discuss allowlist / #5/#10 / Discuss cutover / E3 health unchanged by this phase’s intent
- Flags remain OFF; allowlist empty

## Tests

- `whatsapp_p5a_campaign`: **0 failed / 10**
- Regression `whatsapp_discuss_p4` + `whatsapp_e1_quarantine`: **0 failed / 23**

## Production upgrade

- Backup: `backups/pet_spot_elsahel_pre_p5a_20260723T142044Z.dump`
- Discuss after: #5=`hub`, #10=`hub`, allowlist=`10,5`, purposes=`discuss` (unchanged)
- Campaign cutover ICP: **False**; allowlist empty; instance #1 `campaign_cutover_enabled` False
- Modules: Hub **19.0.1.6.0**, chat **19.0.1.15.0**

## Next authorized slice

**P5B** — Hub adapter branch in `_process_campaign_queue` (still flags OFF in Production until explicit pilot).
