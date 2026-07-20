# -*- coding: utf-8 -*-
{
    "name": "Project Public Task Update",
    "version": "19.0.1.4.0",
    "category": "Project",
    "summary": "Tokenized public Odoo form for external task updates (no login)",
    "description": """
Public task update links
========================
Share a tokenized Odoo URL (/task/update/<token>) via WhatsApp or Chatwoot.
External users submit missing information; data is saved as chatter on the task.

The public page may show a read-only list of direct sub-tasks (name, stage,
closed state only). OpenProject and other internal fields are never exposed.

Security (19.0.1.4.0)
---------------------
* Public POST uses standard Odoo CSRF (session cookie + csrf_token field).
* Capability tokens remain high-entropy secrets.token_urlsafe(32), unique in DB.
* Tokens are stored plaintext so reusable links can be displayed to authorized
  project users; this is an accepted risk for this release. Future work may
  move to digest-only / show-once tokens with a designed migration.
* Tokens must never appear in logs, chatter, list views, or exception messages.
* Server-side field length and list-count limits; secure response headers;
  transaction-safe per-token submit throttle.

Install on test DB first.
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
