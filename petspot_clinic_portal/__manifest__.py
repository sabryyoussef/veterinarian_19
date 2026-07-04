# -*- coding: utf-8 -*-
{
    'name': 'PetSpot Clinic Portal',
    'version': '19.0.1.0.0',
    'category': 'Services',
    'summary': 'Tokenized mobile portal for appointments, vet exam, and reminders (Chatwoot/WhatsApp)',
    'description': """
PetSpot Clinic Portal
=====================
Public token links for:

* Patient/staff booking (pet + appointment)
* Vet basic exam (medical visit + follow-up reminder)
* Token API for Chatwoot macros / dashboard app

Author: Sabry Youssef
    """,
    'author': 'Sabry Youssef',
    'license': 'LGPL-3',
    'depends': [
        'pet_management',
        'petspot_wa_intake',
        'mail',
        'integration_bridge_core',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/system_parameters.xml',
        'views/portal_token_views.xml',
        'views/portal_templates.xml',
        'views/menus.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
