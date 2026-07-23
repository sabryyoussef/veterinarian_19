# -*- coding: utf-8 -*-
{
    'name': 'Developer Hub',
    'version': '19.0.1.1.0',
    'category': 'Productivity',
    'summary': 'App shell menus for Sabry Odoo Developer / Partner Outreach',
    'author': 'Sabry Youssef',
    'license': 'LGPL-3',
    'depends': ['base', 'crm', 'contacts', 'odoo_partners'],
    'data': [
        'data/crm_team_data.xml',
        'data/partner_category_data.xml',
        'views/res_partner_views.xml',
        'views/developer_hub_menus.xml',
    ],
    'installable': True,
    'application': True,
}
