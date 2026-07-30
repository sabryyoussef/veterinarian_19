# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    petspot_ops_owner_product_id = fields.Many2one(
        related="company_id.petspot_ops_owner_product_id",
        readonly=False,
    )
    petspot_ops_owner_purchasing_id = fields.Many2one(
        related="company_id.petspot_ops_owner_purchasing_id",
        readonly=False,
    )
    petspot_ops_owner_finance_id = fields.Many2one(
        related="company_id.petspot_ops_owner_finance_id",
        readonly=False,
    )
    petspot_ops_owner_sales_id = fields.Many2one(
        related="company_id.petspot_ops_owner_sales_id",
        readonly=False,
    )
    petspot_ops_owner_shipping_id = fields.Many2one(
        related="company_id.petspot_ops_owner_shipping_id",
        readonly=False,
    )
    petspot_ops_owner_warehouse_id = fields.Many2one(
        related="company_id.petspot_ops_owner_warehouse_id",
        readonly=False,
    )
    petspot_ops_owner_store_id = fields.Many2one(
        related="company_id.petspot_ops_owner_store_id",
        readonly=False,
    )
    petspot_ops_owner_manager_id = fields.Many2one(
        related="company_id.petspot_ops_owner_manager_id",
        readonly=False,
    )
