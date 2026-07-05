from odoo import api, fields, models


class PetgetDocument(models.Model):
    _name = 'petget.document'
    _description = 'Animal Document'
    _order = 'upload_date desc, id desc'

    name = fields.Char(string='Title', required=True)
    animal_id = fields.Many2one(
        'petget.animal', string='Animal', required=True, ondelete='cascade',
        index=True,
    )
    category = fields.Selection(
        selection=[
            ('pedigree', 'Pedigree Certificate'),
            ('vaccination', 'Vaccination Record'),
            ('microchip', 'Microchip Certificate'),
            ('health_check', 'Health Check'),
            ('registration', 'Registration Paper'),
            ('dna_test', 'DNA Test Result'),
            ('training', 'Training Certificate'),
            ('other', 'Other'),
        ],
        string='Category', required=True, default='other',
    )
    # Stored privately in the filestore — requires authentication to download.
    file = fields.Binary(string='File', attachment=True, required=True)
    file_name = fields.Char(string='File Name')

    issue_date = fields.Date(string='Issue Date')
    expiry_date = fields.Date(string='Expiry Date')
    uploaded_by_id = fields.Many2one(
        'res.users', string='Uploaded By', readonly=True,
        default=lambda self: self.env.user,
    )
    upload_date = fields.Datetime(
        string='Upload Date', readonly=True, default=fields.Datetime.now,
    )
    notes = fields.Text(string='Notes')
    company_id = fields.Many2one(
        'res.company', string='Company',
        default=lambda self: self.env.company,
    )
