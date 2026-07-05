# WhatsApp Chat — Odoo 19 Module

> **`evolution_whatsapp_chat`** · version 19.0.1.7.0 · license LGPL-3  
> Depends on: `integration_bridge_core`

Send and receive WhatsApp messages directly from Odoo CRM leads and contacts, powered by the [Evolution API](https://github.com/EvolutionAPI/evolution-api).  
Includes campaign management, delivery tracking, and a full reporting dashboard.

---

## Table of Contents

1. [Feature Overview](#1-feature-overview)
2. [Architecture](#2-architecture)
3. [Folder Structure](#3-folder-structure)
4. [Installation](#4-installation)
5. [Setup Guide (step-by-step)](#5-setup-guide-step-by-step)
6. [Use Case Scenarios](#6-use-case-scenarios)
7. [Configuration Reference](#7-configuration-reference)
8. [Data Model](#8-data-model)
9. [Enhancement Roadmap](#9-enhancement-roadmap)

---

## 1. Feature Overview

| Feature | Status | Description |
|---|---|---|
| Send WhatsApp (quick) | ✅ Live | Smart button on contacts + CRM leads opens send wizard |
| Message templates | ✅ Live | Reusable templates with `{name}`, `{first}`, `{company}`, `{phone}` placeholders |
| Template personalisation | ✅ Live | Auto-render template per contact when sending |
| Attachments | ✅ Live | Send PDF, images, documents via Evolution API `/sendMedia` |
| Send modes | ✅ Live | Send Now / Queue / Schedule for later |
| WhatsApp Discuss channel | ✅ Live | Dedicated channel per contact; inbound messages appear there |
| Inbound message routing | ✅ Live | Incoming WhatsApp messages → Discuss channel + lead chatter |
| Delivery status tracking | ✅ Live | `PENDING → SENT → DELIVERED → READ` per message |
| Campaign management | ✅ Live | Multi-contact campaigns with per-recipient status tracking |
| Anti-duplicate logic | ✅ Live | Skip contacts who already received this campaign |
| Rate limiting | ✅ Live | Configurable delay between messages (seconds) |
| Reporting dashboard | ✅ Live | Success rate, read rate, delivery analytics |
| Standalone app tile | ✅ Live | Own home-screen icon (green WhatsApp) |

---

## 2. Architecture

```
Odoo User
    │
    ▼
whatsapp.send.wizard (quick send)
    │  or
wa.campaign (bulk)
    │
    ├──── Send Mode: Now ──► _send_via_evolution()
    │                              │
    │                              ▼ POST /message/sendText/{instance}
    │                         Evolution API
    │                              │
    │                              ▼
    │                    wa.message.log (PENDING → SENT)
    │
    └──── Send Mode: Queue / Scheduled
               │
               ▼
        integration.outbound.queue
               │
               ▼ (cron every 5 min)
        integration_bridge_core.send_message()
               │
               ▼ POST /message/sendText/{instance}
           Evolution API

Inbound WhatsApp message:
  Evolution webhook ──► POST /bridge/evolution/webhook (integration_bridge_core)
                                    │
                                    ▼
                       wa.message.log.mark_replied()  +  discuss.channel.wa_post_inbound()
                                    │
                                    ▼
                       lead chatter note  +  Discuss channel message
```

---

## 3. Folder Structure

```
evolution_whatsapp_chat/
│
├── __init__.py
├── __manifest__.py                             # application=True
├── README.md                                   # this file
│
├── models/
│   ├── __init__.py
│   ├── whatsapp_template.py                    # evo.wa.template: message templates
│   ├── whatsapp_send_wizard.py                 # whatsapp.send.wizard: quick send
│   ├── whatsapp_bulk_wizard.py                 # whatsapp.bulk.wizard: one-off bulk
│   ├── wa_campaign.py                          # wa.campaign: campaign management
│   ├── wa_campaign_line.py                     # wa.campaign.line: per-recipient row
│   ├── wa_campaign_recipient_wizard.py         # wizard: select campaign recipients
│   ├── wa_message_log.py                       # wa.message.log: delivery tracking
│   ├── discuss_channel.py                      # discuss.channel: WhatsApp channel integration
│   ├── res_partner.py                          # res.partner: WA phone + smart button
│   └── crm_lead.py                             # crm.lead: WA smart button + channel
│
├── views/
│   ├── whatsapp_template_views.xml
│   ├── whatsapp_send_wizard_views.xml
│   ├── whatsapp_bulk_wizard_views.xml
│   ├── wa_campaign_views.xml
│   ├── wa_campaign_line_views.xml
│   ├── wa_reporting_views.xml
│   ├── res_partner_views.xml                   # Smart button on contact form
│   ├── crm_lead_views.xml                      # Smart button on lead form
│   └── whatsapp_menu.xml                       # Root app menu + sub-menus
│
├── data/
│   └── whatsapp_templates.xml                  # Seed templates (CV intro, follow-up, interview)
│
├── security/
│   └── ir.model.access.csv
│
├── migrations/
│   └── 19.0.1.1.0/pre-migrate.py
│
├── tests/
│   └── test_odoo19_compatibility.py
│
└── static/
    └── description/
        └── icon.png                            # Green WhatsApp icon (home screen)
```

---

## 4. Installation

### Prerequisites
- `integration_bridge_core` must be installed first.
- Evolution API running and connected to a WhatsApp number.
- Evolution API URL, key, and instance configured in `integration_bridge_core` settings.

```bash
python odoo-bin -c odoo.conf -u evolution_whatsapp_chat --stop-after-init
```

---

## 5. Setup Guide (step-by-step)

### Step 1 — Verify Evolution API connection

1. Confirm Evolution API is running: `curl http://your-evo-host:8099/instance/fetchInstances`
2. In Odoo: **Integration Bridge → Configuration → Settings** → confirm URL, Key, Instance are set.

### Step 2 — Check seed templates

1. WhatsApp app → **Messaging → Message Templates**.
2. Three default templates are pre-loaded: **CV Introduction**, **Follow-up**, **Interview Invite**.
3. Edit or add templates. Use placeholders: `{name}`, `{first}`, `{company}`, `{phone}`.

### Step 3 — Send a test message from a contact

1. Open **Contacts** (or **CRM → Leads**) → open any record with a phone number.
2. Click the green **WhatsApp** smart button (phone icon in the top-right).
3. The send wizard opens — phone is pre-filled.
4. Select a **Template** or type a free-form message.
5. Choose **Send Mode**: `Send Now` for immediate, `Queue` for cron-based.
6. Click **Send** → success notification appears.
7. Check the chatter — a green-bordered note confirms the send.

### Step 4 — View the WhatsApp Discuss channel

1. Open Discuss (from the main menu).
2. Find the channel named `WhatsApp — {contact name}`.
3. Outbound messages appear here; inbound messages (from Evolution webhook) also appear here.

### Step 5 — Create a Campaign

1. WhatsApp app → **Campaigns → Campaigns → New**.
2. Fill **Campaign Name**, select a **Template** or write a **Message**.
3. Set **Target**: Contacts or CRM Leads.
4. Click **Load Recipients** → select contacts/leads in the wizard.
5. Click **Generate Recipients** → the campaign lines list is populated.
6. Review — skipped contacts (duplicates or recently contacted) are already marked.
7. Set **Send Mode**: Immediate / Queue / Scheduled.
8. Click **Start Campaign** → messages go out.
9. Monitor progress in the **Campaign Recipients** tab (Pending / Sent / Delivered / Read / Failed).

### Step 6 — Monitor delivery

1. WhatsApp app → **Reporting → All Messages** (or Sent / Received / Got Replies).
2. Each `wa.message.log` row shows phone, direction, status, timestamp.
3. Delivery status updates automatically when Evolution fires `MESSAGES_UPDATE` webhook events.

---

## 6. Use Case Scenarios

### Scenario A — Quick follow-up to a CRM lead

**Context:** A recruiter wants to follow up with a candidate via WhatsApp immediately after reviewing their profile.

**Steps:**
1. CRM → Pipeline → open the lead.
2. Click **WhatsApp** smart button.
3. Select template **Follow-up Message** → personalised text auto-fills.
4. Send Now.

**Result:** Message sent instantly; chatter note logged; WhatsApp Discuss channel updated.

---

### Scenario B — Interview invitation to multiple candidates

**Context:** HR wants to send the same interview invitation to 15 shortlisted candidates.

**Steps:**
1. WhatsApp app → **Campaigns → New**.
2. Template = "Interview Invite". Message = `Hi {first}, we'd like to invite you to an interview...`
3. Target = CRM Leads. Click **Load Recipients** → select the 15 shortlisted leads.
4. Enable **Prevent Duplicate Sends** and **Personalise per Contact**.
5. Set **Delay Between Messages** = 5 seconds (avoid rate limits).
6. **Start Campaign**.

**Result:** 15 personalised messages sent with individual delivery tracking; failed messages can be retried.

---

### Scenario C — Scheduled campaign for off-hours delivery

**Context:** Marketing wants to send a campaign at 9 AM the next morning, not now.

**Steps:**
1. Create campaign as above.
2. Set **Send Mode** = `Schedule for Specific Time`.
3. Set **Scheduled Send Time** = tomorrow 09:00.
4. Start Campaign → messages enter the outbound queue with `next_retry_at = 09:00`.
5. The cron job (runs every 5 min) will pick them up after 09:00.

---

### Scenario D — Inbound message from a customer

**Context:** A candidate replies to the WhatsApp follow-up.

**Flow (automatic):**
1. Evolution API receives the reply.
2. Evolution fires `MESSAGES_UPSERT` to `/bridge/evolution/webhook`.
3. Bridge calls `wa.message.log.mark_replied(phone, reply_text)`.
4. The log entry is updated; the Discuss channel for that contact shows the reply.
5. The CRM lead chatter is updated with the inbound message text.

**What the user sees:** The Discuss channel `WhatsApp — Ahmed Hassan` shows the new incoming message. The lead status can be manually updated to "Recruiter Replied".

---

### Scenario E — Bulk send with attachments

**Context:** Send a PDF brochure + WhatsApp text to all active contacts.

**Steps:**
1. WhatsApp app → Campaigns → New.
2. Write message body.
3. Add attachment(s) in **Attachments** field (PDF, image).
4. Load recipients → Generate → Start Campaign.

**Result:** Each recipient gets the text message followed by the attachment via Evolution `/sendMedia`.

---

## 7. Configuration Reference

### System Parameters (from `integration_bridge_core`)

| Key | Description |
|---|---|
| `integration_bridge.evolution_url` | Base URL of Evolution API server |
| `integration_bridge.evolution_key` | API key for Evolution API |
| `integration_bridge.evolution_instance` | WhatsApp instance name |

### Message Template Placeholders

| Placeholder | Replaced with |
|---|---|
| `{name}` | Full contact name |
| `{first}` | First name only |
| `{company}` | Company name |
| `{phone}` | Normalised phone number |

---

## 8. Data Model

### `evo.wa.template`

| Field | Type | Description |
|---|---|---|
| name | Char | Template display name |
| body | Text | Template text with `{placeholders}` |
| active | Boolean | Only active templates appear in wizards |
| category | Selection | intro / follow_up / interview / general |

### `wa.campaign`

| Field | Type | Description |
|---|---|---|
| name | Char | Campaign name |
| state | Selection | draft / scheduled / running / paused / completed / cancelled |
| template_id | Many2one | Template to use |
| message | Text | Final message (can override template) |
| personalise | Boolean | Replace placeholders per contact |
| target_model | Selection | `res.partner` or `crm.lead` |
| send_mode | Selection | immediate / queue / scheduled |
| scheduled_date | Datetime | When to start (scheduled mode) |
| delay_between | Integer | Seconds between messages |
| check_duplicates | Boolean | Skip already-contacted recipients |
| min_days_between | Integer | Cooldown days between campaigns per contact |
| total_count | Integer (computed) | Total recipients |
| sent_count | Integer (computed) | Successfully sent |
| delivered_count | Integer (computed) | Delivered to device |
| read_count | Integer (computed) | Read by recipient |
| success_rate | Float (computed) | % sent |
| read_rate | Float (computed) | % read out of sent |

### `wa.campaign.line`

| Field | Type | Description |
|---|---|---|
| campaign_id | Many2one | Parent campaign |
| partner_id | Many2one | Contact |
| lead_id | Many2one | CRM lead (optional) |
| phone | Char | Normalised phone |
| status | Selection | pending / sent / delivered / read / failed / skipped |
| message | Text | Rendered (personalised) message |
| wa_message_id | Char | Evolution API message ID (for delivery tracking) |
| error_msg | Text | Error if failed |

### `wa.message.log`

| Field | Type | Description |
|---|---|---|
| partner_id | Many2one | Contact |
| lead_id | Many2one | CRM lead |
| direction | Selection | `out` (sent) / `in` (received) |
| phone | Char | Phone number |
| message | Text | Message content |
| status | Selection | pending / sent / delivered / read / failed |
| wa_message_id | Char | Evolution API message ID |
| replied | Boolean | True if a reply was received |
| reply_text | Text | Inbound reply content |

---

## 9. Enhancement Roadmap

### Read receipts real-time UI

Currently read status is updated by the Evolution webhook cron. Enhancement: use Odoo bus notifications to push delivery status updates to the open campaign view in real-time, without refreshing.

### WhatsApp template message approval (Meta BSP)

For production WhatsApp Business API (Meta-approved), messages must use pre-approved templates. Add a `template_status` field (`draft` / `submitted` / `approved` / `rejected`) and an approval workflow.

### AI-powered reply suggestions

When an inbound WhatsApp message arrives, use Dify / OpenAI to suggest a reply based on the conversation history in the Discuss channel. Present suggestion in the chatter as a button "Use this reply".

### Opt-out / unsubscribe management

Add an opt-out mechanism: if a contact replies `STOP`, mark them as opted-out and exclude from future campaigns automatically.

### Campaign A/B testing

Allow creating two message variants per campaign, split recipients 50/50, and compare read rates.

---

*Last updated: 2026-04-04 — aligned with version 19.0.1.7.0*
