# -*- coding: utf-8 -*-
{
    "name": "Dev Hub Generation",
    "version": "19.0.9.1.2",
    "category": "Productivity",
    "summary": "Generic generation lease engine for Dev Hub draft artifacts",
    "author": "Sabry Youssef",
    "license": "LGPL-3",
    "depends": ["devhub_work", "devhub_analysis", "devhub_plan"],
    "data": [
        "security/ir.model.access.csv",
        "views/dev_work_generation_views.xml",
        "views/dev_work_generation_link_views.xml",
        "views/dev_generation_views.xml",
    ],
    "installable": True,
    "application": True,
    "auto_install": False,
}
