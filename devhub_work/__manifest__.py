# -*- coding: utf-8 -*-
{
    "name": "Dev Hub Work",
    "version": "19.0.9.1.4",
    "category": "Productivity",
    "summary": "Dev Hub work lifecycle, source messages, and core artifacts",
    "author": "Sabry Youssef",
    "license": "LGPL-3",
    "depends": ["devhub_core", "project"],
    "data": [
        "security/ir.model.access.csv",
        "data/dev_project_alias_seed.xml",
        "views/dev_work_views.xml",
        "views/dev_work_origin_views.xml",
        "views/dev_project_alias_views.xml",
        "views/dev_work_menus.xml",
    ],
    "installable": True,
    "application": True,
    "auto_install": False,
}
