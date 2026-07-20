# -*- coding: utf-8 -*-
{
    "name": "Development Session Hub",
    "version": "19.0.8.1.1",
    "category": "Productivity",
    "summary": "Development work lifecycle, artifacts, checkpoints, and sessions",
    "description": """
Development Session Hub
=======================
Canonical Odoo lifecycle and artifact records for OpenProject-backed
development work. The module stores sanitized source references, versioned
analysis and plans, exact approvals, immutable checkpoints, resume briefs,
completion reports, reviewed communication drafts, and exact-state human
approval for isolated-worktree commit, push, open Pull Request, squash Merge,
repository discovery/bind/bootstrap, Selected-repository GitHub App allowlists,
Test/Staging deployment, rollback, and separately approved Production
promotion after soak evidence. Auto-merge remains disabled. Production deploy
never auto-promotes from staging.
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
        "views/dev_execution_views.xml",
        "views/dev_git_commit_views.xml",
        "views/dev_git_commit_wizard_views.xml",
        "views/dev_git_push_views.xml",
        "views/dev_git_push_wizard_views.xml",
        "views/dev_git_pr_views.xml",
        "views/dev_git_pr_wizard_views.xml",
        "views/dev_git_merge_views.xml",
        "views/dev_git_merge_wizard_views.xml",
        "views/dev_github_credentials_views.xml",
        "views/dev_repository_onboarding_views.xml",
        "views/dev_repository_onboarding_wizard_views.xml",
        "views/dev_deploy_views.xml",
        "views/dev_deploy_wizard_views.xml",
        "views/dev_launch_wizard_views.xml",
        "views/dev_resume_brief_wizard_views.xml",
        "views/dev_session_hub_menus.xml",
    ],
    "installable": True,
    "application": True,
    "auto_install": False,
}
