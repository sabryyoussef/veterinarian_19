# -*- coding: utf-8 -*-
{
    "name": "WhatsApp Hub",
    "version": "19.0.1.16.0",
    "category": "Productivity",
    "summary": "WhatsApp platform (Hub, Campaign, Discuss, Integration Bridge menus)",
    "description": """
WhatsApp Hub — Consolidated Custom WhatsApp Module
==================================================
Owns the generic Odoo-side WhatsApp domain:

* Instances (Evolution)
* Groups (JID @g.us)
* Contacts
* Conversations
* Messages (inbound/outbound) with idempotency
* Outbound queue

Canonical ingress: Chatwoot-normalized event → service_ingest_normalized.

Business modules (Dev Hub, clinic, CRM) consume this module and must not
duplicate WhatsApp message infrastructure.

Does NOT own: Dev Hub work intake, clinic pet/visit/sale confirmation,
n8n/AI/Chatwoot product logic.
""",
    "author": "Sabry Youssef",
    "license": "LGPL-3",
    "depends": [
        "base",
        "mail",
        "web",
        "contacts",
    ],
    "data": [
        "security/whatsapp_hub_security.xml",
        "security/ir.model.access.csv",
        "data/ir_cron_outbound.xml",
        "data/ir_cron_discuss_hub_health.xml",
        "data/ir_cron_campaign_hub_health.xml",
        "data/ir_cron_ingestion_health.xml",
        "data/whatsapp_hub_outbound_flags.xml",
        "views/whatsapp_instance_views.xml",
        "views/whatsapp_group_views.xml",
        "views/whatsapp_contact_views.xml",
        "views/whatsapp_conversation_views.xml",
        "views/whatsapp_message_views.xml",
        "views/whatsapp_outbound_views.xml",
        "views/whatsapp_discuss_shadow_views.xml",
        "views/whatsapp_discuss_hub_health_views.xml",
        "views/whatsapp_campaign_shadow_views.xml",
        "views/whatsapp_campaign_hub_health_views.xml",
        "views/whatsapp_ingestion_health_views.xml",
        "views/whatsapp_hub_dashboard_views.xml",
        "views/whatsapp_hub_menus.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "whatsapp_hub/static/src/dashboards/dashboards.css",
            "whatsapp_hub/static/src/dashboards/general_dashboard.js",
            "whatsapp_hub/static/src/dashboards/general_dashboard.xml",
            "whatsapp_hub/static/src/dashboards/whatsapp_dashboard.js",
            "whatsapp_hub/static/src/dashboards/whatsapp_dashboard.xml",
            "whatsapp_hub/static/src/chat_thread/chat_thread.css",
            "whatsapp_hub/static/src/chat_thread/chat_thread.js",
            "whatsapp_hub/static/src/chat_thread/chat_thread.xml",
        ],
    },
    "installable": True,
    "application": True,
    "auto_install": False,
}
