# -*- coding: utf-8 -*-
{
    "name": "Dev Hub Execution",
    "version": "19.0.9.1.1",
    "category": "Productivity",
    "summary": "Isolated execution workspaces, checkpoints, and worker leases",
    "author": "Sabry Youssef",
    "license": "LGPL-3",
    "depends": ["devhub_session", "devhub_plan"],
    "data": [
        "security/ir.model.access.csv",
        "views/dev_execution_views.xml",
        "views/dev_work_checkpoint_views.xml",
        "views/dev_execution_menus.xml",
    ],
    "installable": True,
    "application": True,
    "auto_install": False,
}
