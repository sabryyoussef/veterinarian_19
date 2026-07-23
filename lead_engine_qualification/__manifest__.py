# -*- coding: utf-8 -*-
{
    "name": "Lead Engine Qualification",
    "summary": "Scoring, assignment, identity map, and CRM lead extensions for Lead Engine",
    "version": "19.0.1.1.0",
    "category": "Sales/CRM",
    "author": "Sabry Youssef",
    "author_email": "vendorah2@gmail.com, abhorya@gmail.com",
    "website": "https://github.com/sabryyoussef",
    "license": "LGPL-3",
    "depends": ["lead_engine_core"],
    "data": [
        "security/ir.model.access.csv",
        "views/crm_lead_views.xml",
        "views/lead_engine_identity_map_views.xml",
        "views/lead_engine_score_rule_views.xml",
        "views/lead_engine_assignment_rule_views.xml",
        "views/menuitem.xml",
    ],
    "demo": [
        "demo/demo_rules.xml",
        "demo/demo_hosp_rules.xml",
    ],
    "installable": True,
    "application": True,
}

