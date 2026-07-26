# -*- coding: utf-8 -*-
{
    "name": "Dev Hub Outbox",
    "version": "19.0.9.1.1",
    "category": "Productivity",
    "summary": "External outbox lease/ack service APIs for Chatwoot and OpenProject",
    "author": "Sabry Youssef",
    "license": "LGPL-3",
    "depends": ["devhub_work"],
    "data": [
        "security/ir.model.access.csv",
        "views/dev_integration_views.xml",
        "views/dev_outbox_service_views.xml",
    ],
    "installable": True,
    "application": True,
    "auto_install": False,
}
