from odoo import fields, models


class PetgetDogColor(models.Model):
    _name = 'petget.dog.color'
    _description = 'Dog Colour'
    _order = 'name'

    name = fields.Char(string='Colour', required=True, translate=True)
    active = fields.Boolean(default=True)

    _name_uniq = models.Constraint('UNIQUE(name)', 'Colour must be unique.')
