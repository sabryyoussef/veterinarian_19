# -*- coding: utf-8 -*-
{
    "name": "Delivery ShipBlu",
    "version": "19.0.1.1.0",
    "category": "Inventory/Delivery",
    "summary": "ShipBlu shipping from Odoo — import, track, and (gated) operate",
    "description": """
Delivery ShipBlu
================
Import ShipBlu delivery orders (including Shopify-created AWBs), match to
Odoo/Shopify orders, sync tracking, coverage maps, returns/exchanges/COD
mirrors, and gated operational actions.

Default ownership: Track Only. Creation disabled until UAT approval.
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
        "views/shipblu_backend_views.xml",
        "views/shipblu_coverage_views.xml",
        "views/shipblu_aux_order_views.xml",
        "views/shipblu_shipment_views.xml",
        "views/delivery_carrier_views.xml",
        "views/stock_picking_views.xml",
        "views/menu.xml",
    ],
    "installable": True,
    "application": False,
    "post_init_hook": "post_init_hook",
}
