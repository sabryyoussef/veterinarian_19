# Gmail Connector — Development Log

> For full documentation, setup guide, use cases, and roadmap see **[README.md](README.md)**.

---

## Shipped Phases

| Phase | Version | Description |
|---|---|---|
| A | 19.0.1.x | Skeleton: `mail.gmail.account` model, security groups (User / Administrator), record rules, Discuss → Configuration menu, chatter-ready form |
| B | 19.0.2.x | Credentials + Send: manager-only OAuth fields, default scopes, `action_gmail_refresh_profile`, `action_gmail_send_test` (self-address), chatter logging |
| C | 19.0.3.x | Browser OAuth: `/google_gmail/mail_connector_oauth/start` + `/callback` routes extending `GoogleGmailController`; session state; secure callback flow |
| D | 19.0.4.x | Provision mail servers: one-click SMTP + IMAP provisioning linked to account; per-account `_fetch_gmail_access_token` override; smart buttons |
| E | 19.0.5.x | CRM pipeline: IMAP fetch to `crm.lead`; Gmail label field; custom IMAP mailbox SELECT that does not reset to INBOX |
| E+ | 19.0.6.x | Noise filters: sender domain exclude, subject keyword allow-list; `job_outreach_match` computed field; ATS domain heuristic |
| F | 19.0.7.x | Gmail API wizards: **Search Gmail and Import** (rich filter builder, preview, bulk import); **Compare Gmail vs CRM leads** (diagnostic overlay); standalone app tile with icon |

## Key Bug Fixes

| Version | Fix |
|---|---|
| 19.0.7.0.12 | Wizard access via XML `search` attribute instead of CSV XML IDs (TransientModel registration timing) |
| 19.0.7.0.12 | `ir.actions.server` for account buttons to bypass Odoo 19 strict `type="object"` button validation on upgrade |
| 19.0.7.0.12 | `mail_gmail_account_fetchmail.py` split to resolve related field load order for `fetchmail.server` fields |
| 19.0.7.0.13 | `message_post` / `message_notify` override to strip `_GMAIL_GATEWAY_KEYS` before `_notify_thread` (Odoo 19 strict whitelist `ValueError` fix) |
| 19.0.7.0.13 | Standalone app: `application=True`, `web_icon`, own root menu with Mailboxes / Tools sections |

## Open Decisions (deferred)

- [ ] Single Google Cloud OAuth app (system-wide) vs per-company client id/secret
- [ ] `fields.Encrypted` for credential storage (not available in Odoo 19 Community)
- [ ] Gmail Pub/Sub push integration for real-time fetch (planned Phase G)
- [ ] Outbound queue with retry logic (planned Phase I)
