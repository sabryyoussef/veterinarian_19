# -*- coding: utf-8 -*-
{
    "name": "Pet Spot WhatsApp Marketing Queue",
    "version": "19.0.1.1.0",
    "category": "Marketing",
    "summary": "Fail-closed WhatsApp marketing campaigns (petspot-marketing only)",
    "description": """
Campaign-once approval, rate-limited queue, consent-gated eligibility.
Transport: Evolution instance petspot-marketing only. Never sabry min.
Global pause defaults ON after install. TEST/UAT first.
Tag-based configured audiences (e.g. SAHEL_TAGGED_CLIENTS_2020_2026); tags never equal consent.
    """,
    "author": "Pet Spot",
    "license": "LGPL-3",
    "depends": [
        "base",
        "mail",
        "contacts",
        "petspot_wa_marketing_consent",
    ],
    "data": [
        "security/queue_security.xml",
        "security/ir.model.access.csv",
        "data/settings_data.xml",
        "data/audience_data.xml",
        "data/ir_cron_data.xml",
        "views/template_views.xml",
        "views/audience_views.xml",
        "views/campaign_views.xml",
        "views/queue_views.xml",
        "views/event_views.xml",
        "views/settings_views.xml",
        "views/menu.xml",
    ],
    "demo": [],
    "installable": True,
    "application": False,
}
