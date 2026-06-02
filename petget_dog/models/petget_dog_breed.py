from odoo import fields, models


class PetgetDogBreed(models.Model):
    _name = 'petget.dog.breed'
    _description = 'Dog Breed'
    _order = 'name'

    name = fields.Char(string='Breed', required=True, index='trigram')
    akc_group = fields.Selection(
        selection=[
            ('sporting', 'Sporting'),
            ('hound', 'Hound'),
            ('working', 'Working'),
            ('terrier', 'Terrier'),
            ('toy', 'Toy'),
            ('non_sporting', 'Non-Sporting'),
            ('herding', 'Herding'),
            ('foundation', 'Foundation Stock'),
            ('misc', 'Miscellaneous'),
            ('other', 'Other'),
        ],
        string='AKC Group',
    )
    size = fields.Selection(
        selection=[
            ('small', 'Small'),
            ('medium', 'Medium'),
            ('large', 'Large'),
            ('giant', 'Giant'),
        ],
        string='Size',
    )
    active = fields.Boolean(default=True)

    _name_uniq = models.Constraint('UNIQUE(name)', 'Breed name must be unique.')
