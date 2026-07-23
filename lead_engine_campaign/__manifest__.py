# -*- coding: utf-8 -*-
{
    "name": "Lead Engine Campaign",
    "summary": "Guided wizard to set up a complete Lead Engine campaign in minutes",
    "version": "19.0.1.0.0",
    "category": "Sales/CRM",
    "author": "Sabry Youssef",
    "author_email": "vendorah2@gmail.com, abhorya@gmail.com",
    "website": "https://github.com/sabryyoussef",
    "license": "LGPL-3",
    "depends": ["lead_engine_sequence"],
    "data": [
        "security/ir.model.access.csv",
        "views/lead_engine_source_views.xml",
        "views/lead_engine_campaign_wizard_views.xml",   # action defined here first
        "views/lead_engine_campaign_template_views.xml", # then referenced here
        "views/menuitem.xml",
        "data/campaign_templates.xml",
    ],
    "installable": True,
    "application": True,
}

