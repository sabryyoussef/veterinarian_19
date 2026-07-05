# Integration Bridge Core — Odoo 19 Module

> **`integration_bridge_core`** · version 19.0.1.0.5 · license LGPL-3

Universal integration layer that connects external messaging and automation platforms to Odoo 19 CRM.  
Acts as the **shared foundation** for all channel-specific modules (WhatsApp, Chatwoot, n8n, Dify, Typebot).

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
| Unified inbound endpoint | ✅ Live | Single `/bridge/inbound` route handles all platforms |
| Platform routing | ✅ Live | Automatic dispatch to `_handle_{platform}()` handler |
| Token authentication | ✅ Live | Per-platform Bearer tokens with expiry + IP whitelist |
| Partner auto-creation | ✅ Live | Find-or-create `res.partner` from phone/email/name |
| CRM lead auto-creation | ✅ Live | Find-or-create `crm.lead` linked to partner |
| Audit log | ✅ Live | Full request/response log with duration, status, platform |
| Outbound queue | ✅ Live | Persistent outbound message queue with retry + back-off |
| Cron queue processor | ✅ Live | Scheduled action runs pending outbound messages |
| Native Evolution webhook | ✅ Live | `/bridge/evolution/webhook` for delivery status + inbound |
| Health check endpoint | ✅ Live | `/bridge/inbound/health` returns module + platform info |
| Settings UI | ✅ Live | Master token, IP whitelist, Evolution API config |
| Standalone app tile | ✅ Live | Own home-screen icon (purple bridge) |

**Supported platforms:** Evolution API · Chatwoot · Typebot · n8n · Dify / Flowise

---

## 2. Architecture

```
External Platforms                 Odoo 19
─────────────────                  ───────────────────────────────────────────
Evolution API  ──┐
Chatwoot       ──┤  POST /bridge/inbound
n8n            ──┤  (Bearer token auth)    ┌─ _handle_evolution()
Typebot        ──┤ ──────────────────────► │  _handle_chatwoot()
Dify           ──┘                         │  _handle_n8n()
                                           │  _handle_typebot()
                                           │  _handle_dify()
Evolution API  ──── POST /bridge/evolution/webhook
(native WA)         (delivery + inbound)   └──► res.partner (find/create)
                                                crm.lead    (find/create)
                                                discuss.channel (optional)
                                                integration.bridge.log
                                                integration.outbound.queue
                                                      │
                                                      ▼ (cron every 5 min)
                                                 send_message()
                                                 → HTTP POST to platform
```

---

## 3. Folder Structure

```
integration_bridge_core/
│
├── __init__.py
├── __manifest__.py                         # application=True
├── README.md                               # this file
│
├── controllers/
│   ├── __init__.py
│   ├── bridge_base.py                      # Auth, logging helpers, CORS
│   └── bridge_unified.py                  # Main /bridge/inbound + /evolution/webhook
│
├── models/
│   ├── __init__.py
│   ├── integration_bridge_log.py           # integration.bridge.log model
│   ├── integration_bridge_token.py         # integration.bridge.token model
│   ├── integration_bridge_settings.py      # res.config.settings extension
│   └── integration_outbound_queue.py       # integration.outbound.queue model
│
├── views/
│   ├── integration_bridge_log_views.xml
│   ├── integration_bridge_token_views.xml
│   ├── integration_bridge_settings_views.xml
│   ├── integration_outbound_queue_views.xml
│   └── integration_menu.xml               # Root app menu + sub-menus
│
├── data/
│   ├── system_parameters.xml              # Default ir.config_parameter values
│   ├── integration_platforms.xml          # Platform seed data
│   └── ir_cron_outbound_queue.xml         # Cron: process outbound queue every 5 min
│
├── security/
│   └── ir.model.access.csv
│
├── migrations/
│   ├── 19.0.1.0.0/pre-migrate.py
│   └── 19.0.1.0.5/post-migrate.py
│
└── static/
    └── description/
        └── icon.png                        # Purple bridge icon (home screen)
```

---

## 4. Installation

```bash
python odoo-bin -c odoo.conf -u integration_bridge_core --stop-after-init
```

No Python pip dependencies beyond Odoo standard libraries.

---

## 5. Setup Guide (step-by-step)

### Step 1 — Configure the Master Token

1. Home screen → **Integration Bridge** app → **Configuration → Settings**.
2. Set **Master Token** — this is the `X-Bridge-Token` header value your external platforms must send.
3. Optionally set **IP Whitelist** — comma-separated IPs (leave empty to allow all).
4. Save.

### Step 2 — Configure Evolution API Parameters

In Settings (same form):
- **Evolution API URL** — e.g. `http://localhost:8099` or `https://evo.yourdomain.com`
- **Evolution API Key** — your Evolution API key
- **Evolution Instance** — your WhatsApp instance name (e.g. `sabry_1`)

Or edit directly in: **Settings → Technical → Parameters → System Parameters**  
Keys: `integration_bridge.evolution_url`, `integration_bridge.evolution_key`, `integration_bridge.evolution_instance`

### Step 3 — Create Per-Platform Tokens (optional)

1. Integration Bridge → **Configuration → Bridge Tokens → New**.
2. Set **Token Name**, **Platform**, paste or generate a **Token**.
3. Optionally set **Allowed IPs** and **Expires At**.
4. Save.

Per-platform tokens are validated by the base controller and can restrict access per integration source.

### Step 4 — Configure n8n / Chatwoot / Typebot to call the bridge

Add an HTTP node pointing to:
```
POST https://your-odoo.com/bridge/inbound
Headers:
  X-Bridge-Token: <your-master-token>
  Content-Type: application/json
Body:
{
  "platform": "evolution",
  "event_type": "message_created",
  "data": { ... }
}
```

### Step 5 — Configure Evolution API native webhook (optional but recommended)

In your Evolution API dashboard:
- **Webhook URL**: `https://your-odoo.com/bridge/evolution/webhook`
- **Events**: `MESSAGES_UPDATE`, `MESSAGES_UPSERT`, `CONNECTION_UPDATE`

This enables real-time delivery/read status updates on `wa.message.log` records.

### Step 6 — Verify health check

```bash
curl https://your-odoo.com/bridge/inbound/health
# → {"status": "ok", "module": "integration_bridge_core", ...}
```

---

## 6. API Reference

### POST /bridge/inbound

**Auth:** `X-Bridge-Token: <token>` header

**Request:**
```json
{
  "platform": "evolution | chatwoot | typebot | n8n | dify",
  "event_type": "message_created | form_submit | manual",
  "data": { ... }
}
```

**Response (success):**
```json
{
  "success": true,
  "record_id": 42,
  "odoo_model": "crm.lead",
  "partner_id": 17,
  "lead_created": true,
  "external_ref": "EVO-sabry_1-201234567890"
}
```

---

### Evolution data shape

```json
{
  "platform": "evolution",
  "event_type": "message_created",
  "data": {
    "instance": "sabry_1",
    "data": {
      "key": {
        "remoteJid": "201234567890@s.whatsapp.net",
        "fromMe": false
      },
      "message": { "conversation": "Hello!" },
      "pushName": "Ahmed Hassan"
    }
  }
}
```

---

### Chatwoot / n8n data shape

```json
{
  "platform": "chatwoot",
  "event_type": "conversation_created",
  "data": {
    "name": "Issue title",
    "description": "Details...",
    "reporter": {
      "phone": "+201234567890",
      "name": "Ahmed Hassan",
      "email": "ahmed@example.com"
    },
    "chatwoot": {
      "conversation_id": "1234",
      "account_id": "5",
      "inbox_id": "2"
    }
  }
}
```

---

### Typebot data shape

```json
{
  "platform": "typebot",
  "event_type": "form_submit",
  "data": {
    "form_id": "job-application-v2",
    "contact": {
      "phone": "+201234567890",
      "name": "Sara Ali",
      "email": "sara@example.com"
    },
    "answers": {
      "title": "Job Application",
      "description": "Frontend developer role"
    }
  }
}
```

---

### POST /bridge/evolution/webhook

Accepts native Evolution API webhook events directly (no custom wrapper needed).

**Events handled:**
- `messages.update` → updates delivery status (`SENT` / `DELIVERED` / `READ`) on `wa.message.log`
- `messages.upsert` → posts inbound text to `wa.message.log.mark_replied()`

---

### GET /bridge/inbound/health

```json
{
  "status": "ok",
  "module": "integration_bridge_core",
  "version": "19.0.1.0.0",
  "odoo": "19",
  "platforms": ["evolution", "chatwoot", "typebot", "n8n", "dify"]
}
```

---

## 7. Use Case Scenarios

### Scenario A — WhatsApp → CRM Lead (via Evolution API + n8n)

**Goal:** Every WhatsApp message to your Evolution instance creates a CRM lead in Odoo.

**Flow:**
1. Customer sends WhatsApp message to your number.
2. Evolution API fires webhook to n8n (or directly to Odoo).
3. n8n calls `POST /bridge/inbound` with `platform=evolution`.
4. Bridge finds or creates `res.partner` by phone number.
5. Bridge finds or creates `crm.lead` linked to partner.
6. Message text is posted to the lead's chatter.
7. If `evolution_whatsapp_chat` is installed, message also appears in the WhatsApp Discuss channel.

**Result:** Sales team sees the WhatsApp conversation in the CRM pipeline without leaving Odoo.

---

### Scenario B — Chatwoot Conversation → CRM Lead

**Goal:** Every new Chatwoot conversation creates a lead; agents can see customer history in Odoo.

**Flow:**
1. Customer starts Chatwoot conversation.
2. Chatwoot fires webhook to n8n.
3. n8n enriches payload and calls `POST /bridge/inbound` with `platform=chatwoot`.
4. Bridge creates partner + lead with `chatwoot_conversation_id` stored.
5. Lead chatter shows conversation context.

**Result:** CRM stays in sync with Chatwoot without manual data entry.

---

### Scenario C — Typebot Form → CRM Lead

**Goal:** Typebot collects job application or contact form data and creates a CRM lead.

**Flow:**
1. User completes Typebot chatbot flow.
2. Typebot calls a webhook node pointing to `POST /bridge/inbound` with `platform=typebot`.
3. Bridge extracts `contact` and `answers`, creates partner + lead.
4. Lead description = form answers.

**Result:** Every Typebot completion = qualified CRM lead with context.

---

### Scenario D — Outbound Message Queue (rate-limited sending)

**Goal:** Send messages to many WhatsApp contacts without hitting Evolution API rate limits.

**Flow:**
1. Any module calls `integration.outbound.queue.create_outbound_message(...)`.
2. Queue record is created with `status=pending`.
3. Cron job runs every 5 minutes and calls `process_pending_messages()`.
4. Each message is sent via HTTP POST to the target endpoint.
5. Success → `status=sent`; Failure → `status=failed`, `retry_count++`, `next_retry_at` set.
6. After 3 failures → permanently `failed`.

**Result:** Reliable, rate-controlled outbound messaging with full audit trail.

---

### Scenario E — Monitoring: Who's sending what?

**Goal:** Investigate why a specific platform is failing.

**Steps:**
1. Integration Bridge → **Monitoring → Integration Logs**.
2. Filter by **Platform** = `evolution`, **Status** = `failed`.
3. Open a failed log → see full Request Payload and Error Message.
4. Cross-reference with **Outbound Queue** for outbound failures.

---

## 8. Configuration Reference

### System Parameters (`ir.config_parameter`)

| Key | Default | Description |
|---|---|---|
| `integration_bridge.master_token` | *(empty)* | Required: master auth token for all inbound requests |
| `integration_bridge.ip_whitelist` | *(empty)* | Comma-separated IPs; empty = allow all |
| `integration_bridge.evolution_url` | `http://127.0.0.1:8099` | Evolution API base URL |
| `integration_bridge.evolution_key` | *(empty)* | Evolution API key |
| `integration_bridge.evolution_instance` | `sabry` | Evolution WhatsApp instance name |

---

## 9. Data Model

### `integration.bridge.log`

| Field | Type | Description |
|---|---|---|
| name | Char | Event description (auto-generated) |
| direction | Selection | `inbound` or `outbound` |
| platform | Selection | chatwoot / evolution / typebot / n8n / dify / other |
| endpoint | Char | URL called |
| external_id | Char | External reference (conversation_id, form_id, etc.) |
| status | Selection | `success` / `failed` / `pending` |
| request_payload | Text | Full JSON request body |
| response_payload | Text | Full JSON response |
| http_status | Integer | HTTP response code |
| error_message | Text | Error if failed |
| related_model | Char | Odoo model (e.g. `crm.lead`) |
| related_res_id | Integer | Odoo record ID |
| duration_ms | Integer | Processing time in milliseconds |
| remote_ip | Char | Caller IP address |

### `integration.bridge.token`

| Field | Type | Description |
|---|---|---|
| name | Char | Token label |
| token | Char | Secret token value (unique) |
| platform | Selection | Platform scope |
| active | Boolean | Only active tokens are validated |
| allowed_ips | Char | Comma-separated IP whitelist |
| expires_at | Datetime | Optional expiry |
| last_used | Datetime | Last successful use |
| usage_count | Integer | Total use count |

### `integration.outbound.queue`

| Field | Type | Description |
|---|---|---|
| name | Char | Message title |
| platform | Selection | Target platform |
| endpoint_url | Char | Full destination URL |
| payload | Text | JSON message body |
| status | Selection | `pending` / `sent` / `failed` |
| priority | Integer | 1–10 (10 = highest) |
| retry_count | Integer | Current attempt count |
| max_retries | Integer | Max attempts before permanent failure |
| next_retry_at | Datetime | Earliest time for next retry |
| http_method | Selection | GET / POST / PUT / PATCH / DELETE |
| headers | Text | Additional HTTP headers as JSON |
| response_data | Text | Last response body |
| log_id | Many2one | Linked `integration.bridge.log` record |

---

## 10. Enhancement Roadmap

### Phase 2 — Per-Platform Token Enforcement on `/bridge/inbound`

Currently the base controller validates the master token only. Enhancement: route-level platform token validation — require the token to match the `platform` field in the payload.

### Phase 3 — Webhook Signature Verification

Evolution API and Chatwoot support HMAC-SHA256 request signatures. Add signature validation in `bridge_base.py` to prevent spoofed requests even if a token is leaked.

### Phase 4 — Inbound Rate Limiting

Add per-IP request rate limiting to prevent abuse of the public `/bridge/inbound` endpoint.

### Phase 5 — Log Retention Policy (Cron)

Add a scheduled action to auto-delete `integration.bridge.log` records older than a configurable threshold (default 90 days). Partially implemented in `cleanup_old_logs()`.

### Phase 6 — Dashboard / Reporting View

Add a reporting view with:
- Messages per platform per day (bar chart)
- Success rate trend (line chart)
- Average response time (ms) per platform

### Phase 7 — Dify / AI Agent Full Integration

The `_handle_dify()` handler currently delegates to a `DifyClient` model that is not yet shipped. Complete the Dify chatflow / workflow integration with proper session management.

---

*Last updated: 2026-04-04 — aligned with version 19.0.1.0.5*
