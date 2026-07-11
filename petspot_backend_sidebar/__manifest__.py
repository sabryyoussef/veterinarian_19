# -*- coding: utf-8 -*-
{
    'name': 'PetSpot Backend Sidebar (Clinic Hub)',
    'version': '19.0.1.1.1',
    'category': 'Services',
    'summary': 'Clinic Hub dashboard with left sidebar for common PetSpot workflows',
    'description': """
PetSpot Clinic Hub
==================
Lightweight backend landing page with an internal left sidebar that opens
existing Odoo apps/actions. Does not replace the Enterprise home menu or
patch the global WebClient.
    """,
    'author': 'Sabry Youssef',
    'license': 'LGPL-3',
    'depends': [
        'web',
        'web_enterprise',
        'pet_management',
        'petspot_wa_intake',
        'petspot_clinic_portal',
        'sale_management',
        'point_of_sale',
        'stock',
        'account',
        'crm',
    ],
    'data': [
        'views/menus.xml',
    ],
    # No custom models — empty ACL file intentionally omitted.
    'assets': {
        'web.assets_backend': [
            'petspot_backend_sidebar/static/src/clinic_hub/**/*',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}
