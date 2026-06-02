from odoo import fields, models


class PetgetBreedGrowth(models.Model):
    _name = 'petget.breed.growth'
    _description = 'Breed Growth Milestone'
    _order = 'breed_id, sequence, age_from_weeks'

    breed_id = fields.Many2one(
        'petget.dog.breed', string='Breed', required=True, ondelete='cascade',
        index=True,
    )
    sequence = fields.Integer(default=10)
    name = fields.Char(string='Age', required=True, help='e.g. "8 weeks", "6 months", "Adult".')
    age_from_weeks = fields.Integer(string='From (weeks)')
    age_to_weeks = fields.Integer(string='To (weeks)', help='Leave 0 for the open-ended adult row.')
    weight_min_kg = fields.Float(string='Weight min (kg)')
    weight_max_kg = fields.Float(string='Weight max (kg)')
    note = fields.Text(string='Notes')
