# -*- coding: utf-8 -*-
{
    'name': 'PetSpot Clinic Portal',
    'version': '19.0.2.1.0',
    'category': 'Services',
    'summary': 'Tokenized mobile portal for appointments, vet exam, incomplete cases, reminders',
    'description': """
PetSpot Clinic Portal
=====================
Public token links for booking and exam, incomplete-case tracking in Odoo,
WhatsApp reminders, booking slots, and submit audit log.

Author: Sabry Youssef
    """,
    'author': 'Sabry Youssef',
    'license': 'LGPL-3',
    'depends': [
        'pet_management',
        'petspot_wa_intake',
        'mail',
        'integration_bridge_core',
        'sale',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/system_parameters.xml',
        'data/cron_reminders.xml',
        'views/portal_token_views.xml',
        'views/incomplete_visit_views.xml',
        'views/clinic_slot_views.xml',
        'views/portal_templates.xml',
        'views/menus.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
