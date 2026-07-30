# -*- coding: utf-8 -*-
{
    "name": "PetSpot Fulfillment Orchestration",
    "version": "19.0.1.0.0",
    "category": "Sales/Sales",
    "summary": "Order fulfillment state machine: Shopify B2B RFQ + WhatsApp availability + ShipBlu gates",
    "description": """
PetSpot Fulfillment Orchestration
=================================
Coordinates two parallel paths without changing the Shopify catalog or theme:

* Path A — Supplier-backed B2B (Shopify order → RFQ → approval/payment → ShipBlu)
* Path B — Manual WhatsApp availability inquiry → quotation/draft → fulfill

Does NOT modify products, variants, collections, inventory quantities,
petspot.availability_mode, or storefront theme files.

Depends on the existing Shopify connector and ShipBlu Duplicate AWB Guard.
    """,
    "author": "Pet Spot",
    "license": "LGPL-3",
    "depends": [
        "sale_management",
        "purchase",
        "stock",
        "mail",
        "custom_odoo_shopify_connector",
        "delivery_shipblu",
    ],
    "data": [
        "security/petspot_fulfillment_security.xml",
        "security/ir.model.access.csv",
        "data/ir_sequence_data.xml",
        "data/ir_config_parameter_data.xml",
        "views/petspot_fulfillment_case_views.xml",
        "views/petspot_availability_inquiry_views.xml",
        "views/sale_order_views.xml",
        "views/purchase_order_views.xml",
        "views/menu.xml",
        "wizard/petspot_fulfillment_transition_wizard_views.xml",
        "wizard/petspot_mark_paid_wizard_views.xml",
        "wizard/petspot_supplier_confirm_wizard_views.xml",
    ],
    "demo": [],
    "installable": True,
    "application": True,
    "auto_install": False,
}
