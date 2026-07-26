# -*- coding: utf-8 -*-
{
    "name": "Dev Hub OpenProject",
    "version": "19.0.9.1.1",
    "category": "Productivity",
    "summary": "OpenProject fields, map tabs, and work-package helpers for Dev Hub",
    "author": "Sabry Youssef",
    "license": "LGPL-3",
    "depends": ["devhub_work", "openproject_sync"],
    "data": [
        "security/ir.model.access.csv",
        "views/dev_project_op_views.xml",
        "views/dev_work_op_views.xml",
    ],
    "installable": True,
    "application": True,
    "auto_install": False,
}
