# -*- coding: utf-8 -*-
{
    "name": "Cron Control",
    "summary": "Manage all scheduled actions (cron jobs) from one admin screen",
    "version": "19.0.1.2.0",
    "category": "Administration",
    "license": "LGPL-3",
    "author": "Sabry Youssef, Resume project",
    "author_email": "vendorah2@gmail.com, abhorya@gmail.com",
    "website": "https://github.com/sabryyoussef",
    "depends": ["base"],
    "data": [
        "security/ir.model.access.csv",
        "views/resume_cron_bulk_wizard_views.xml",
        "views/ir_cron_views.xml",
        "views/cron_analytics_views.xml",
        "views/cron_control_menus.xml",
    ],
    "installable": True,
    "application": True,
}
