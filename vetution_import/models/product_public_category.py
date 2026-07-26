# -*- coding: utf-8 -*-

from odoo import fields, models


class ProductPublicCategory(models.Model):
    _inherit = "product.public.category"

    vetution_id = fields.Integer(
        index=True,
        copy=False,
        help="Source category or sub_category id for Phase 2 upserts.",
    )
    vetution_slug = fields.Char(index=True, copy=False)

    _product_public_category_vetution_id_uniq = models.Constraint(
        "UNIQUE(vetution_id)",
        "Vetution public category source id must be unique.",
    )
