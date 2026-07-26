# -*- coding: utf-8 -*-
{
    "name": "Dev Hub Odoo Runtime",
    "version": "19.0.9.1.1",
    "category": "Productivity",
    "summary": "Shared Odoo major-version runtime stacks and addon sources",
    "author": "Sabry Youssef",
    "license": "LGPL-3",
    "depends": ["devhub_core"],
    "data": [
        "security/ir.model.access.csv",
        "views/dev_odoo_runtime_views.xml",
    ],
    "installable": True,
    "application": True,
    "auto_install": False,
}
