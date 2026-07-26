# -*- coding: utf-8 -*-

from odoo import api, fields, models

VETUTION_PRODUCT_URL = "https://vetution.com/products/{slug}"


class ProductTemplate(models.Model):
    _inherit = "product.template"

    # Identity / provenance
    vetution_id = fields.Integer(index=True, copy=False)
    vetution_slug = fields.Char(index=True, copy=False)
    vetution_url = fields.Char(
        compute="_compute_vetution_url",
        store=False,
    )
    vetution_synced_on = fields.Datetime(copy=False)
    vetution_raw_json = fields.Text(
        copy=False,
        help="Full detail payload from Vetution for debugging/replay.",
    )

    # Taxonomy & relations
    vetution_brand_id = fields.Many2one(
        comodel_name="vetution.brand",
        string="Vetution Brand",
        index=True,
        ondelete="set null",
    )
    vetution_species_ids = fields.Many2many(
        comodel_name="vetution.species",
        relation="product_template_vetution_species_rel",
        column1="product_tmpl_id",
        column2="species_id",
        string="Vetution Species",
    )
    vetution_ingredient_ids = fields.Many2many(
        comodel_name="vetution.ingredient",
        relation="product_template_vetution_ingredient_rel",
        column1="product_tmpl_id",
        column2="ingredient_id",
        string="Vetution Ingredients",
    )
    vetution_country_ids = fields.Many2many(
        comodel_name="res.country",
        relation="product_template_vetution_country_rel",
        column1="product_tmpl_id",
        column2="country_id",
        string="Vetution Countries",
        help="Source uses short names (e.g. UAE); Phase 2 maps to res.country.",
    )

    # Content
    vetution_content_ids = fields.One2many(
        comodel_name="vetution.content.block",
        inverse_name="product_tmpl_id",
        string="Vetution Content Blocks",
    )
    vetution_description = fields.Html(sanitize=False)
    vetution_composition = fields.Html(sanitize=False)
    vetution_dosage = fields.Html(sanitize=False)
    vetution_indications = fields.Html(sanitize=False)
    vetution_contraindications = fields.Html(sanitize=False)
    vetution_side_effects = fields.Html(sanitize=False)
    vetution_precautions = fields.Html(sanitize=False)
    vetution_warnings = fields.Html(sanitize=False)
    vetution_storage = fields.Html(sanitize=False)
    vetution_features = fields.Html(sanitize=False)
    vetution_feeding_guide = fields.Html(sanitize=False)
    vetution_analytical_constituents = fields.Html(sanitize=False)
    vetution_how_to_use = fields.Html(sanitize=False)
    vetution_video_html = fields.Html(sanitize=False)

    # SEO / flags
    vetution_meta_title = fields.Char()
    vetution_meta_description = fields.Text()
    vetution_cold_chain = fields.Boolean(
        help="From list endpoint cold_chain (0/1).",
    )
    vetution_show_price = fields.Boolean()
    vetution_rate = fields.Float(digits=(3, 2))
    vetution_rates_count = fields.Integer()

    # Cross-links (fill on a second pass after all products exist)
    vetution_similar_ids = fields.Many2many(
        comodel_name="product.template",
        relation="vetution_similar_rel",
        column1="product_tmpl_id",
        column2="similar_tmpl_id",
        string="Vetution Similar Products",
    )
    vetution_alternative_ids = fields.Many2many(
        comodel_name="product.template",
        relation="vetution_alternative_rel",
        column1="product_tmpl_id",
        column2="alternative_tmpl_id",
        string="Vetution Alternative Products",
    )

    _product_template_vetution_id_uniq = models.Constraint(
        "UNIQUE(vetution_id)",
        "Vetution product source id must be unique.",
    )

    @api.depends("vetution_slug")
    def _compute_vetution_url(self):
        for product in self:
            slug = product.vetution_slug
            product.vetution_url = (
                VETUTION_PRODUCT_URL.format(slug=slug) if slug else False
            )
