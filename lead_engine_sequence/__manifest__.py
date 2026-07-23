# -*- coding: utf-8 -*-
{
    "name": "Lead Engine Sequence",
    "summary": "Lightweight playbook / sequence layer for CRM leads (MVP, no automation_oca)",
    "version": "19.0.3.1.0",
    "category": "Sales/CRM",
    "author": "Sabry Youssef",
    "author_email": "vendorah2@gmail.com, abhorya@gmail.com",
    "website": "https://github.com/sabryyoussef",
    "license": "LGPL-3",
    "depends": ["lead_engine_qualification", "mail"],
    "data": [
        "security/ir.model.access.csv",
        "data/ir_cron.xml",
        "views/lead_engine_playbook_run_views.xml",
        "views/lead_engine_playbook_views.xml",
        "views/lead_engine_playbook_step_views.xml",
        "views/lead_engine_playbook_wizard_views.xml",
        "views/lead_engine_playbook_analytics_menu.xml",
        "views/crm_lead_views.xml",
        "views/lead_engine_source_views.xml",
        "views/menuitem.xml",
    ],
    "demo": [
        "demo/demo_playbooks.xml",
        "demo/demo_hosp_playbooks.xml",
    ],
    "installable": True,
    "application": True,
}

