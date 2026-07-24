# -*- coding: utf-8 -*-
{
    "name": "Dev Hub Analysis",
    "version": "19.0.9.1.1",
    "category": "Productivity",
    "summary": "Business analysis artifacts for Dev Hub work items",
    "author": "Sabry Youssef",
    "license": "LGPL-3",
    "depends": ["devhub_work", "devhub_plan"],
    "data": [
        "security/ir.model.access.csv",
        "views/dev_analysis_views.xml",
        "views/dev_analysis_menus.xml",
    ],
    "installable": True,
    "application": True,
    "auto_install": False,
}
