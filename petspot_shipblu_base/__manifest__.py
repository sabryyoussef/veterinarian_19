# -*- coding: utf-8 -*-
{
    "name": "Pet Spot ShipBlu Base",
    "version": "19.0.1.5.0",
    "category": "Inventory/Delivery",
    "summary": "Shared ShipBlu API client, credentials, pricing, and operational config",
    "description": """
Pet Spot ShipBlu Base
=====================
Company-scoped ShipBlu API configuration (Api-Key), HTTP client, sanitized
request logging, connection tests, pricing rules, volume discounts, package
sizes, SLA, settlements, and cost estimation engine.

Docs: https://docs.shipblu.com/
    """,
    "author": "Pet Spot",
    "license": "LGPL-3",
    "depends": ["base", "mail"],
    "data": [
        "security/shipblu_security.xml",
        "security/ir.model.access.csv",
        "data/ir_sequence_data.xml",
        "views/shipblu_backend_views.xml",
        "views/shipblu_api_log_views.xml",
        "views/shipblu_ops_views.xml",
        "views/menu.xml",
    ],
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": False,
}
