# P10 — Production WhatsApp Hub Traffic Activation Report

**Executed:** 2026-07-23  
**Final verdict:** **PRODUCTION HUB TRAFFIC PILOT PASS WITH NON-BLOCKERS**  
**Rollback:** **Not required** (n8n routing remains Production Hub + observe-only)

Evidence:

```text
docs/whatsapp_hub_consolidation/migration/p10_traffic_activation/
```

---

## M. Final Verdict

```text
PRODUCTION HUB TRAFFIC PILOT PASS WITH NON-BLOCKERS
```

One approved pilot JID (`Testopenclow`) now persists inbound messages into Production `whatsapp_hub` via the existing Evolution → Bridge → Chatwoot → n8n path, exactly once, without enabling Dev Hub intake or changing non-pilot routing.

### Non-blockers

| Item | Notes |
|------|-------|
| Direct Evolution `sendText` is `fromMe` | Skipped by design (anti-loop). Live path validated via Evolution **webhook contract** (`fromMe:false`) into the bridge — same path real radio inbound uses after Evolution emits `messages.upsert`. |
| `evolution_message_id` empty on Hub row | Chatwoot/n8n payload did not populate Evolution id into Hub fields for this event; Chatwoot id + group JID + text present. Improve mapping later. |
| Bridge health JSON still shows cosmetic `version: 19.0.1.0.0` | Unrelated to P10; module is `19.0.1.1.1`. |

---

## A. Preflight

| Check | Result |
|-------|--------|
| Production service | `active` (`pet_spot_elsahel`) |
| `GET /whatsapp_hub/health` | `{"ok": true}` |
| Hub installed | `19.0.1.0.1` |
| Code pin | `4ce0387` |
| n8n workflow | `chatwoot-ai-analysis` / `gKMYWKVT5FtUAFwB` / **active** |
| Pre-change backup | `/home/sabry/infra/n8n/backups/workflows/chatwoot-ai-analysis-p10-pre-prod-hub-20260723T063751Z.json` |

---

## B. n8n Change

| Item | Value |
|------|-------|
| Workflow | `gKMYWKVT5FtUAFwB` |
| Backup | `…/chatwoot-ai-analysis-p10-pre-prod-hub-20260723T063751Z.json` |
| Hub base URL | **`https://drpaws.ai`** (was `https://devhub-fresh.drpaws.ai`) |
| Bridge token | Production `n8n Default` integration token (not printed) |
| Pilot filter | `WHATSAPP_HUB_PILOT_JIDS=120363411424964076@g.us` |
| Observe-only | `Build Dev Hub Intake Payload` forces `devhub_intake_enabled=false` / `p10_observe_only=true` |
| Hub failure mode | HTTP node `neverError` + `onError: continueRegularOutput` — flow continues if Hub fails |
| Non-pilot groups | Unchanged (Hub IF false → skip) |

Script: `/home/sabry/infra/n8n/scripts/patch-whatsapp-hub-prod-p10.py`  
n8n container recreated to load env.

---

## C. Pilot Source

| Field | Value |
|-------|-------|
| Group name | **Testopenclow** |
| Group JID | `120363411424964076@g.us` |
| Source map | `/home/sabry/nextcloud/group-project-map.json` |
| Company / OP parent | `testing` |
| Chatwoot label | `testopenclow` |
| Known Chatwoot conversation | **69** |
| Routing policy | Hub ingest **on**; Dev Hub intake **off**; legacy OP auto-create still skipped for this JID via existing `DEVHUB_INTAKE_MODE_SKIP` gate |

---

## D. Live Message Evidence

### Path used

```text
Evolution messages.upsert (fromMe=false)
  → chatwoot_evolution_bridge /webhook/evolution
  → Chatwoot conversation 69 / message 14383
  → n8n chatwoot-ai-analysis execution 42636
  → Production POST https://drpaws.ai/whatsapp_hub/ingest
  → whatsapp.message id=3
```

### Trace

| Layer | ID / value |
|-------|------------|
| Marker | `WHATSAPP-HUB-PROD-LIVE-UAT-20260723T064122Z` |
| Group JID | `120363411424964076@g.us` |
| Evolution key id (inject) | `P10PROD1784788882` |
| Bridge result | `conversation_id=69`, `message_id=14383` |
| Chatwoot message ID | **14383** |
| Chatwoot conversation ID | **69** |
| n8n execution | **42636** (finished, marker present, Hub nodes present in run blob) |
| Hub `whatsapp.message` | **id=3** |
| Odoo log | `whatsapp_hub ingested message id=3 group=120363411424964076@g.us cw_msg=14383` |
| HTTP | `POST /whatsapp_hub/ingest` **200** |

Note: An earlier Evolution `sendText` (`…T063900Z`) was `fromMe:true` and correctly did **not** enter Chatwoot/Hub.

---

## E. Canonical Persistence

```text
one inbound Chatwoot message 14383
→ one whatsapp.message id=3
```

---

## F. Idempotency

| Call | Result |
|------|--------|
| Live ingest | row id **3**, `chatwoot_message_id=14383` |
| Replay same `chatwoot_message_id` to Hub | `duplicate=true`, `skipped=true`, `message_id=3` |
| DB count for `chatwoot_message_id=14383` | **1** |

---

## G. Legacy Flow

| Check | Result |
|-------|--------|
| Bridge accepted Evolution webhook | **200** / created Chatwoot message |
| Chatwoot conversation usable | conversation **69** received **14383** |
| Bridge health | `{"ok":true}` on `:3010` |
| Odoo bridge health | **200** |
| Evolution webhook retarget | **Not changed** |

---

## H. Business Side Effects

| Metric | Before inbound | After | Delta |
|--------|----------------|-------|-------|
| `whatsapp_message` | 2 | 3 | **+1** (expected) |
| `petspot_wa_intake` | 12 | 12 | **0** |
| `crm_lead` | 1929 | 1929 | **0** |
| `wa_campaign` | 14 | 14 | **0** |
| modular `dev_whatsapp_intake` | 3 | 3 | **0** |

No duplicate clinic intake / CRM lead / campaign / Dev Hub intake from Hub activation.

---

## I. Failure / Retry Behavior

- Hub HTTP node uses `neverError` + `continueRegularOutput`.
- If Production Hub is down, n8n continues the existing Chatwoot analysis path.
- Hub is **not** a hard dependency for WhatsApp → Chatwoot delivery.
- Retry: re-posting the same Chatwoot message id is idempotent (duplicate).

---

## J. Monitoring Results (pilot window)

| Event | Result |
|-------|--------|
| Auth probe earlier | Hub row 2 (preflight) |
| fromMe sendText | Not ingested (expected) |
| Live inbound pilot | **Success** (Hub id 3 / CW 14383 / exec 42636) |
| Duplicate replay | **Success** (no second row) |
| Hub ingest failures | **0** in this window |

Do **not** expand beyond this JID yet.

---

## K. Rollback Status

```text
n8n rollback NOT required
```

If needed later:

1. Restore backup `chatwoot-ai-analysis-p10-pre-prod-hub-20260723T063751Z.json`, **or**
2. Set `WHATSAPP_HUB_BASE_URL` back to `https://devhub-fresh.drpaws.ai` / clear pilot JIDs, recreate n8n  
3. Keep Production `whatsapp_hub` installed (P9 stays)

---

## L. Production Safety

Confirmed:

- No module uninstall  
- No `-u all`  
- No DB schema changes beyond P9  
- No Evolution webhook retarget  
- No global Hub activation (pilot JID only)  
- No outbound Hub cutover  
- Observe-only (Dev Hub intake forced off)

---

## N. Recommended Expansion (do not auto-enable)

| Stage | Candidates | Notes |
|-------|------------|-------|
| Stage 1 | `120363411424964076@g.us` Testopenclow | **DONE** |
| Stage 2 | Internal admin/dev JIDs (e.g. Dev Needed) | Explicit approval + observe-only first |
| Stage 3 | Selected business groups | Per-JID policy in `group-project-map.json` |
| Stage 4 | All managed JIDs | Only after monitoring clean |

Every group needs an explicit routing policy. Do not default-ingest all WhatsApp groups.

---

## Success Condition

> One real inbound WhatsApp-path message from one approved Production pilot group passes Evolution → Bridge → Chatwoot → n8n, is persisted exactly once in Production `whatsapp_hub`, survives duplicate retry, and causes no duplicate business side effects.

**Status: MET** (with non-blockers above).
