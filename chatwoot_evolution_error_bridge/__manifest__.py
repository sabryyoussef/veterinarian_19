# -*- coding: utf-8 -*-
{
    'name': 'Chatwoot Evolution Error Bridge',
    'version': '19.0.1.0.1',
    'category': 'Tools',
    'summary': 'Chatwoot/Evolution WhatsApp → Odoo 19 CRM bridge (error_reporter_16-free)',
    'description': """
Chatwoot Evolution Error Bridge — Odoo 19
==========================================
Extends integration_bridge_core with legacy /bridge/error_reports endpoint
and Chatwoot-specific CRM lead tracking fields.

In Odoo 19, the old error.report model is replaced by crm.lead + res.partner,
so this module re-routes all Chatwoot/WhatsApp webhooks to CRM.

Features:
- Extends crm.lead with Chatwoot conversation tracking fields
- Provides backward-compatible /bridge/error_reports webhook endpoint
- Configurable via res.config.settings
- Compatible with existing n8n/Chatwoot workflows

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
        'integration_bridge_core',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/system_parameters.xml',
        'views/crm_lead_chatwoot_views.xml',
        'views/res_config_settings_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
