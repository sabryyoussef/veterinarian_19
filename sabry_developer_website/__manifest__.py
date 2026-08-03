# -*- coding: utf-8 -*-
{
    'name': 'Sabry Developer Website',
    'version': '19.0.1.1.0',
    'category': 'Website',
    'summary': 'Personal Odoo developer Multi-Website (portfolio, CV, contact)',
    'author': 'Sabry Youssef',
    'license': 'LGPL-3',
    'depends': ['website', 'website_crm', 'crm', 'developer_hub'],
    'data': [
        'data/website_data.xml',
        'views/website_pages.xml',
        'views/templates.xml',
    ],
    'installable': True,
    'application': True,
}
