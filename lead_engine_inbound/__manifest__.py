# -*- coding: utf-8 -*-
{
    "name": "Lead Engine Inbound",
    "summary": "HTTP intake, validation, and synchronous qualification orchestration",
    "version": "19.0.1.1.1",
    "category": "Sales/CRM",
    "author": "Sabry Youssef",
    "author_email": "vendorah2@gmail.com, abhorya@gmail.com",
    "website": "https://github.com/sabryyoussef",
    "license": "LGPL-3",
    "depends": ["lead_engine_core", "lead_engine_qualification", "lead_engine_sequence"],
    "data": [
        "views/lead_engine_source_views.xml",
    ],
    "demo": [
        "data/demo_lead_engine_mvp.xml",
        "data/demo_hosp_inbound.xml",
    ],
    "installable": True,
    "application": False,
}

