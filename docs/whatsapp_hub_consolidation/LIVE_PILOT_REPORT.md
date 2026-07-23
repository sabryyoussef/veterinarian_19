# WhatsApp Hub Live Pilot — Implementation Report

**Date:** 2026-07-23  
**Scope:** Non-production only. Production DB `pet_spot_elsahel` untouched (`whatsapp_hub` absent).

---

## A. n8n Integration

| Item | Value |
|------|-------|
| Workflow | `chatwoot-ai-analysis` |
| Workflow ID | `gKMYWKVT5FtUAFwB` |
| Active | yes |
| Backup | `/home/sabry/infra/n8n/backups/workflows/chatwoot-ai-analysis-hub-ingest-20260723T045647Z.json` |
| Patch script | `/home/sabry/infra/n8n/scripts/patch-whatsapp-hub-ingest.py` |

**Nodes added**

- `Build Hub Payload`
- `IF: Hub Pilot Scope`
- `WhatsApp Hub Ingest` → `POST {WHATSAPP_HUB_BASE_URL}/whatsapp_hub/ingest`
- `Merge Hub Result`
- `Hub Skip Passthrough`
- `Build Dev Hub Intake Payload`
- `IF: Dev Hub Intake Scope`
- `Dev Hub Intake RPC` (jsonrpc; timeout raised to 180s)
- `Merge Dev Hub Intake Result` / `Dev Hub Intake Skip`

**Routing scope**

- Pilot JID only: `120363411424964076@g.us` (`testopenclow`) via `WHATSAPP_HUB_PILOT_JIDS`
- Non-pilot → unchanged path (Hub nodes skipped)
- Hub target: `https://devhub-fresh.drpaws.ai` → modular DB `devhub_modular_fresh` (:8032)
- `DEVHUB_INTAKE_MODE_SKIP` preserved in `Evaluate Auto-Create Gates`

---

## B. Live WhatsApp UAT

| Item | Value |
|------|-------|
| Pilot group | `testopenclow` / `Testopenclow` |
| Pilot JID | `120363411424964076@g.us` |
| Marker | `DEVHUB-HUB-LIVE-UAT-20260723T045800Z` |
| Evolution message id | `3EB06F16F9CF75616B1222` |
| Chatwoot account / conv / msg | `2` / `69` / `14381` |
| n8n cw-ai execution | `42232` |
| Hub `whatsapp.message` id | **5** |

**Path traced**

```text
WhatsApp (Evolution send_text to pilot group — real WA message id)
  → Evolution store (message present in history)
  → n8n Evolution webhook (MESSAGES_UPSERT replay as inbound for pilot;
       native fromMe API send did not fire webhook — see Blockers)
  → Bridge → Chatwoot message 14381 (incoming)
  → n8n chatwoot-ai-analysis exec 42232
  → WhatsApp Hub Ingest → whatsapp.message id=5
```

**Evidence types**

| Step | Type |
|------|------|
| WA message body + Evolution id | **Live** (sent via Evolution MCP; stored in Evolution) |
| Chatwoot + n8n Hub ingest | **Live pipeline** after Evolution webhook delivery of that message |
| Dev Hub intake M2O link | **Post-pipeline** (RPC timeout through Cloudflare; linked on modular DB) |

---

## C. Canonical Message Proof

```text
one inbound Chatwoot message 14381
→ one whatsapp.message (id=5)
→ hub_count for chatwoot_message_id=14381 = 1
→ replay → duplicate: true
```

n8n node result (`42232`):

```json
{"ok": true, "message_id": 5, "conversation_id": 3, "group_id": 1, "contact_id": 2, "duplicate": false}
```

---

## D. Dev Hub Consumer Proof

| Item | Value |
|------|-------|
| Intake id | `20` (`awaiting_confirm`) |
| `whatsapp_message_id` | `5` |
| Source JID | `120363411424964076@g.us` |
| OpenProject auto-create | **blocked** |

Gate result from exec `42232`:

```json
{
  "gate_failures": ["devhub_intake_mode", "not_actionable:request_type=other", "low_confidence:0.45<0.75"],
  "auto_create_eligible": false
}
```

`devhub_intake_mode` proves `DEVHUB_INTAKE_MODE_SKIP` still active for the pilot JID.

Note: n8n `Dev Hub Intake RPC` timed out at 60s via Cloudflare on first run (timeout now 180s). Intake event for message 14381 was recorded against open intake `20` (same Chatwoot conversation grouping). Hub link set on intake `20`.

---

## E. Clinic Consumer Proof

On `pet_spot_elsahel_test` (replayed controlled event, not Production):

```json
{
  "hub": {"message_id": 3, "duplicate": false},
  "clinic_id": 18,
  "clinic_wa": 3,
  "dup": true,
  "count": 1
}
```

---

## F. Idempotency

- Hub replay for cw `14381` → `duplicate: true`, count `1`
- Intake replay → `skipped: duplicate_message`
- Unit tests: idempotent ingest green (see I)

Also fixed: dedupe now prefers Chatwoot message id so adding Evolution id later does not create a second hub row (`whatsapp_hub` 19.0.1.0.1).

---

## G. `petspot_campaign_rewards` Fix

| Item | Detail |
|------|--------|
| Root cause | Stale settings view still referenced `campaign_phone_marassi` after field rename to `campaign_phone_haram` |
| Fix | Legacy alias field `campaign_phone_marassi` on `res.config.settings` mapping to the same ICP as Haram phone (`social_media_connector` 19.0.1.0.1) |
| Files | `social_media_connector/models/res_config_settings.py`, `__manifest__.py` |
| Upgrade | `-u social_media_connector,petspot_campaign_rewards` on `pet_spot_elsahel_test` → **EXIT 0** |

---

## H. Dev Hub Seed Conflict Fix

| Item | Detail |
|------|--------|
| Root cause | Orphan `dev.policy` row for modular-fresh scope without `ir.model.data`; seed recreate hit unique scope constraint |
| Fix | (1) Linked XML ID for existing policy; (2) `DevPolicy.create` upserts by scope during `install_mode`/`module` context (`devhub_core` 19.0.9.0.1) |
| Upgrade | `-u whatsapp_hub,devhub_whatsapp,devhub_core` (+ cascade `dev_session_hub` seed) → **EXIT 0**, seed loads clean |

---

## I. Test Results

| Suite | Passed | Failed | Errors | Skipped |
|-------|--------|--------|--------|---------|
| `/whatsapp_hub` on `whatsapp_hub_fresh` | 3 | **0** | **0** | 0 |
| `/devhub_whatsapp,/whatsapp_hub` on `devhub_modular_fresh` | 7 | **0** | **0** | 0 |

Logs: `tests_whatsapp_hub_live.log`, `tests_devhub_whatsapp_live.log`

---

## J. Screenshots / Evidence Paths

| Path | Content |
|------|---------|
| `docs/whatsapp_hub_consolidation/live_pilot/n8n_exec_42232_hub_nodes.json` | Hub ingest node results |
| `docs/whatsapp_hub_consolidation/live_pilot/gate_result.json` | OP skip gate (`devhub_intake_mode`) |
| `infra/n8n/backups/workflows/chatwoot-ai-analysis-hub-ingest-20260723T045647Z.json` | Workflow backup |
| `docs/whatsapp_hub_consolidation/upgrade_campaign_rewards_fix.log` | Campaign upgrade |
| `docs/whatsapp_hub_consolidation/upgrade_hub_dedupe_intake.log` | Seed/hub upgrade |

(Browser screenshots skipped — Playwright Chromium binary missing on host.)

---

## K. Production Safety Confirmation

- DB `pet_spot_elsahel`: **no** `whatsapp_hub` module
- No Production Odoo upgrades
- Hub ingest env points at `devhub-fresh.drpaws.ai` / modular fresh only
- Pilot JID allowlist only — other groups unchanged

---

## L. Remaining Blockers / Follow-ups

1. **Evolution `fromMe` API sends** do not emit MESSAGES_UPSERT to n8n when `WHATSAPP_ALLOW_FROM_ME_FOR_TEST=false`. Live UAT used the real WA message id, then delivered via Evolution webhook as inbound for the pilot. Prefer a second-phone inbound send for the next UAT.
2. **Dev Hub Intake RPC via Cloudflare** was slow (first attempt timed out at 60s). Timeout raised to 180s; consider host-local URL for modular when Docker can reach it.
3. **Late execution syntax error** in Arabic gate-fail note string (pre-existing) after Hub succeeded — does not block Hub ingest.
4. n8n → Dev Hub intake should return `whatsapp_message_id` on duplicate path (field now exists; duplicate early-return still omits M2O in JSON — minor).

---

## Primary success condition

**Met:** A WhatsApp message with marker `DEVHUB-HUB-LIVE-UAT-20260723T045800Z` reached Chatwoot (`14381`), was ingested by n8n into `whatsapp_hub` as **exactly one** `whatsapp.message` (`id=5`), is linked from Dev Hub intake (`20`), and legacy OpenProject auto-create remained blocked (`devhub_intake_mode`).
