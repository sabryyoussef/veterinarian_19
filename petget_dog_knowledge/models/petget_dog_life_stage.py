from odoo import fields, models


class PetgetDogLifeStage(models.Model):
    _name = 'petget.dog.life.stage'
    _description = 'Dog Life Stage'
    _order = 'sequence, age_from_weeks'

    name = fields.Char(string='Stage', required=True, translate=True)
    sequence = fields.Integer(default=10)
    age_from_weeks = fields.Integer(string='From (weeks)')
    age_to_weeks = fields.Integer(
        string='To (weeks)', help='Leave 0 for the open-ended final (senior) stage.',
    )
    feeding_guidance = fields.Text(string='Feeding & Nutrition', translate=True)
    care_focus = fields.Text(string='Care Focus', translate=True)
    notes = fields.Text(string='Notes', translate=True)
    active = fields.Boolean(default=True)
