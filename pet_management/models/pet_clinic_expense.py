# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError


class PetClinicExpense(models.Model):
    _name = 'pet.clinic.expense'
    _description = 'Clinic Expense'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(
        string='Reference',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _('New'),
        tracking=True,
    )
    date = fields.Date(
        required=True,
        default=fields.Date.context_today,
        tracking=True,
        index=True,
    )
    amount = fields.Monetary(required=True, tracking=True, currency_field='currency_id')
    currency_id = fields.Many2one(
        'res.currency',
        required=True,
        default=lambda self: self.env.company.currency_id,
    )
    description = fields.Char(required=True, tracking=True)
    category_id = fields.Many2one(
        'pet.expense.category',
        required=True,
        tracking=True,
        check_company=True,
    )
    funding_source_id = fields.Many2one(
        'pet.funding.source',
        string='Paid From',
        required=True,
        tracking=True,
        check_company=True,
    )
    notes = fields.Text()
    company_id = fields.Many2one(
        'res.company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    analytic_account_id = fields.Many2one(
        'account.analytic.account',
        string='Analytic Account',
        check_company=True,
    )
    state = fields.Selection(
        [
            ('draft', 'Draft'),
            ('posted', 'Posted'),
            ('cancelled', 'Cancelled'),
        ],
        default='draft',
        required=True,
        tracking=True,
        index=True,
        copy=False,
    )
    move_id = fields.Many2one(
        'account.move',
        string='Journal Entry',
        copy=False,
        readonly=True,
        check_company=True,
    )
    reversal_move_id = fields.Many2one(
        'account.move',
        string='Reversal Entry',
        copy=False,
        readonly=True,
        check_company=True,
    )
    posted_uid = fields.Many2one('res.users', string='Posted By', copy=False, readonly=True)
    posted_date = fields.Datetime(string='Posted On', copy=False, readonly=True)
    attachment_count = fields.Integer(compute='_compute_attachment_count')

    _sql_constraints = [
        (
            'pet_clinic_expense_move_uniq',
            'unique(move_id)',
            'An accounting move can be linked to only one clinic expense.',
        ),
        (
            'pet_clinic_expense_amount_positive',
            'CHECK(amount > 0)',
            'Expense amount must be greater than zero.',
        ),
    ]

    @api.depends()
    def _compute_attachment_count(self):
        Attachment = self.env['ir.attachment']
        for rec in self:
            rec.attachment_count = Attachment.search_count([
                ('res_model', '=', self._name),
                ('res_id', '=', rec.id),
            ]) if rec.id else 0

    @api.onchange('category_id')
    def _onchange_category_id(self):
        if self.category_id and self.category_id.analytic_account_id and not self.analytic_account_id:
            self.analytic_account_id = self.category_id.analytic_account_id

    @api.onchange('funding_source_id')
    def _onchange_funding_source_company(self):
        if self.funding_source_id:
            self.company_id = self.funding_source_id.company_id
            self.currency_id = self.funding_source_id.currency_id or self.company_id.currency_id

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('pet.clinic.expense') or _('New')
            if vals.get('category_id') and not vals.get('analytic_account_id'):
                cat = self.env['pet.expense.category'].browse(vals['category_id'])
                if cat.analytic_account_id:
                    vals['analytic_account_id'] = cat.analytic_account_id.id
        return super().create(vals_list)

    def write(self, vals):
        protected = {
            'amount', 'date', 'description', 'category_id', 'funding_source_id',
            'company_id', 'currency_id', 'analytic_account_id',
        }
        for rec in self:
            if rec.state == 'posted' and protected.intersection(vals):
                raise UserError(_(
                    'Posted expense %(name)s cannot be modified. Reverse it first.',
                    name=rec.display_name,
                ))
            if rec.state == 'cancelled' and protected.intersection(vals):
                raise UserError(_(
                    'Cancelled expense %(name)s cannot be modified.',
                    name=rec.display_name,
                ))
        return super().write(vals)

    def unlink(self):
        for rec in self:
            if rec.state != 'draft' or rec.move_id:
                raise UserError(_(
                    'Only draft expenses without journal entries can be deleted.'
                ))
        return super().unlink()

    def _lock_rows(self):
        """Narrow SELECT … FOR UPDATE to make action_post race-safe."""
        if not self.ids:
            return
        self.env.cr.execute(
            'SELECT id FROM pet_clinic_expense WHERE id IN %s FOR UPDATE',
            [tuple(self.ids)],
        )

    def _check_can_post(self):
        if not (
            self.env.user.has_group('pet_management.group_pet_clinic_accountant')
            or self.env.user.has_group('base.group_system')
        ):
            raise AccessError(_('Only Clinic Accountants (or managers) can post expenses.'))

    def _check_can_cancel(self):
        if not (
            self.env.user.has_group('pet_management.group_pet_clinic_accountant')
            or self.env.user.has_group('base.group_system')
        ):
            raise AccessError(_('Only Clinic Accountants can reverse/cancel expenses.'))

    def _validate_for_posting(self):
        self.ensure_one()
        if self.amount <= 0:
            raise ValidationError(_('Expense amount must be greater than zero.'))
        if not self.category_id or not self.category_id.account_id:
            raise ValidationError(_(
                'Expense category "%(cat)s" has no expense account configured.',
                cat=self.category_id.display_name if self.category_id else _('(none)'),
            ))
        source = self.funding_source_id
        if not source or not source.active:
            raise ValidationError(_('Select an active funding source.'))
        if source.company_id != self.company_id or self.category_id.company_id != self.company_id:
            raise ValidationError(_('Category, funding source, and expense must share the same company.'))
        if source.source_type in ('cash', 'bank'):
            if not source.journal_id or source.journal_id.type not in ('cash', 'bank'):
                raise ValidationError(_(
                    'Funding source "%(src)s" needs a Cash/Bank journal.',
                    src=source.display_name,
                ))
            if not source.liquidity_account_id:
                raise ValidationError(_(
                    'Journal "%(journal)s" has no liquidity account.',
                    journal=source.journal_id.display_name,
                ))
        elif source.source_type == 'partner':
            if not source.partner_id:
                raise ValidationError(_('Partner funding source is missing a partner.'))
            payable = source.payable_account_id or source.partner_id.with_company(
                self.company_id
            ).property_account_payable_id
            if not payable:
                raise ValidationError(_(
                    'Partner "%(partner)s" has no payable account for this company.',
                    partner=source.partner_id.display_name,
                ))

    def _prepare_move_vals(self):
        self.ensure_one()
        source = self.funding_source_id
        expense_account = self.category_id.account_id
        analytic_dist = {}
        if self.analytic_account_id:
            analytic_dist = {str(self.analytic_account_id.id): 100.0}

        debit_line = {
            'name': self.description or self.name,
            'account_id': expense_account.id,
            'debit': self.amount,
            'credit': 0.0,
            'partner_id': False,
            'analytic_distribution': analytic_dist or False,
        }
        if source.source_type in ('cash', 'bank'):
            journal = source.journal_id
            credit_line = {
                'name': self.description or self.name,
                'account_id': source.liquidity_account_id.id,
                'debit': 0.0,
                'credit': self.amount,
                'partner_id': False,
            }
        else:
            journal = self.env['account.journal'].search([
                ('company_id', '=', self.company_id.id),
                ('type', '=', 'general'),
                ('code', '=', 'MISC'),
            ], limit=1) or self.env['account.journal'].search([
                ('company_id', '=', self.company_id.id),
                ('type', '=', 'general'),
            ], limit=1)
            if not journal:
                raise UserError(_('No miscellaneous journal found to post partner-funded expenses.'))
            payable = source.payable_account_id or source.partner_id.with_company(
                self.company_id
            ).property_account_payable_id
            credit_line = {
                'name': self.description or self.name,
                'account_id': payable.id,
                'debit': 0.0,
                'credit': self.amount,
                'partner_id': source.partner_id.id,
            }
        return {
            'move_type': 'entry',
            'journal_id': journal.id,
            'date': self.date,
            'ref': self.name,
            'company_id': self.company_id.id,
            'currency_id': self.currency_id.id,
            'line_ids': [(0, 0, debit_line), (0, 0, credit_line)],
        }

    def action_post(self):
        self._check_can_post()
        self._lock_rows()
        # Re-browse after lock
        for rec in self.browse(self.ids):
            if rec.state == 'posted' and rec.move_id:
                continue
            if rec.state == 'cancelled':
                raise UserError(_('Cancelled expenses cannot be posted.'))
            if rec.move_id:
                # Recover inconsistent draft-with-move
                if rec.move_id.state == 'posted':
                    rec.write({
                        'state': 'posted',
                        'posted_uid': self.env.user.id,
                        'posted_date': fields.Datetime.now(),
                    })
                    continue
            rec._validate_for_posting()
            move = self.env['account.move'].create(rec._prepare_move_vals())
            move.action_post()
            rec.write({
                'move_id': move.id,
                'state': 'posted',
                'posted_uid': self.env.user.id,
                'posted_date': fields.Datetime.now(),
            })
        return True

    def action_cancel(self):
        """Reverse posted move via Odoo 19 _reverse_moves; never delete the original."""
        self._check_can_cancel()
        self._lock_rows()
        for rec in self.browse(self.ids):
            if rec.state == 'cancelled' and rec.reversal_move_id:
                continue
            if rec.state != 'posted' or not rec.move_id:
                raise UserError(_('Only posted expenses with a journal entry can be reversed.'))
            if rec.reversal_move_id:
                raise UserError(_('Expense %(name)s was already reversed.', name=rec.display_name))
            move = rec.move_id
            if move.state != 'posted':
                raise UserError(_('Linked journal entry is not posted.'))
            reverse_moves = move._reverse_moves(
                default_values_list=[{
                    'date': fields.Date.context_today(rec),
                    'ref': _('Reversal of %s') % (rec.name,),
                }],
                cancel=True,
            )
            reverse = reverse_moves[:1]
            if reverse.state != 'posted':
                reverse.action_post()
            rec.write({
                'reversal_move_id': reverse.id,
                'state': 'cancelled',
            })
        return True

    def action_open_move(self):
        self.ensure_one()
        move = self.move_id
        if not move:
            raise UserError(_('No journal entry linked.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Journal Entry'),
            'res_model': 'account.move',
            'view_mode': 'form',
            'res_id': move.id,
            'target': 'current',
        }

    def action_open_attachments(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Attachments'),
            'res_model': 'ir.attachment',
            'view_mode': 'list,form',
            'domain': [('res_model', '=', self._name), ('res_id', '=', self.id)],
            'context': {'default_res_model': self._name, 'default_res_id': self.id},
        }
