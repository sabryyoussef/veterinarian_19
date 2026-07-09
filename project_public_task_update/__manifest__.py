# -*- coding: utf-8 -*-
{
    "name": "Project Public Task Update",
    "version": "19.0.1.2.0",
    "category": "Project",
    "summary": "Tokenized public Odoo form for external task updates (no login)",
    "description": """
Public task update links
========================
Share a tokenized Odoo URL (/task/update/<token>) via WhatsApp or Chatwoot.
External users submit missing information; data is saved as chatter on the task.

OpenProject is never exposed publicly. Install on test DB first.
    """,
    "author": "Sabry Youssef",
    "license": "LGPL-3",
    "depends": [
        "project",
        "mail",
    ],
    "data": [
        "views/public_task_update_templates.xml",
        "views/project_task_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
