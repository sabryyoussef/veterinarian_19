# -*- coding: utf-8 -*-

from odoo import fields, models


class VetutionSpecies(models.Model):
    _name = "vetution.species"
    _description = "Vetution Species"
    _order = "name, id"

    name = fields.Char(required=True)
    vetution_id = fields.Integer(index=True)

    _vetution_species_vetution_id_uniq = models.Constraint(
        "UNIQUE(vetution_id)",
        "Vetution species source id must be unique.",
    )
