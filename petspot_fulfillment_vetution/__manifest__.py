# -*- coding: utf-8 -*-
{
    "name": "PetSpot Fulfillment × Vetution Bridge",
    "version": "19.0.1.3.1",
    "category": "Sales/Sales",
    "summary": "Phase 15A.4: separated product vs delivery economics (Giza origin)",
    "description": """
PetSpot Fulfillment × Vetution Bridge (Phase 15A)
================================================
Connects petspot_fulfillment to vetution_import / vetution_supplier for
shadow assessments only:

* Resolve exact Vetution size mapping (never title-only)
* Immutable sanitized supplier snapshots
* Landed-cost worksheet + suggested_price with safety gates
* Mapping review queue with audit history

Does NOT create quotations, RFQ/PO, customer messages, Odoo/Shopify price
writes, payments, deliveries, or ShipBlu AWBs. Does NOT enable Production
commercial crons.
    """,
    "author": "Pet Spot",
    "license": "LGPL-3",
    "depends": [
        "petspot_fulfillment",
        "vetution_supplier",
        "petspot_shipblu_base",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/landed_cost_policy_data.xml",
        "data/packaging_payment_data.xml",
        "data/delivery_revenue_rule_data.xml",
        "data/automation_allowlist_data.xml",
        "data/ir_config_parameter_data.xml",
        "views/landed_cost_policy_views.xml",
        "views/supplier_snapshot_views.xml",
        "views/shadow_assessment_views.xml",
        "views/mapping_review_views.xml",
        "views/automation_allowlist_views.xml",
        "views/availability_inquiry_views.xml",
        "views/menu.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
