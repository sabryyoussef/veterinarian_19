# Chatwoot Evolution Error Bridge — Odoo 19 Module

> **`chatwoot_evolution_error_bridge`** · version 19.0.1.0.1 · license LGPL-3  
> Depends on: `integration_bridge_core`

Backward-compatible bridge that lets **existing n8n / Chatwoot workflows keep working without any changes** after migrating from Odoo 18 (which had an `error.report` model) to Odoo 19 (which uses `crm.lead` + `res.partner` instead).

All `/bridge/error_reports` routes now silently create/update CRM leads, returning the same response shape the old routes returned.

---

## Table of Contents

1. [Feature Overview](#1-feature-overview)
2. [Architecture](#2-architecture)
3. [Folder Structure](#3-folder-structure)
4. [Installation](#4-installation)
5. [Setup Guide (step-by-step)](#5-setup-guide-step-by-step)
6. [API Reference](#6-api-reference)
7. [Use Case Scenarios](#7-use-case-scenarios)
8. [Configuration Reference](#8-configuration-reference)
9. [Data Model](#9-data-model)
10. [Enhancement Roadmap](#10-enhancement-roadmap)

---

## 1. Feature Overview

| Feature | Status | Description |
|---|---|---|
| Legacy endpoint compatibility | ✅ Live | `/bridge/error_reports` routes work unchanged for n8n/Chatwoot |
| CRM lead creation | ✅ Live | POST → creates `crm.lead` with Chatwoot tracking fields |
| Duplicate detection | ✅ Live | Checks `x_external_ref` before creating; returns existing lead |
| Status update | ✅ Live | POST `/<id>/status` maps legacy status → CRM stage |
| Lead detail retrieval | ✅ Live | GET `/<id>` returns lead in old `error_report` format |
| Reply message | ✅ Live | GET `/<id>/reply_message` returns formatted WhatsApp text |
| Chatwoot tracking fields | ✅ Live | Extends `crm.lead` with `x_chatwoot_*` fields |
| Token + IP auth | ✅ Live | `X-Bridge-Token` header + IP whitelist (from `integration_bridge_core`) |
| Health check | ✅ Live | GET `/bridge/health` returns module status |
| Settings UI | ✅ Live | Configurable via `res.config.settings` |

---

## 2. Architecture

```
Existing n8n workflow (Odoo 18 era)
    │
    │  POST /bridge/error_reports         ← same URL as before
    │  Header: X-Bridge-Token: xxx
    │
    ▼
ChatwootBridgeAPI controller
    │
    ├── validate_bridge_token() decorator
    │       └─ checks ir.config_parameter: integration_bridge.master_token
    │          checks ip_whitelist
    │
    ├── _find_or_create_partner(phone, name, email)
    │
    ├── duplicate check via x_external_ref = "CW-{conversation_id}"
    │
    └── crm.lead.create(vals)
            │  x_source_platform = 'chatwoot'
            │  x_chatwoot_conversation_id
            │  x_chatwoot_account_id / inbox_id / contact_id
            │  x_reporter_phone / name / email
            │  x_external_ref = "CW-{conversation_id}"
            │
            └── response same shape as old error.report endpoint:
                {
                  "success": true,
                  "error_id": 42,
                  "error_number": "CRM-00042",
                  "odoo_url": "/web#id=42&model=crm.lead&view_type=form",
                  ...
                }
```

---

## 3. Folder Structure

```
chatwoot_evolution_error_bridge/
│
├── __init__.py
├── __manifest__.py                             # application=False (extension module)
├── README.md                                   # this file
│
├── controllers/
│   ├── __init__.py
│   └── bridge_api.py                           # Backward-compat /bridge/error_reports routes
│
├── models/
│   ├── __init__.py
│   ├── crm_lead.py                             # Extends crm.lead with x_chatwoot_* fields
│   └── res_config_settings.py                  # Extends settings with Chatwoot config
│
├── views/
│   ├── crm_lead_chatwoot_views.xml             # Chatwoot tab on CRM lead form
│   └── res_config_settings_views.xml           # Settings section
│
├── data/
│   └── system_parameters.xml                   # Default ir.config_parameter values
│
├── security/
│   └── ir.model.access.csv
│
├── migrations/
│   └── 19.0.1.0.0/pre-migrate.py
│
└── static/
    └── description/
        └── index.html                          # Odoo App Store description
```

---

## 4. Installation

### Prerequisites
- `integration_bridge_core` installed and configured (master token set).
- Chatwoot and/or n8n already calling `/bridge/error_reports`.

```bash
python odoo-bin -c odoo.conf -u chatwoot_evolution_error_bridge --stop-after-init
```

No additional setup needed for existing workflows — they will start creating CRM leads instead of error reports immediately.

---

## 5. Setup Guide (step-by-step)

### Step 1 — Ensure master token is set

The `X-Bridge-Token` header is validated against `integration_bridge.master_token`.  
Set it in: **Integration Bridge → Configuration → Settings → Master Token**.

> If you were using the old `chatwoot_bridge.token` parameter, the controller reads both as fallback:
> `integration_bridge.master_token` → fallback → `chatwoot_bridge.token`

### Step 2 — (Optional) Migrate n8n nodes to new master token

If the old `chatwoot_bridge.token` was a different value, update n8n HTTP nodes to send the new master token, or keep the old parameter key with the same value.

### Step 3 — Verify CRM lead fields appear

1. CRM → Pipeline → open any lead.
2. Look for the **Chatwoot** tab on the lead form.
3. Fields: Source Platform, WA Phone, WA Push Name, Chatwoot Conversation ID, etc.

### Step 4 — Test with curl

```bash
curl -X POST https://your-odoo.com/bridge/error_reports \
  -H "Content-Type: application/json" \
  -H "X-Bridge-Token: your-master-token" \
  -d '{
    "name": "Test Lead",
    "description": "Test from curl",
    "reporter": {
      "phone": "+201234567890",
      "name": "Ahmed Hassan",
      "email": "ahmed@example.com"
    },
    "chatwoot": {
      "conversation_id": "TEST-001",
      "account_id": "5",
      "inbox_id": "2"
    }
  }'
```

Expected response:
```json
{
  "success": true,
  "error_id": 42,
  "error_number": "CRM-00042",
  "odoo_url": "/web#id=42&model=crm.lead&view_type=form",
  "external_ref": "CW-TEST-001",
  "chatwoot_conversation_id": "TEST-001",
  "message": "Lead created successfully"
}
```

### Step 5 — Verify health check

```bash
curl https://your-odoo.com/bridge/health
# → {"status": "ok", "module": "chatwoot_evolution_error_bridge", ...}
```

---

## 6. API Reference

### POST /bridge/error_reports

Create a CRM lead from a Chatwoot/WhatsApp conversation.

**Auth:** `X-Bridge-Token: <master-token>` header

**Request:**
```json
{
  "name": "Lead title (optional)",
  "description": "Problem description",
  "reporter": {
    "phone": "+201234567890",
    "name": "Contact name",
    "email": "contact@example.com"
  },
  "chatwoot": {
    "conversation_id": "1234",
    "account_id": "5",
    "inbox_id": "2",
    "contact_id": "89",
    "message_id": "555"
  }
}
```

**Response (new lead):**
```json
{
  "success": true,
  "error_id": 42,
  "error_number": "CRM-00042",
  "odoo_url": "/web#id=42&model=crm.lead&view_type=form",
  "external_ref": "CW-1234",
  "chatwoot_conversation_id": "1234",
  "message": "Lead created successfully"
}
```

**Response (duplicate):**
```json
{
  "success": true,
  "duplicate": true,
  "error_id": 42,
  "error_number": "CRM-00042",
  "message": "Lead already exists for this conversation"
}
```

---

### POST /bridge/error_reports/{id}/status

Update CRM lead stage + add a chatter note.

**Request:**
```json
{
  "status": "in_progress",
  "note": "Agent is working on it"
}
```

**Status mapping:**

| Old status | CRM stage (matched by name) |
|---|---|
| `new` | New |
| `in_progress` | Contacted |
| `fixed` | Won |
| `wont_fix` | Lost |
| `duplicate` | Lost |

---

### GET /bridge/error_reports/{id}

Return CRM lead detail in the old `error_report` format.

**Response:**
```json
{
  "success": true,
  "error": {
    "id": 42,
    "error_number": "CRM-00042",
    "name": "Lead title",
    "description": "...",
    "status": "Contacted",
    "reporter_name": "Ahmed Hassan",
    "reporter_phone": "201234567890",
    "reporter_email": "ahmed@example.com",
    "chatwoot_conversation_id": "1234",
    "external_ref": "CW-1234",
    "odoo_url": "/web#id=42&model=crm.lead&view_type=form",
    "created_at": "2025-01-15T10:30:00"
  }
}
```

---

### GET /bridge/error_reports/{id}/reply_message

Return a formatted WhatsApp/Chatwoot reply message string.

**Response:**
```json
{
  "success": true,
  "error_id": 42,
  "message": "✅ *Lead Updated*\n\n*Ref:* CRM-00042\n*Stage:* Contacted\n*Lead:* ...\n\nOur team will follow up with you shortly. 🙏",
  "conversation_id": "1234"
}
```

---

### GET /bridge/health

```json
{
  "status": "ok",
  "module": "chatwoot_evolution_error_bridge",
  "version": "19.0.1.0.0",
  "odoo": "19"
}
```

---

## 7. Use Case Scenarios

### Scenario A — Zero-change migration from Odoo 18

**Context:** You had a working Odoo 18 setup with `error_reporter_16` model and n8n calling `/bridge/error_reports`. You upgraded to Odoo 19 and the old model no longer exists.

**Solution:**
1. Install `chatwoot_evolution_error_bridge`.
2. Set the master token to the same value as the old `chatwoot_bridge.token`.
3. n8n workflows continue to call the same endpoint with the same payload → CRM leads are created instead of `error.report` records.
4. All old response fields (`error_id`, `error_number`, `odoo_url`) are preserved in the response, so downstream n8n nodes don't need updating.

---

### Scenario B — Chatwoot agent marks conversation resolved → update Odoo lead

**Context:** When a Chatwoot agent resolves a conversation, n8n sends a status update to Odoo.

**n8n node:**
```
POST /bridge/error_reports/{odoo_lead_id}/status
{
  "status": "fixed",
  "note": "Issue resolved by agent Sara"
}
```

**Result:** CRM lead is moved to "Won" stage; chatter note "Status Update via Bridge API: Issue resolved by agent Sara" is added.

---

### Scenario C — n8n polls Odoo for lead details to send a WhatsApp reply

**Context:** n8n needs to compose a WhatsApp reply message for a lead.

**n8n node:**
```
GET /bridge/error_reports/{odoo_lead_id}/reply_message
```

**Result:** n8n receives a ready-to-send formatted message like:
```
✅ Lead Updated

Ref: CRM-00042
Stage: Contacted
Lead: Chatwoot — Ahmed Hassan

Our team will follow up with you shortly. 🙏
```

n8n sends this directly to Chatwoot API or Evolution API without reformatting.

---

### Scenario D — Duplicate conversation detection

**Context:** The same Chatwoot conversation fires the webhook twice (retry logic).

**Behaviour:**
- First call → creates lead #42 with `x_external_ref = "CW-1234"`.
- Second call → duplicate check finds lead #42 → returns `{ "duplicate": true, "error_id": 42 }`.

n8n receives the `error_id` in both cases and can proceed identically.

---

## 8. Configuration Reference

### System Parameters

| Key | Default | Description |
|---|---|---|
| `integration_bridge.master_token` | *(empty)* | Master auth token (primary) |
| `chatwoot_bridge.token` | *(empty)* | Legacy token key (fallback) |
| `integration_bridge.ip_whitelist` | *(empty)* | Comma-separated allowed IPs |
| `chatwoot_bridge.cors_origins` | `*` | CORS allowed origins |

---

## 9. Data Model

### `crm.lead` extensions (added by this module)

| Field | Type | Description |
|---|---|---|
| x_source_platform | Selection | whatsapp / chatwoot / evolution / web / other |
| x_reporter_phone | Char | WhatsApp phone (sanitized, no `+` or `@...`) |
| x_reporter_name | Char | WhatsApp `pushName` from Evolution |
| x_reporter_email | Char | Email from Chatwoot contact |
| x_chatwoot_account_id | Char | Chatwoot account ID |
| x_chatwoot_inbox_id | Char | Chatwoot inbox ID |
| x_chatwoot_conversation_id | Char | Chatwoot conversation ID (indexed) |
| x_chatwoot_contact_id | Char | Chatwoot contact ID |
| x_chatwoot_message_id | Char | Last Chatwoot message ID |
| x_chatwoot_payload | Text | Full Chatwoot payload JSON |
| x_external_ref | Char | Unique external ref (`CW-{conv_id}`) — dedupe key |

### Auto-generated values

- `x_external_ref` is auto-set to `CW-{x_chatwoot_conversation_id}` on create if not provided.
- `x_external_ref` has a uniqueness constraint — duplicate webhook calls are detected cleanly.

---

## 10. Enhancement Roadmap

### Chatwoot → Odoo real-time sync

Currently updates are push-only (Chatwoot calls Odoo). Enhancement: add a cron job that polls Chatwoot API for conversation status changes and syncs them to the lead stage without relying on n8n.

### Chatwoot assignment sync

When a CRM lead is assigned to a user in Odoo, automatically assign the Chatwoot conversation to the corresponding Chatwoot agent via the Chatwoot API.

### Conversation history pull

Add a method that fetches full Chatwoot conversation history for a lead and displays it in a dedicated Odoo chatter thread.

### Evolution API conversation status push

When the CRM lead stage changes, automatically post a status update message back to the WhatsApp conversation via Evolution API.

### Inbound media handling

Currently only text messages are stored. Enhancement: download media from Evolution API (images, PDFs, voice messages) and attach them to the CRM lead as `ir.attachment`.

---

*Last updated: 2026-04-04 — aligned with version 19.0.1.0.1*
