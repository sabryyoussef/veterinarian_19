# -*- coding: utf-8 -*-

from odoo import api, fields, models

from .content_labels import normalize_label


class VetutionIngredient(models.Model):
    _name = "vetution.ingredient"
    _description = "Vetution Ingredient"
    _order = "name, id"

    name = fields.Char(required=True)
    vetution_id = fields.Integer(index=True)
    name_normalized = fields.Char(
        index=True,
        help="Lowercased/stripped name for Phase 2 dedupe against inconsistent casing.",
    )

    _vetution_ingredient_vetution_id_uniq = models.Constraint(
        "UNIQUE(vetution_id)",
        "Vetution ingredient source id must be unique.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name") and not vals.get("name_normalized"):
                vals["name_normalized"] = normalize_label(vals["name"])
        return super().create(vals_list)

    def write(self, vals):
        if "name" in vals and "name_normalized" not in vals:
            vals = dict(vals, name_normalized=normalize_label(vals["name"]))
        return super().write(vals)
