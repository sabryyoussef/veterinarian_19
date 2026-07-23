# -*- coding: utf-8 -*-
{
    "name": "WhatsApp Hub",
    "version": "19.0.1.0.1",
    "category": "Productivity",
    "summary": "Authoritative Odoo WhatsApp platform (messages, groups, conversations, outbound)",
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
        "views/whatsapp_instance_views.xml",
        "views/whatsapp_group_views.xml",
        "views/whatsapp_contact_views.xml",
        "views/whatsapp_conversation_views.xml",
        "views/whatsapp_message_views.xml",
        "views/whatsapp_outbound_views.xml",
        "views/whatsapp_hub_menus.xml",
    ],
    "installable": True,
    "application": True,
    "auto_install": False,
}
