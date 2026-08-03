# -*- coding: utf-8 -*-
{
    "name": "PetSpot Legacy WA Marketing Guard",
    "version": "19.0.1.0.0",
    "category": "Marketing",
    "summary": "Block legacy wa.campaign / bulk marketing; keep marketing on petspot_wa_marketing_queue",
    "description": """
Hard server-side + UI containment for legacy evolution_whatsapp_chat marketing paths.

Install on TEST first. Do not deploy to production without separate approval.
Does not block individual Discuss/WhatsApp chat or operational single-recipient sends.
    """,
    "author": "Pet Spot",
    "license": "LGPL-3",
    "depends": [
        "evolution_whatsapp_chat",
        "petspot_wa_marketing_queue",
    ],
    "data": [
        "views/wa_campaign_guard_views.xml",
        "views/whatsapp_bulk_guard_views.xml",
    ],
    "installable": True,
    "application": False,
}
