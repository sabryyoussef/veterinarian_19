from odoo import fields, models


class PetgetNote(models.Model):
    _name = 'petget.note'
    _description = 'Animal Activity Note'
    _order = 'note_date desc, id desc'

    animal_id = fields.Many2one(
        'petget.animal', string='Animal', required=True, ondelete='cascade',
        index=True,
    )
    note_type = fields.Selection(
        selection=[
            ('general', 'General Note'),
            ('care', 'Care Note'),
            ('health', 'Health Note'),
            ('breeding', 'Breeding Note'),
            ('followup', 'Follow-up Note'),
        ],
        string='Type', required=True, default='general',
    )
    note_date = fields.Datetime(
        string='Date', required=True, default=fields.Datetime.now,
    )
    body = fields.Text(string='Note', required=True)
    user_id = fields.Many2one(
        'res.users', string='Logged By', readonly=True,
        default=lambda self: self.env.user,
    )
    company_id = fields.Many2one(
        'res.company', default=lambda self: self.env.company,
    )
