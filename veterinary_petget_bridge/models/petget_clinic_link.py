from odoo import api, fields, models
from odoo.exceptions import ValidationError


class PetgetDocument(models.Model):
    _inherit = 'petget.document'

    x_pet_id = fields.Many2one(
        'x_pets', string='Clinic Pet', ondelete='cascade', index=True,
    )
    animal_id = fields.Many2one(required=False)

    @api.constrains('animal_id', 'x_pet_id')
    def _check_pet_link(self):
        for doc in self:
            if not doc.animal_id and not doc.x_pet_id:
                raise ValidationError('Link the document to a clinic pet.')


class PetgetReminder(models.Model):
    _inherit = 'petget.reminder'

    x_pet_id = fields.Many2one(
        'x_pets', string='Clinic Pet', ondelete='cascade', index=True,
    )
    animal_id = fields.Many2one(required=False)

    @api.constrains('animal_id', 'x_pet_id')
    def _check_pet_link(self):
        for reminder in self:
            if not reminder.animal_id and not reminder.x_pet_id:
                raise ValidationError('Link the reminder to a clinic pet.')


class PetgetNote(models.Model):
    _inherit = 'petget.note'

    x_pet_id = fields.Many2one(
        'x_pets', string='Clinic Pet', ondelete='cascade', index=True,
    )
    animal_id = fields.Many2one(required=False)

    @api.constrains('animal_id', 'x_pet_id')
    def _check_pet_link(self):
        for note in self:
            if not note.animal_id and not note.x_pet_id:
                raise ValidationError('Link the note to a clinic pet.')
