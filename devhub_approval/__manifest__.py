# -*- coding: utf-8 -*-
{
    "name": "Dev Hub Approval",
    "version": "19.0.9.1.1",
    "category": "Productivity",
    "summary": "Plan approval records and reusable approval mixin for Dev Hub",
    "author": "Sabry Youssef",
    "license": "LGPL-3",
    "depends": ["devhub_plan"],
    "data": [
        "security/ir.model.access.csv",
        "views/dev_approval_views.xml",
    ],
    "installable": True,
    "application": True,
    "auto_install": False,
}
