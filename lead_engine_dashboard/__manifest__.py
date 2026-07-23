# -*- coding: utf-8 -*-
{
    "name": "Lead Engine Dashboard",
    "summary": "Read-only analytics for Lead Engine (sources, qualification, intake)",
    "version": "19.0.1.0.0",
    "category": "Sales/CRM",
    "author": "Sabry Youssef",
    "author_email": "vendorah2@gmail.com, abhorya@gmail.com",
    "website": "https://github.com/sabryyoussef",
    "license": "LGPL-3",
    "depends": ["lead_engine_core", "lead_engine_qualification"],
    "data": [
        "views/crm_lead_analytics_views.xml",
        "views/intake_log_analytics_views.xml",
        "views/menus.xml",
    ],
    "installable": True,
    "application": True,
}

