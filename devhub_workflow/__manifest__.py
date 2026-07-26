# -*- coding: utf-8 -*-
{
    "name": "Dev Hub Workflow",
    "version": "19.0.9.1.2",
    "category": "Productivity",
    "summary": "Interactive JS walkthrough from WhatsApp intake to completion",
    "author": "Sabry Youssef",
    "license": "LGPL-3",
    "depends": ["devhub_work", "web"],
    "data": [
        "security/ir.model.access.csv",
        "data/dev_workflow_capabilities.xml",
        "views/dev_workflow_views.xml",
        "views/dev_workflow_menus.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "devhub_workflow/static/src/workflow_guide/workflow_guide.css",
            "devhub_workflow/static/src/workflow_guide/workflow_guide.js",
            "devhub_workflow/static/src/workflow_guide/workflow_guide.xml",
        ],
    },
    "installable": True,
    "application": True,
    "auto_install": False,
}
