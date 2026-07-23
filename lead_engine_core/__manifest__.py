# -*- coding: utf-8 -*-
{
    "name": "Lead Engine Core",
    "summary": "Source registry, intake audit log, and base security for Lead Engine",
    "version": "19.0.1.1.0",
    "category": "Sales/CRM",
    "author": "Sabry Youssef",
    "author_email": "vendorah2@gmail.com, abhorya@gmail.com",
    "website": "https://github.com/sabryyoussef",
    "license": "LGPL-3",
    "depends": ["mail", "crm", "contacts"],
    "data": [
        "security/lead_engine_security.xml",
        "security/ir.model.access.csv",
        "views/lead_engine_source_views.xml",
        "views/lead_engine_intake_log_views.xml",
        "views/res_config_settings_views.xml",
        "views/menuitem.xml",
    ],
    "demo": [
        "demo/demo_sources.xml",
        "demo/demo_hosp_sources.xml",
    ],
    "installable": True,
    "application": True,
}

