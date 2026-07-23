# -*- coding: utf-8 -*-
{
    'name': 'Gmail Connector',
    'version': '19.0.7.1.0',
    'category': 'Productivity',
    'summary': 'Gmail OAuth mailboxes: browser OAuth → SMTP/IMAP provision → CRM leads → Gmail API search/import',
    'description': """
Gmail Connector
===============
Standalone Odoo 19 application that connects Gmail mailboxes via OAuth 2.0.

Features:
- Browser OAuth flow (per-account client credentials, refresh token stored in Odoo)
- One-click provision of SMTP (outgoing) and IMAP (incoming) mail servers
- Per-account token refresh (independent of system-wide google_gmail parameters)
- CRM lead creation from inbound emails with Gmail metadata fields
- Noise filtering: skip by sender domain or subject keyword; custom Gmail label fetch
- Gmail API Search & Import wizard: filter by sender/subject/label/date, preview, bulk import
- Gmail vs CRM comparison diagnostic wizard
- Job outreach heuristic: auto-flag leads from ATS platforms (LinkedIn, Greenhouse, etc.)

See README.md for full documentation, setup guide, and roadmap.
    """,
    'author': 'Sabry Youssef, Resume project',
    'author_email': 'vendorah2@gmail.com, abhorya@gmail.com',
    'website': 'https://github.com/sabryyoussef',
    'license': 'LGPL-3',
    'external_dependencies': {
        'python': [
            'google-api-python-client',
            'google-auth',
            'google-auth-oauthlib',
        ],
    },
    'depends': ['base', 'web', 'mail', 'google_gmail', 'crm'],
    'data': [
        'security/mail_gmail_connector_security.xml',
        'security/ir.model.access.csv',
        'security/mail_gmail_wizard_access.xml',
        'views/mail_gmail_account_views.xml',
        'views/mail_gmail_inbox_check_wizard_views.xml',
        'views/mail_gmail_fetch_import_wizard_views.xml',
        'views/fetchmail_server_views.xml',
        'views/crm_lead_views.xml',
        'data/mail_gmail_connector_config.xml',
        'data/crm_lead_actions.xml',
        'data/mail_gmail_server_actions.xml',
        'views/res_config_settings_views.xml',
        'views/mail_gmail_menus.xml',
    ],
    'installable': True,
    'application': True,
}
