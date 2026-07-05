from odoo import _, api, fields, models


class PetgetReminder(models.Model):
    _name = 'petget.reminder'
    _description = 'Animal Reminder'
    _inherit = ['mail.thread']
    _order = 'due_date, id'

    name = fields.Char(string='Title', required=True, tracking=True)
    animal_id = fields.Many2one(
        'petget.animal', string='Animal', required=True, ondelete='cascade',
        index=True,
    )
    reminder_type = fields.Selection(
        selection=[
            ('vaccination', 'Vaccination'),
            ('worming', 'Worming'),
            ('heat', 'Heat Cycle'),
            ('vet_visit', 'Vet Visit'),
            ('grooming', 'Grooming'),
            ('general', 'General'),
        ],
        string='Type', required=True, default='general', tracking=True,
    )
    due_date = fields.Date(string='Due Date', required=True, tracking=True)
    state = fields.Selection(
        selection=[('pending', 'Pending'), ('done', 'Completed')],
        string='Status', default='pending', required=True, tracking=True,
    )
    is_overdue = fields.Boolean(
        string='Overdue', compute='_compute_is_overdue',
        search='_search_is_overdue',
    )
    completed_date = fields.Date(string='Completed On', readonly=True)
    user_id = fields.Many2one(
        'res.users', string='Responsible', tracking=True,
        default=lambda self: self.env.user,
    )
    note = fields.Text(string='Notes')
    company_id = fields.Many2one(
        'res.company', default=lambda self: self.env.company,
    )

    @api.depends('state', 'due_date')
    def _compute_is_overdue(self):
        today = fields.Date.context_today(self)
        for rec in self:
            rec.is_overdue = bool(
                rec.state == 'pending' and rec.due_date and rec.due_date < today
            )

    def _search_is_overdue(self, operator, value):
        if operator not in ('=', '!='):
            raise NotImplementedError(_('Unsupported operator for Overdue search.'))
        today = fields.Date.context_today(self)
        overdue_domain = ['&', ('state', '=', 'pending'), ('due_date', '<', today)]
        not_overdue_domain = ['|', ('state', '!=', 'pending'), ('due_date', '>=', today)]
        wants_overdue = (operator == '=') == bool(value)
        return overdue_domain if wants_overdue else not_overdue_domain

    def action_done(self):
        self.write({
            'state': 'done',
            'completed_date': fields.Date.context_today(self),
        })

    def action_reset(self):
        self.write({'state': 'pending', 'completed_date': False})
