# -*- coding: utf-8 -*-
{
    "name": "Dev Hub Sessions",
    "version": "19.0.9.1.1",
    "category": "Productivity",
    "summary": "Dev Hub development sessions and launch/resume wizards",
    "author": "Sabry Youssef",
    "license": "LGPL-3",
    "depends": ["devhub_work"],
    "data": [
        "security/ir.model.access.csv",
        "views/dev_session_views.xml",
        "views/dev_work_session_link_views.xml",
        "views/dev_launch_wizard_views.xml",
        "views/dev_resume_brief_wizard_views.xml",
        "views/dev_session_menus.xml",
    ],
    "installable": True,
    "application": True,
    "auto_install": False,
}
