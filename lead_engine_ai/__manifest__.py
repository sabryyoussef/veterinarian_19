# -*- coding: utf-8 -*-
{
    "name": "Lead Engine AI",
    "version": "19.0.1.1.0",
    "summary": "AI-drafted email replies for incoming CRM lead messages",
    "description": """
Lead Engine AI
==============
Watches incoming emails on CRM leads (routed via Gmail or any IMAP),
calls a configured LLM (OpenAI / Anthropic / Gemini) to draft a reply,
and presents the draft for human approval before sending.

Zero-dependency AI approach: uses direct HTTP calls to the LLM API,
no pgvector or enterprise AI module required.

Flow
----
1. External email arrives on a CRM lead
2. AI drafts a reply (background, non-blocking)
3. Smart button on the lead lights up: "N AI Drafts"
4. User clicks → sees draft → opens Odoo compose window pre-filled
5. User edits (optional) → sends
    """,
    "author": "Sabry Youssef",
    "author_email": "vendorah2@gmail.com, abhorya@gmail.com",
    "website": "https://github.com/sabryyoussef",
    "category": "Sales/CRM",
    "license": "LGPL-3",
    "application": False,
    "installable": True,
    "depends": [
        "crm",
        "mail",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/lead_engine_ai_data.xml",
        "views/lead_engine_ai_reply_views.xml",
        "views/crm_lead_views.xml",
        "views/res_config_settings_views.xml",
        "views/lead_engine_ai_menus.xml",
    ],
    "web_icon": "lead_engine_ai,static/description/icon.png",
}
