# -*- coding: utf-8 -*-
{
    "name": "Dev Hub Git",
    "version": "19.0.9.1.1",
    "category": "Productivity",
    "summary": "Governed local Git commit and push",
    "author": "Sabry Youssef",
    "license": "LGPL-3",
    "depends": ["devhub_execution"],
    "data": [
        "security/ir.model.access.csv",
        "views/dev_git_commit_views.xml",
        "views/dev_git_commit_wizard_views.xml",
        "views/dev_git_push_views.xml",
        "views/dev_git_push_wizard_views.xml",
        "views/dev_execution_git_views.xml",
        "views/dev_repository_git_views.xml",
        "views/dev_git_menus.xml",
    ],
    "installable": True,
    "application": True,
    "auto_install": False,
}
