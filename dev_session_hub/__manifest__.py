# -*- coding: utf-8 -*-
{
    "name": "Development Session Hub",
    "version": "19.0.3.0.0",
    "category": "Productivity",
    "summary": "Development work lifecycle, artifacts, checkpoints, and sessions",
    "description": """
Development Session Hub
=======================
Canonical Odoo lifecycle and artifact records for OpenProject-backed
development work. The module stores sanitized source references, versioned
analysis and plans, exact approvals, immutable checkpoints, resume briefs,
completion reports, and reviewed communication drafts. It reuses the guarded
manual Cursor launcher and never changes branches, commits, pushes, deploys,
or sends directly to WhatsApp.
    """,
    "author": "Sabry Youssef",
    "license": "LGPL-3",
    "depends": ["base", "mail", "web", "project", "openproject_sync"],
    "data": [
        "security/dev_session_hub_security.xml",
        "security/ir.model.access.csv",
        "data/dev_session_hub_seed.xml",
        "views/dev_dashboard_views.xml",
        "views/dev_registry_views.xml",
        "views/dev_work_views.xml",
        "views/dev_integration_views.xml",
        "views/dev_session_views.xml",
        "views/dev_launch_wizard_views.xml",
        "views/dev_resume_brief_wizard_views.xml",
        "views/dev_session_hub_menus.xml",
    ],
    "installable": True,
    "application": True,
    "auto_install": False,
}
