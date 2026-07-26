# -*- coding: utf-8 -*-

from odoo import fields, models


class ProductProduct(models.Model):
    _inherit = "product.product"

    vetution_size_id = fields.Integer(
        index=True,
        copy=False,
        help="Source drug_size_id (e.g. 5488).",
    )
    vetution_size_name = fields.Char(
        copy=False,
        help="Raw size string from Vetution (e.g. '30 tablets').",
    )
    vetution_out_of_stock = fields.Boolean(copy=False)
    vetution_expire_date = fields.Date(copy=False)
    vetution_image_url = fields.Char(
        copy=False,
        help="Per-size image URL from Vetution.",
    )
    vetution_old_price = fields.Float(copy=False)

    _product_product_vetution_size_id_uniq = models.Constraint(
        "UNIQUE(vetution_size_id)",
        "Vetution size source id must be unique.",
    )
