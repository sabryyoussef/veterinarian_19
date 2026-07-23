# -*- coding: utf-8 -*-
{
    'name': 'Phone SMS Connector',
    'version': '19.0.1.1.0',
    'category': 'Productivity',
    'summary': 'Send & manage phone SMS from Odoo via an Android phone SMS gateway (pluggable backend)',
    'description': """
Phone SMS Connector — Odoo 19
=============================
Send and manage phone SMS directly from Odoo, using an Android phone as the SMS
gateway (reachable over USB/Bluetooth tethering or the LAN).

Features:
- "Send SMS" smart button + action on contacts and CRM leads
- Quick-send wizard: pick recipients or a free phone number, choose a template
- Reusable SMS templates with placeholder rendering
- Full message log (outbound + inbound) with delivery states and chatter
- Pluggable gateway backend (Android SMSGate / generic HTTP JSON) so it can be
  swapped later without touching the rest of the module
- Gateway configuration with a one-click connection test
- Inbound polling cron + a token-protected webhook controller for push callbacks

Author: Sabry Youssef
    """,
    'author': 'Sabry Youssef',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'mail',
        'crm',
        'contacts',
        'phone_validation',
        'hr_expense',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/sms_data.xml',
        'data/sms_cron.xml',
        'data/sms_templates.xml',
        'data/expense_categories.xml',
        'data/bank_sms_counterparty_map_data.xml',
        'views/sms_gateway_config_views.xml',
        'views/sms_template_views.xml',
        'views/sms_send_wizard_views.xml',
        'views/sms_message_log_views.xml',
        'views/bank_sms_transaction_views.xml',
        'views/bank_sms_counterparty_map_views.xml',
        'views/bank_sms_backfill_wizard_views.xml',
        'views/hr_expense_views.xml',
        'views/res_partner_views.xml',
        'views/crm_lead_views.xml',
        'views/sms_menu.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
