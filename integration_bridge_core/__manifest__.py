# -*- coding: utf-8 -*-
{
    'name': 'Integration Bridge Core',
    'version': '19.0.1.0.5',
    'category': 'Tools',
    'summary': 'Universal integration layer for Evolution WhatsApp, Chatwoot, n8n, Dify → Odoo 19',
    'description': """
Integration Bridge Core — Odoo 19
===================================
Universal integration layer connecting external platforms with Odoo.

Supported Platforms:
- Evolution API (WhatsApp Web)
- Chatwoot (customer conversations)
- n8n (workflow automation)
- Dify / Flowise (AI agents)
- Typebot (form-based collection)

Features:
- Token-based authentication (master token + per-platform tokens)
- IP whitelisting support
- Request/response logging with full audit trail
- Outbound message queue with retry logic
- Cron-based queue processor
- CRM lead + partner auto-creation from WhatsApp messages
- Unified /bridge/inbound endpoint with platform routing
- Health check endpoint
- Settings UI (master token, IP whitelist)

Author: Sabry Youssef
    """,
    'author': 'Sabry Youssef',
    'website': 'https://github.com/sabryyoussef',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'web',
        'mail',
        'crm',
        'contacts',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/system_parameters.xml',
        'data/integration_platforms.xml',
        'data/ir_cron_outbound_queue.xml',
        'views/integration_bridge_log_views.xml',
        'views/integration_bridge_token_views.xml',
        'views/integration_bridge_settings_views.xml',
        'views/integration_outbound_queue_views.xml',
        'views/integration_menu.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
