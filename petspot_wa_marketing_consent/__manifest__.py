# -*- coding: utf-8 -*-
{
    "name": "Pet Spot WhatsApp Marketing Consent",
    "version": "19.0.1.0.1",
    "category": "Marketing",
    "summary": "Explicit WhatsApp marketing consent + eligibility (fail-closed)",
    "description": """
Pet Spot WhatsApp Marketing Consent
===================================
Auditable opt-in/opt-out for WhatsApp marketing. Tags, sales, and operational
messages never imply marketing consent.

Install on TEST/UAT first. Do not enable outbound marketing queues in this module.
    """,
    "author": "Pet Spot",
    "license": "LGPL-3",
    "depends": [
        "base",
        "mail",
        "contacts",
    ],
    "data": [
        "security/consent_security.xml",
        "security/ir.model.access.csv",
        "data/consent_wording_data.xml",
        "data/consent_wording_v1_1_activate.xml",
        "views/wa_marketing_consent_views.xml",
        "views/res_partner_views.xml",
        "views/menu.xml",
        "wizard/staff_consent_wizard_views.xml",
    ],
    "demo": [],
    "installable": True,
    "application": False,
}
