# -*- coding: utf-8 -*-
{
    "name": "Odoo Partners",
    "version": "19.0.1.1.0",
    "category": "Tools",
    "summary": "Odoo partner directory categories + optional demo partner dump",
    "author": "Sabry Youssef",
    "license": "LGPL-3",
    "depends": ["base", "contacts"],
    "data": [
        "data/res_partner_category_data.xml",
    ],
    "demo": [
        "demo/res_partner_demo.xml",
    ],
    "installable": True,
    "application": False,
}
