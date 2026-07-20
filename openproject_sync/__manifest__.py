# -*- coding: utf-8 -*-
{
    "name": "OpenProject Sync",
    "version": "19.0.1.5.1",
    "category": "Project",
    "summary": "Phased OpenProject ↔ Odoo work package / task sync",
    "description": """
OpenProject Sync
================
Bidirectional sync between OpenProject work packages and Odoo project.task,
rolled out in phases (pull-first, gated push).

Includes OP company classification (Edafa / Bright / …) for Project group-by.

Install and validate on pet_spot_elsahel_test (:8028) before production.
    """,
    "author": "Sabry Youssef",
    "license": "LGPL-3",
    "depends": [
        "project",
        "mail",
        "web",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/ir_cron.xml",
        "views/openproject_backend_views.xml",
        "views/openproject_project_map_views.xml",
        "views/openproject_status_map_views.xml",
        "views/openproject_user_map_views.xml",
        "views/openproject_sync_log_views.xml",
        "views/project_task_views.xml",
        "views/project_task_search_views.xml",
        "views/project_project_views.xml",
        "views/openproject_task_realign_views.xml",
        "views/menus.xml",
    ],
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": True,
    "auto_install": False,
}
