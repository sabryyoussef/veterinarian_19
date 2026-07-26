# -*- coding: utf-8 -*-
{
    "name": "Dev Hub Core",
    "version": "19.0.9.1.1",
    "category": "Productivity",
    "summary": "Dev Hub registry identity: projects, machines, environments, repositories",
    "author": "Sabry Youssef",
    "license": "LGPL-3",
    "depends": ["base", "mail", "web"],
    "data": [
        "security/devhub_core_security.xml",
        "security/ir.model.access.csv",
        "data/devhub_core_seed.xml",
        "views/dev_dashboard_views.xml",
        "views/dev_registry_views.xml",
        "views/devhub_core_menus.xml",
    ],
    "installable": True,
    "application": True,
    "auto_install": False,
}
