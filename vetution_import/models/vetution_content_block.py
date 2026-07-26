# -*- coding: utf-8 -*-

from odoo import api, fields, models

from .content_labels import normalize_label


class VetutionContentBlock(models.Model):
    _name = "vetution.content.block"
    _description = "Vetution Product Content Block"
    _order = "product_tmpl_id, sequence, id"

    product_tmpl_id = fields.Many2one(
        comodel_name="product.template",
        required=True,
        ondelete="cascade",
        index=True,
    )
    sequence = fields.Integer(
        default=10,
        help="Preserve the source ``other`` array order.",
    )
    label = fields.Char(
        required=True,
        help="Raw label from Vetution, verbatim (including typos).",
    )
    label_normalized = fields.Char(
        compute="_compute_label_normalized",
        store=True,
        index=True,
        help="Lowercased, colons/whitespace normalized — for grouping later.",
    )
    body_html = fields.Html(
        sanitize=False,
        help="Raw HTML from Vetution; sanitize in Phase 2 before public display.",
    )
    is_mapped = fields.Boolean(
        default=False,
        help="True if this block was also copied into a canonical Html field.",
    )

    @api.depends("label")
    def _compute_label_normalized(self):
        for block in self:
            block.label_normalized = normalize_label(block.label)
