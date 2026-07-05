# -*- coding: utf-8 -*-
{
    'name': 'WhatsApp Chat',
    'version': '19.0.1.7.0',
    'category': 'Productivity',
    'summary': 'Send & receive WhatsApp from CRM leads and contacts via Evolution API + Campaigns',
    'description': """
Evolution WhatsApp Chat — Odoo 19
===================================
Adds a WhatsApp quick-send button + live chat panel to both
CRM leads and contacts, routed through the Evolution API.

Features:
- "Send WhatsApp" smart button on contacts and CRM leads
- Quick-send wizard with message templates
- Dedicated WhatsApp channel per contact in Odoo Discuss
- Incoming WhatsApp messages appear in the Discuss channel + chatter
- Predefined message templates (CV intro, follow-up, interview)
- Full outbound via Evolution API /message/sendText
- **Campaign Management**: Multi-contact campaigns with status tracking
- **Anti-Duplicate**: Prevent sending same campaign twice
- **Status Tracking**: Pending → Sent → Delivered → Read
- **Reporting Dashboard**: Success rates, read rates, analytics

Author: Sabry Youssef
    """,
    'author': 'Sabry Youssef',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'mail',
        'crm',
        'contacts',
        'integration_bridge_core',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/whatsapp_templates.xml',
        'views/whatsapp_template_views.xml',
        'views/whatsapp_send_wizard_views.xml',
        'views/whatsapp_bulk_wizard_views.xml',
        'views/wa_campaign_views.xml',
        'views/wa_campaign_line_views.xml',
        'views/wa_reporting_views.xml',
        'views/res_partner_views.xml',
        'views/crm_lead_views.xml',
        'views/whatsapp_menu.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
