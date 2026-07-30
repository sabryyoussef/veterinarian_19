# -*- coding: utf-8 -*-
{
    "name": "Delivery ShipBlu",
    "version": "19.0.1.5.0",
    "category": "Inventory/Delivery",
    "summary": "ShipBlu ops: import, track, pricing, pickups, settlements, SLA",
    "description": """
Delivery ShipBlu
================
Odoo Inventory → ShipBlu Shipping mirrors the merchant portal for Api-Key-capable
operations, with Duplicate AWB Guard, operational pricing/cutoffs, pickup batches,
returns financial estimates, SLA, and reporting.

Live shipment creation and pickup submission remain gated off by default.
Docs: https://docs.shipblu.com/
    """,
    "author": "Pet Spot",
    "license": "LGPL-3",
    "depends": [
        "petspot_shipblu_base",
        "stock_delivery",
        "sale_management",
        "delivery",
    ],
    "data": [
        "security/ir.model.access.csv",
        "security/shipblu_shipment_rules.xml",
        "data/delivery_carrier_data.xml",
        "data/ir_cron_data.xml",
        "wizard/shipblu_import_wizard_views.xml",
        "wizard/shipblu_portal_wizard_views.xml",
        "views/shipblu_backend_views.xml",
        "views/shipblu_coverage_views.xml",
        "views/shipblu_aux_order_views.xml",
        "views/shipblu_portal_views.xml",
        "views/shipblu_shipment_views.xml",
        "views/shipblu_ops_views.xml",
        "views/delivery_carrier_views.xml",
        "views/stock_picking_views.xml",
        "views/menu.xml",
    ],
    "installable": True,
    "application": False,
    "post_init_hook": "post_init_hook",
}
