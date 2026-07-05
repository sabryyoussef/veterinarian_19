# -*- coding: utf-8 -*-
{
    "name": "Social Media Connector",
    "version": "19.0.1.0.0",
    "category": "Marketing",
    "summary": "Compose Facebook posts locally and push scheduled posts to Odoo Online Social",
    "author": "Sabry Youssef",
    "license": "LGPL-3",
    "depends": ["base", "web", "mail", "base_setup"],
    "data": [
        "security/ir.model.access.csv",
        "data/ir_cron_data.xml",
        "views/social_media_page_views.xml",
        "views/social_media_post_views.xml",
        "views/res_config_settings_views.xml",
        "views/social_media_menu.xml",
    ],
    "installable": True,
    "application": True,
}
