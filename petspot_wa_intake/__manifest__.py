# -*- coding: utf-8 -*-
{
    'name': 'PetSpot WhatsApp Intake',
    'version': '19.0.1.0.0',
    'category': 'Services',
    'summary': 'Draft pets, visits, and sales from PetSpot Sahel WhatsApp / Chatwoot',
    'description': """
PetSpot WhatsApp Intake
=======================
Optional clinic lane between Chatwoot (PetSpot Sahel inbox) / Evolution and Odoo.

* Ingest messages via secured HTTP endpoint (X-Bridge-Token)
* Store draft intake records (pet / visit / sale / other)
* Staff confirm in Odoo to create pet.pet, pet.appointment, or sale.order drafts
* Does not hard-depend on Chatwoot or Evolution packages — only system parameters

Author: Sabry Youssef
    """,
    'author': 'Sabry Youssef',
    'license': 'LGPL-3',
    'depends': [
        'integration_bridge_core',
        'pet_management',
        'sale',
        'mail',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/system_parameters.xml',
        'views/petspot_wa_intake_views.xml',
        'views/res_config_settings_views.xml',
        'views/menus.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
