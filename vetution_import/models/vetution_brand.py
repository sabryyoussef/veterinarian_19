# -*- coding: utf-8 -*-

from odoo import api, fields, models


class VetutionBrand(models.Model):
    _name = "vetution.brand"
    _description = "Vetution Brand"
    _order = "name, id"

    name = fields.Char(required=True)
    slug = fields.Char(required=True, index=True)
    vetution_id = fields.Integer(index=True)
    logo = fields.Binary(attachment=True)
    logo_url = fields.Char()
    facebook_page = fields.Char()
    info = fields.Text()
    meta_title = fields.Char()
    meta_description = fields.Text()
    product_ids = fields.One2many(
        comodel_name="product.template",
        inverse_name="vetution_brand_id",
        string="Products",
    )
    product_count = fields.Integer(compute="_compute_product_count")

    _vetution_brand_slug_uniq = models.Constraint(
        "UNIQUE(slug)",
        "Vetution brand slug must be unique.",
    )
    _vetution_brand_vetution_id_uniq = models.Constraint(
        "UNIQUE(vetution_id)",
        "Vetution brand source id must be unique.",
    )

    @api.depends("product_ids")
    def _compute_product_count(self):
        for brand in self:
            brand.product_count = len(brand.product_ids)

    def action_view_products(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Products",
            "res_model": "product.template",
            "view_mode": "list,form",
            "domain": [("vetution_brand_id", "=", self.id)],
            "context": {"default_vetution_brand_id": self.id},
        }
