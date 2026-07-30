# -*- coding: utf-8 -*-
{
    "name": "PetSpot Fulfillment × Vetution Bridge",
    "version": "19.0.1.4.0",
    "category": "Sales/Sales",
    "summary": "Phase 15B: synthetic E2E workflow orchestration (locks OFF on Production)",
    "description": """
PetSpot Fulfillment × Vetution Bridge
=====================================
Shadow landed cost + TEST workflow orchestration:

* Separated product vs delivery economics (Giza origin)
* Synthetic TEST cost profile (NOT for commerce)
* Auto-quote / messaging / payment / RFQ task / Giza receipt / mock AWB
* Price publish queue (mocked)

Production transactional flags remain OFF. Synthetic values must never
be copied into Production commercial policy.
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
        "data/synthetic_test_policy_data.xml",
        "data/message_template_data.xml",
        "data/automation_allowlist_data.xml",
        "data/ir_config_parameter_data.xml",
        "data/ir_config_parameter_workflow.xml",
        "data/ir_cron_data.xml",
        "views/landed_cost_policy_views.xml",
        "views/supplier_snapshot_views.xml",
        "views/shadow_assessment_views.xml",
        "views/mapping_review_views.xml",
        "views/automation_allowlist_views.xml",
        "views/availability_inquiry_views.xml",
        "views/message_template_views.xml",
        "views/quotation_ledger_views.xml",
        "views/payment_trust_views.xml",
        "views/price_publish_queue_views.xml",
        "views/data_health_views.xml",
        "views/workflow_views.xml",
        "views/menu.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
