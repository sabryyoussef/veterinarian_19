# Gmail Connector — Odoo 19 Module

> **`mail_gmail_connector`** · version 19.0.7.0.13 · license LGPL-3

A standalone Odoo 19 application that connects one or more Gmail mailboxes to Odoo using OAuth 2.0.  
Covers the full mail lifecycle: **browser OAuth → SMTP send → IMAP fetch → CRM lead creation → Gmail API search/import**.

---

## Table of Contents

1. [Feature Overview](#1-feature-overview)
2. [Architecture](#2-architecture)
3. [Folder Structure](#3-folder-structure)
4. [Installation](#4-installation)
5. [Setup Guide (step-by-step)](#5-setup-guide-step-by-step)
6. [Use Case Scenarios](#6-use-case-scenarios)
7. [Configuration Reference](#7-configuration-reference)
8. [Security Model](#8-security-model)
9. [Data Model](#9-data-model)
10. [Technical Notes & Known Fixes](#10-technical-notes--known-fixes)
11. [Enhancement Roadmap](#11-enhancement-roadmap)

---

## 1. Feature Overview

| Feature | Status | Description |
|---|---|---|
| Gmail OAuth (browser flow) | ✅ Live | Per-account OAuth 2.0 with refresh token stored in Odoo |
| Outgoing SMTP (Gmail OAuth) | ✅ Live | One-click provision of STARTTLS SMTP server |
| Incoming IMAP (Gmail OAuth) | ✅ Live | One-click provision of IMAP fetchmail server with custom mailbox/label |
| Per-account token refresh | ✅ Live | Each account uses its own OAuth client credentials |
| CRM lead creation from email | ✅ Live | Inbound emails automatically create CRM leads with Gmail metadata |
| Noise filter (IMAP) | ✅ Live | Skip by sender domain or subject keyword; custom Gmail label fetch |
| Gmail API search wizard | ✅ Live | Search Gmail with rich filters, preview results, import into Odoo |
| Gmail vs CRM comparison | ✅ Live | Diagnostic tool comparing Gmail inbox against Odoo CRM leads |
| Job outreach detection | ✅ Live | Auto-flag leads from ATS platforms (LinkedIn, Greenhouse, etc.) |
| Standalone app tile | ✅ Live | Own home-screen icon, not buried under Discuss |

---

## 2. Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     Gmail Cloud Platform                        │
│   Gmail IMAP (imap.gmail.com:993)  Gmail SMTP (smtp.gmail.com) │
│   Gmail REST API (googleapis.com/gmail/v1)                      │
└────────────┬───────────────────────┬────────────────────────────┘
             │ XOAUTH2 token         │ XOAUTH2 token
             ▼                       ▼
┌────────────────────┐   ┌───────────────────────┐
│  fetchmail.server  │   │    ir.mail_server      │
│  (IMAP/Gmail)      │   │    (SMTP/Gmail OAuth)  │
│  ← extended by     │   │  ← extended by         │
│  fetchmail_        │   │  ir_mail_server_ext.py │
│  server_ext.py     │   └───────────────────────┘
└────────┬───────────┘
         │ fetch RFC822
         ▼
┌────────────────────────────────────────────────────────────────┐
│               mail_thread_gmail_fetchmail.py                   │
│  message_parse  → enrich msg_dict with Gmail headers           │
│  _should_skip   → domain/keyword noise filter                  │
│  message_post   → strip gateway keys before _notify_thread     │
└────────────────────────────┬───────────────────────────────────┘
                             │
                             ▼
┌────────────────────────────────────────────────────────────────┐
│               crm_lead_gmail.py  (crm.lead)                    │
│  message_new   → write gmail_labels, gateway_mail_to,          │
│                  gateway_mail_cc, mail_list_id to lead          │
│  job_outreach_match (computed) → ATS domain heuristic          │
└────────────────────────────────────────────────────────────────┘

Browser OAuth flow:
  User → /google_gmail/mail_connector_oauth/start
       → Google consent screen
       → /google_gmail/mail_connector_oauth/callback
       → refresh_token stored on mail.gmail.account

Gmail API wizards:
  mail.gmail.fetch.import.wizard  → search + bulk import
  mail.gmail.inbox.check.wizard   → compare Gmail vs Odoo CRM
```

---

## 3. Folder Structure

```
mail_gmail_connector/
│
├── __init__.py                         # module root
├── __manifest__.py                     # Odoo manifest (application=True)
├── README.md                           # this file
├── PLAN.md                             # development log / original plan
├── requirements.txt                    # Python deps (pip install)
│
├── controllers/
│   ├── __init__.py
│   └── gmail_oauth.py                  # Phase C: OAuth start + callback routes
│
├── models/
│   ├── __init__.py
│   ├── mail_gmail_account.py           # Core model: mail.gmail.account
│   ├── mail_gmail_account_fetchmail.py # related fields loaded after fetchmail
│   ├── mail_thread_gmail_fetchmail.py  # mail.thread override: parse/filter/sanitize
│   ├── fetchmail_server_ext.py         # fetchmail.server: Gmail IMAP, label, filters
│   ├── ir_mail_server_ext.py           # ir.mail_server: per-account token refresh
│   ├── crm_lead_gmail.py               # crm.lead: Gmail fields + job outreach heuristic
│   ├── mail_gmail_fetch_import_wizard.py   # Wizard: search Gmail + import
│   └── mail_gmail_inbox_check_wizard.py    # Wizard: Gmail vs CRM comparison
│
├── views/
│   ├── mail_gmail_account_views.xml        # Gmail account form/list
│   ├── mail_gmail_fetch_import_wizard_views.xml
│   ├── mail_gmail_inbox_check_wizard_views.xml
│   ├── fetchmail_server_views.xml          # Added fields on fetchmail form
│   ├── crm_lead_views.xml                  # Gmail fields on CRM lead
│   └── mail_gmail_menus.xml                # Root app menu + sub-menus
│
├── data/
│   ├── mail_gmail_connector_config.xml     # Default ir.config_parameter values
│   ├── crm_lead_actions.xml                # CRM pipeline stage server actions
│   └── mail_gmail_server_actions.xml       # ir.actions.server for account buttons
│
├── security/
│   ├── mail_gmail_connector_security.xml   # Groups + record rules
│   ├── ir.model.access.csv                 # Access for main models
│   └── mail_gmail_wizard_access.xml        # Access for TransientModel wizards
│
└── static/
    └── description/
        └── icon.png                        # Red Gmail app icon (home screen)
```

---

## 4. Installation

### 4.1 Python dependencies

```bash
pip install -r addons/mail_gmail_connector/requirements.txt
# or manually:
pip install google-api-python-client>=2.100.0 google-auth>=2.23.0 google-auth-oauthlib>=1.1.0
```

### 4.2 Odoo dependencies

The module depends on: `base`, `web`, `mail`, `google_gmail`, `crm`.  
`google_gmail` is an Odoo Enterprise / Community addon — ensure it is installed.

### 4.3 Install the module

```bash
# CLI upgrade
python odoo-bin -c odoo.conf -u mail_gmail_connector --stop-after-init

# Or: Settings → Apps → search "Gmail Connector" → Install
```

---

## 5. Setup Guide (step-by-step)

### Step 1 — Create a Google Cloud OAuth App

1. Go to [Google Cloud Console](https://console.cloud.google.com/) → **APIs & Services → Credentials**.
2. Create an **OAuth 2.0 Client ID** of type **Web application**.
3. Add Authorized redirect URI:  
   `https://your-odoo-domain.com/google_gmail/mail_connector_oauth/callback`
4. Note down **Client ID** and **Client Secret**.
5. Enable the **Gmail API** under **APIs & Services → Enabled APIs**.
6. Add required scopes on **OAuth consent screen → Data access**:
   - `https://mail.google.com/`
   - `https://www.googleapis.com/auth/gmail.send`
   - `https://www.googleapis.com/auth/gmail.modify`
   - `https://www.googleapis.com/auth/gmail.readonly`
   - `https://www.googleapis.com/auth/userinfo.email`

### Step 2 — Create a Gmail Account in Odoo

1. Home screen → **Gmail** app → **Mailboxes → Gmail Accounts → New**.
2. Fill in **Name**, **Company**, **Responsible**.
3. Expand the **OAuth credentials** section (visible to Gmail Administrators only):
   - Paste **OAuth Client ID** and **Client Secret**.
4. Save.

### Step 3 — Connect with Google

1. On the Gmail account form, click **Connect with Google**.
2. You are redirected to Google's consent screen — sign in and grant access.
3. On return, the account **Status** becomes `Connected` and a refresh token is stored.
4. Click **Refresh profile** to populate the **Gmail address** field.

### Step 4 — Provision Mail Servers

1. Click **Provision Mail Servers**.
2. Odoo creates:
   - An **Outgoing mail server** (SMTP / Gmail OAuth / STARTTLS port 587)
   - An **Incoming mail server** (IMAP / Gmail OAuth / SSL port 993)
3. Both servers are linked back to this account for per-account token refresh.

### Step 5 — Configure the Incoming Server

1. Click **Incoming mail server** smart button.
2. Set **Create a new record** → `CRM Lead / Opportunity`.
3. Optionally set:
   - **IMAP mailbox / Gmail label** — default `INBOX`; use a Gmail label like `Job Outreach` to restrict fetching.
   - **Gmail fetch scope** — `Unread only` or `All messages`.
   - **Only if subject contains** — keyword filter (any match imports; leave empty = no filter).
   - **Skip senders containing** — comma-separated substrings (e.g. `youtube.com, noreply@`).
4. Set **State** to `Confirmed` and save.
5. Click **Fetch Now** to run a manual test fetch.

### Step 6 — Verify CRM leads

1. Open CRM → Pipeline or CRM Leads list.
2. Imported emails appear as leads with:
   - **Subject** = email subject
   - **Email from** = sender
   - **Gmail labels** field (if X-Gmail-Labels header was present)
   - **Mail To (gateway)** and **Mail Cc (gateway)** from email headers
   - **Job outreach match** checkbox (auto-computed from ATS domains/keywords)

---

## 6. Use Case Scenarios

### Scenario A — Job Application Pipeline (Primary Use Case)

**Goal:** Automatically import recruiter emails from Gmail into a CRM pipeline to track job applications.

**Setup:**
1. In Gmail, create a filter: if `from:linkedin.com OR from:greenhouse.io` → apply label `Job Outreach`.
2. On the Odoo incoming server, set **IMAP mailbox** = `Job Outreach`.
3. Set **Gmail fetch scope** = `Unread only`.
4. Leave **Subject keywords** empty (all emails in the label are relevant).
5. Set **Skip senders** = `youtube.com, mailer-daemon, noreply@facebook`.

**Result:**
- Every new recruiter email → new CRM lead.
- **Job outreach match** is auto-checked for leads from ATS domains.
- **Gmail labels** field shows `Job Outreach` on each lead.
- Leads not from the label are never fetched.

---

### Scenario B — Full Inbox Import + Odoo Filtering

**Goal:** Import the entire Gmail inbox into Odoo and let Odoo's filters handle noise.

**Setup:**
1. Set **IMAP mailbox** = `INBOX`.
2. Set **Gmail fetch scope** = `All messages`.
3. Enable **Allow full INBOX import**.
4. Set **Subject keywords** = `interview, recruiter, application, offer, position` (only emails matching at least one keyword create leads).
5. Set **Skip senders** = `youtube.com, linkedin.com/notifications, noreply@, mailer-daemon`.

**Result:**
- Odoo fetches all INBOX emails but only creates leads when the subject matches a keyword.
- Notification emails (YouTube, LinkedIn alerts) are silently dropped.
- Human recruiter replies (containing "interview", "offer") create leads.

---

### Scenario C — Manual Gmail Search and Import (One-Time Backfill)

**Goal:** Backfill 3 months of recruiter emails that were received before the module was set up.

**Steps:**
1. Gmail app → **Tools → Search Gmail and Import**.
2. Select the Gmail account.
3. Set **Where to search** = `in:inbox`.
4. Set **Label / source** = `Job Outreach`.
5. Set **From date** = 3 months ago.
6. Enable **Exclude spam & trash** and **Exclude Promotions / Social / Updates**.
7. Set **Max messages** = 150.
8. Click **Preview matches** — review the table of From / Subject.
9. If the list looks correct, click **Import into Odoo**.
10. Review the summary (Imported / Skipped / Failed).

**Notes:**
- Skipped = Message-Id already exists in Odoo (de-duplication is automatic).
- Failed = parsing or routing error (shown in error list).

---

### Scenario D — Diagnostic: Why are some emails missing from CRM?

**Goal:** Determine why certain Gmail emails did not create CRM leads.

**Steps:**
1. Gmail app → **Tools → Compare Gmail vs CRM Leads**.
2. Select the Gmail account.
3. Set **Gmail search query** = `label:Job Outreach newer_than:14d`.
4. Set **Messages / leads to compare** = 100.
5. Click **Run comparison**.
6. Review:
   - **Matching subjects** — emails that exist in both Gmail and Odoo.
   - **Only in Gmail** — emails fetched but not imported (check skip rules, keyword filters).
   - **Only in Odoo** — leads created by other means (manual entry, other servers).

**Typical causes of missing leads:**
- Email landed in INBOX but the server only fetches a label → move email to label or switch to INBOX fetch.
- Subject did not match the keyword filter → add keyword or clear the filter.
- Sender matched the exclude list → remove or narrow the exclusion.
- Email was already read (UNSEEN filter active) → switch to `All messages` scope.

---

### Scenario E — Send a Test Email via Gmail API

**Goal:** Verify that outgoing Gmail API credentials work.

**Steps:**
1. Open the Gmail account form.
2. Click **Send test email**.
3. Odoo sends a test message to the Gmail address itself via the Gmail API.
4. Check the chatter for confirmation (message ID logged).
5. Check the Gmail **Sent** folder to confirm delivery.

---

### Scenario F — Multi-Mailbox Setup (Two Gmail Accounts)

**Goal:** Track both a personal recruiter inbox and a company HR inbox in the same Odoo instance.

**Setup:**
1. Create two `mail.gmail.account` records (e.g. `sabry@gmail.com` and `hr@company.com`).
2. Each uses its own **OAuth Client ID and Secret** (or reuse the same Google Cloud app with both redirect URIs).
3. Connect each account independently via **Connect with Google**.
4. Provision mail servers for each → two SMTP + two IMAP servers.
5. On each IMAP server, set the target model to `crm.lead`.

**Result:** All emails from both accounts create CRM leads. The **Incoming mail server** field on each lead identifies which mailbox the email came from.

---

## 7. Configuration Reference

### System Parameters (`ir.config_parameter`)

| Key | Default | Description |
|---|---|---|
| `mail_gmail_connector.job_outreach_keywords` | `interview,recruiter,application,...` | Comma-separated subject keywords for `job_outreach_match` computation |
| `mail_gmail_connector.job_outreach_sender_domains` | `linkedin.com,greenhouse.io,...` | Comma-separated ATS domains for `job_outreach_match` |
| `mail_gmail_connector.fetchmail_batch_limit` | `0` (unlimited) | Max emails per fetchmail cron run; `0` = no cap |

Edit via: **Settings → Technical → Parameters → System Parameters**.

### Fetchmail Server Fields (per incoming server)

| Field | Description |
|---|---|
| IMAP mailbox / Gmail label | Gmail folder to SELECT. Default `INBOX`. Use a label name for filtered import. |
| Gmail fetch scope | `Unread only` (UNSEEN) or `All messages` (ALL) |
| Allow full INBOX import | Required when scope = All and mailbox = INBOX |
| Only if subject contains | Comma/newline keywords; any match = import; empty = no filter |
| Skip senders containing | Comma-separated substrings matched against From (case-insensitive) |

### OAuth Scopes (per account, managers only)

Default scope string includes:
- `https://mail.google.com/` — required for XOAUTH2 IMAP/SMTP
- `https://www.googleapis.com/auth/gmail.send`
- `https://www.googleapis.com/auth/gmail.modify`
- `https://www.googleapis.com/auth/gmail.readonly`
- `https://www.googleapis.com/auth/userinfo.email`

Do not narrow scopes unless you also remove the corresponding functionality.

---

## 8. Security Model

| Group | Internal name | Capabilities |
|---|---|---|
| Gmail User | `group_gmail_user` | View own Gmail accounts (record rule: `user_id = current user`) |
| Gmail Administrator | `group_gmail_manager` | View all accounts; access OAuth fields (client_id, secret, refresh_token); run wizards |

**Record rules:**
- `gmail_user` → can only read/write accounts where they are the **Responsible** user.
- `gmail_manager` → unrestricted access to all `mail.gmail.account` records.

**Sensitive fields** (visible to Administrators only):
- `oauth_client_id`, `oauth_client_secret`, `refresh_token`, `scopes`

> **Note:** Odoo 19 does not provide `fields.Encrypted` in Community. Credentials are stored as plain `Char`. Consider enabling PostgreSQL-level encryption (`pgcrypto`) or using Odoo.sh's secrets management if operating in a shared environment.

---

## 9. Data Model

### `mail.gmail.account`

| Field | Type | Description |
|---|---|---|
| name | Char | Account display name |
| active | Boolean | Archive without deleting |
| company_id | Many2one | Company scope |
| user_id | Many2one | Responsible user |
| gmail_email | Char | Verified Gmail address (from API profile) |
| state | Selection | `draft` / `connected` / `error` |
| oauth_client_id | Char (manager) | Google Cloud OAuth client ID |
| oauth_client_secret | Char (manager) | Google Cloud OAuth client secret |
| refresh_token | Char (manager) | Long-lived OAuth refresh token |
| scopes | Text (manager) | Space-separated OAuth scopes |
| last_sync_at | Datetime | Timestamp of last successful API call |
| last_error | Text | Last error message (cleared on success) |
| outgoing_mail_server_id | Many2one | Provisioned `ir.mail_server` (SMTP) |
| incoming_mail_server_id | Many2one | Provisioned `fetchmail.server` (IMAP) |

### `crm.lead` (extended fields)

| Field | Type | Description |
|---|---|---|
| gmail_labels | Text | Gmail label list from `X-Gmail-Labels` IMAP header |
| gateway_mail_to | Text | Original `To:` header (searchable) |
| gateway_mail_cc | Text | Original `Cc:` header |
| mail_list_id | Char | `List-Id` header (mailing list identifier) |
| sender_domain | Char (computed) | Domain part of `email_from` |
| job_outreach_match | Boolean (computed) | True if ATS domain, keyword in subject, or Job Outreach label |

### `fetchmail.server` (extended fields)

| Field | Description |
|---|---|
| gmail_connector_account_id | Back-link to the provisioning `mail.gmail.account` |
| gmail_imap_mailbox | IMAP SELECT target (default `INBOX`) |
| gmail_imap_fetch_scope | `unseen` or `all_in_mailbox` |
| gmail_allow_inbox_all | Safety flag for full INBOX import |
| gmail_inbound_subject_keywords | Keyword allow-list for subject filtering |
| gmail_inbound_exclude_domains | Sender substring deny-list |

---

## 10. Technical Notes & Known Fixes

### Odoo 19 compatibility: `_notify_thread` ValueError

**Problem:** Odoo 19's `_notify_thread` uses a strict parameter whitelist (`_get_notify_valid_parameters()`). Custom keys added to `msg_dict` by `message_parse` (e.g. `gateway_mail_to`, `gmail_labels`) survive the `_message_route_process` spread into `post_params` and reach `_notify_thread`, causing:

```
ValueError: Those values are not supported when posting or notifying: gateway_mail_to
```

**Fix:** `message_post` and `message_notify` on `MailThreadGmailFetchmail` strip the four gateway keys before calling `super()`. By that point, `message_new` (on `crm.lead`) has already consumed the values to populate lead fields. See `models/mail_thread_gmail_fetchmail.py`.

### Gmail IMAP mailbox SELECT reset

**Problem:** Core `OdooIMAP4_SSL.check_unread_messages()` calls `select()` with no arguments, resetting the SELECT to INBOX and ignoring a previously selected Gmail label.

**Fix:** `OdooIMAP4GmailConnector` subclass stores the selected mailbox on the connection object and re-applies it before each SEARCH. See `models/fetchmail_server_ext.py`.

### Per-account vs system-wide token refresh

**Problem:** Core `google_gmail` reads `ir.config_parameter` `google_gmail_client_id` / `google_gmail_client_secret` for token refresh. This means all Gmail servers share one OAuth app, which breaks multi-account setups.

**Fix:** `ir_mail_server_ext.py` and `fetchmail_server_ext.py` override `_fetch_gmail_access_token()` to call `mail.gmail.account._gmail_fetch_access_token_direct()` when a `gmail_connector_account_id` is set, using per-account credentials.

### Wizard access via XML `search` attribute

**Problem:** `ir.model.access.csv` uses XML IDs like `model_mail_gmail_inbox_check_wizard`. For `TransientModel`s in Odoo 19, these IDs may not be registered when the CSV is processed during upgrade.

**Fix:** Wizard access rules are defined in `security/mail_gmail_wizard_access.xml` using `model_id` with a `search="[('model', '=', '...')]"` attribute to resolve the model by technical name at install time.

---

## 11. Enhancement Roadmap

### Phase G — Gmail Push Notifications (Pub/Sub)

**Current limitation:** Emails are fetched only when the fetchmail cron runs (default every 5 minutes). There is a delay between email arrival in Gmail and lead creation in Odoo.

**Enhancement:** Integrate Gmail's [Push Notifications API](https://developers.google.com/gmail/api/guides/push) via Google Cloud Pub/Sub:

1. Register a Pub/Sub topic and subscription per Gmail account.
2. Add an Odoo webhook controller `/gmail/pubsub/webhook` to receive push events.
3. On push event: call `fetchmail.server.fetch_mail()` immediately for that account.
4. Result: near-real-time lead creation (< 5 seconds from Gmail receipt).

**Files to add:** `controllers/gmail_pubsub.py`, `models/mail_gmail_account_pubsub.py`

---

### Phase H — Message Deduplication Table

**Current limitation:** Deduplication relies on Odoo's built-in `Message-Id` check inside `message_process`. If the same email is imported via both IMAP fetch and the manual import wizard, it is silently skipped — but only if the `Message-Id` header is present and well-formed.

**Enhancement:**

1. Add a `mail.gmail.imported.message` model storing `(account_id, gmail_message_id, odoo_res_id, odoo_model)`.
2. Before import, check this table.
3. After import, record the mapping.
4. Provides a full audit trail of which Gmail messages became which Odoo records.

---

### Phase I — Outbound Queue with Retry

**Current limitation:** Outgoing emails via Gmail API (test send) use a fire-and-forget approach. If the API call fails, the error is logged but no retry occurs.

**Enhancement:**

1. Add `mail.gmail.outbound.queue` model (mirroring `integration_bridge_core`'s outbound queue pattern).
2. `action_gmail_send_test` and future programmatic sends push to the queue.
3. A cron processes the queue with exponential back-off.
4. Chatter on the Gmail account shows delivery status per message.

---

### Phase J — Gmail Label Sync (two-way)

**Current limitation:** Gmail labels are read-only (parsed from IMAP `X-Gmail-Labels`). Odoo cannot write labels back to Gmail.

**Enhancement:**

1. Add `action_gmail_apply_label(label_name)` on `mail.gmail.account` using the Gmail API `users.messages.modify` endpoint.
2. When a CRM lead moves to a specific pipeline stage (e.g. `Rejected`), a server action applies a Gmail label (e.g. `Rejected`) to the original thread.
3. Closes the loop: Odoo stage changes are reflected in Gmail.

---

### Phase K — Multi-Company Isolation

**Current limitation:** Company isolation relies on the `company_id` field and record rules. The fetchmail cron runs as admin and can see all servers.

**Enhancement:**

1. Add `res.company` multi-company rules to `fetchmail.server` linked records.
2. Ensure wizards and actions respect the current company context.
3. Add a `company_ids` domain on the fetchmail cron to limit per-company runs.

---

### Phase L — Encrypted Credential Storage

**Current limitation:** `oauth_client_id`, `oauth_client_secret`, and `refresh_token` are stored as plain `Char` fields in PostgreSQL. Access is restricted by group ACLs but not encrypted at rest.

**Enhancement:**

1. Evaluate Odoo 19's `fields.Encrypted` availability (Community vs Enterprise).
2. If unavailable, implement AES-GCM encryption with a master key stored in an environment variable (not in the database).
3. Provide a migration script to encrypt existing credentials on upgrade.

---

### Phase M — CRM Pipeline Automation

**Current limitation:** Stage transitions are triggered by manual server actions in the CRM form. There is no automatic progression.

**Enhancement:**

1. Add a scheduled action that scans leads with `job_outreach_match=True`.
2. If a lead has had no reply in 14 days, auto-move to `No Response` stage.
3. If a lead's Gmail thread contains a reply with keywords (`schedule`, `interview`), auto-move to `Recruiter Replied`.
4. Use the Gmail API to check thread history (not just fetchmail) for this scanning.

---

*Last updated: 2026-04-04 — documentation aligned with version 19.0.7.0.13*
