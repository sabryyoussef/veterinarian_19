# -*- coding: utf-8 -*-
{
    "name": "Odoo Remote Connector",
    "version": "19.0.1.0.0",
    "category": "Tools",
    "summary": "Manage and test connections to other Odoo instances via JSON-RPC",
    "author": "Sabry Youssef",
    "license": "LGPL-3",
    "depends": ["base", "web", "mail"],
    "data": [
        "security/ir.model.access.csv",
        "views/odoo_remote_connection_views.xml",
        "views/odoo_remote_connector_menu.xml",
    ],
    "installable": True,
    "application": True,
}
