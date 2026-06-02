from odoo import fields, models


class PetgetAnimal(models.Model):
    _inherit = 'petget.animal'

    breed_id = fields.Many2one('petget.dog.breed', string='Breed')
    coat_type = fields.Selection(
        selection=[
            ('smooth', 'Smooth'),
            ('wire', 'Wire'),
            ('long', 'Long'),
            ('double', 'Double'),
            ('curly', 'Curly'),
        ],
        string='Coat Type',
    )
    temporary_id = fields.Char(string='Temporary ID (puppy)')
    collar_color = fields.Char(string='Collar Colour')
    akc_number = fields.Char(string='AKC Registration #')
