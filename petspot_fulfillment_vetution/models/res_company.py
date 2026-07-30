# -*- coding: utf-8 -*-
from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    petspot_ops_owner_product_id = fields.Many2one(
        "res.users",
        string="Ops Owner — Product Mapping",
        help="Receives Vetution mapping activities.",
    )
    petspot_ops_owner_purchasing_id = fields.Many2one(
        "res.users",
        string="Ops Owner — Purchasing",
    )
    petspot_ops_owner_finance_id = fields.Many2one(
        "res.users",
        string="Ops Owner — Finance / Payment",
    )
    petspot_ops_owner_sales_id = fields.Many2one(
        "res.users",
        string="Ops Owner — Sales / Customer Service",
    )
    petspot_ops_owner_shipping_id = fields.Many2one(
        "res.users",
        string="Ops Owner — Shipping",
    )
    petspot_ops_owner_warehouse_id = fields.Many2one(
        "res.users",
        string="Ops Owner — Giza Warehouse",
    )
    petspot_ops_owner_store_id = fields.Many2one(
        "res.users",
        string="Ops Owner — Store Pickup",
    )
    petspot_ops_owner_manager_id = fields.Many2one(
        "res.users",
        string="Ops Owner — Fulfillment Manager / Escalation",
    )
