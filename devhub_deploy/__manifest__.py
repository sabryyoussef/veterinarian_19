# -*- coding: utf-8 -*-
{
    "name": "Dev Hub Deploy",
    "version": "19.0.9.1.1",
    "category": "Productivity",
    "summary": "Test/Staging/Production deploy approvals, records, and rollback",
    "author": "Sabry Youssef",
    "license": "LGPL-3",
    "depends": ["devhub_github"],
    "data": [
        "security/ir.model.access.csv",
        "views/dev_deploy_views.xml",
        "views/dev_deploy_wizard_views.xml",
        "views/dev_deploy_menus.xml",
    ],
    "installable": True,
    "application": True,
    "auto_install": False,
}
