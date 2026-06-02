from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models


class PetgetAnimal(models.Model):
    _name = 'petget.animal'
    _description = 'Generic Animal Profile'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'image.mixin']
    _order = 'name, id'

    # --- Identity ---
    name = fields.Char(
        string='Call Name', required=True, tracking=True, index='trigram',
        help='The everyday name used to call this animal.',
    )
    registered_name = fields.Char(
        string='Registered Name', tracking=True,
        help='Official name as it appears on registration papers.',
    )
    system_id = fields.Char(
        string='System ID', required=True, readonly=True, copy=False,
        index=True, default=lambda self: _('New'),
        help='Stable internal reference, generated automatically.',
    )
    species = fields.Selection(
        selection=[
            ('dog', 'Dog'),
            ('cat', 'Cat'),
            ('horse', 'Horse'),
            ('other', 'Other'),
        ],
        string='Species', required=True, default='dog', tracking=True,
    )

    # --- Biological ---
    sex = fields.Selection(
        selection=[('male', 'Male'), ('female', 'Female')],
        string='Sex', required=True, tracking=True,
    )
    date_of_birth = fields.Date(string='Date of Birth', tracking=True)
    age_display = fields.Char(
        string='Age', compute='_compute_age_display',
        help='Approximate age computed from the date of birth.',
    )
    color = fields.Char(string='Color / Markings')

    # --- Identification ---
    microchip = fields.Char(string='Microchip Number', tracking=True, copy=False)
    registration_number = fields.Char(string='Registration Number', tracking=True)

    # --- Status ---
    status = fields.Selection(
        selection=[
            ('young', 'Young (Puppy/Kitten/Foal)'),
            ('active', 'Active'),
            ('breeding', 'Breeding'),
            ('retired', 'Retired'),
            ('sold', 'Sold'),
            ('rehomed', 'Rehomed'),
            ('deceased', 'Deceased'),
        ],
        string='Status', default='young', required=True, tracking=True,
    )

    # --- Ownership ---
    owner_id = fields.Many2one(
        'res.partner', string='Current Owner', tracking=True,
    )
    bred_by_id = fields.Many2one('res.partner', string='Bred By')

    # --- Pedigree (self-referential) ---
    sire_id = fields.Many2one(
        'petget.animal', string='Sire',
        domain="[('sex', '=', 'male'), ('species', '=', species)]",
    )
    dam_id = fields.Many2one(
        'petget.animal', string='Dam',
        domain="[('sex', '=', 'female'), ('species', '=', species)]",
    )

    # --- Documents ---
    document_ids = fields.One2many(
        'petget.document', 'animal_id', string='Documents',
    )
    document_count = fields.Integer(
        string='Document Count', compute='_compute_document_count',
    )

    # --- Reminders & activity notes ---
    reminder_ids = fields.One2many(
        'petget.reminder', 'animal_id', string='Reminders',
    )
    reminder_count = fields.Integer(
        string='Pending Reminders', compute='_compute_reminder_count',
    )
    note_ids = fields.One2many(
        'petget.note', 'animal_id', string='Activity Notes',
    )

    # --- Misc ---
    notes = fields.Text(string='Notes')
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company', string='Company',
        default=lambda self: self.env.company,
    )

    @api.depends('date_of_birth')
    def _compute_age_display(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if rec.date_of_birth and rec.date_of_birth <= today:
                delta = relativedelta(today, rec.date_of_birth)
                rec.age_display = '%dy %dm' % (delta.years, delta.months)
            else:
                rec.age_display = ''

    @api.depends('document_ids')
    def _compute_document_count(self):
        for rec in self:
            rec.document_count = len(rec.document_ids)

    @api.depends('reminder_ids.state')
    def _compute_reminder_count(self):
        for rec in self:
            rec.reminder_count = len(
                rec.reminder_ids.filtered(lambda r: r.state == 'pending')
            )

    @api.depends('name', 'system_id')
    def _compute_display_name(self):
        for rec in self:
            if rec.system_id and rec.system_id != _('New'):
                rec.display_name = '[%s] %s' % (rec.system_id, rec.name or '')
            else:
                rec.display_name = rec.name or ''

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('system_id') or vals['system_id'] == _('New'):
                vals['system_id'] = (
                    self.env['ir.sequence'].next_by_code('petget.animal')
                    or _('New')
                )
        return super().create(vals_list)

    def action_view_documents(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Documents'),
            'res_model': 'petget.document',
            'view_mode': 'list,form',
            'domain': [('animal_id', '=', self.id)],
            'context': {'default_animal_id': self.id},
        }

    def action_view_reminders(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Reminders'),
            'res_model': 'petget.reminder',
            'view_mode': 'list,form',
            'domain': [('animal_id', '=', self.id)],
            'context': {'default_animal_id': self.id},
        }
