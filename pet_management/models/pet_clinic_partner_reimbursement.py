# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError


class PetClinicPartnerReimbursement(models.Model):
    _name = 'pet.clinic.partner.reimbursement'
    _description = 'Clinic Partner Reimbursement'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(
        required=True, copy=False, readonly=True,
        default=lambda self: _('New'),
    )
    date = fields.Date(required=True, default=fields.Date.context_today, tracking=True)
    amount = fields.Monetary(required=True, currency_field='currency_id', tracking=True)
    currency_id = fields.Many2one(
        'res.currency', required=True,
        default=lambda self: self.env.company.currency_id,
    )
    partner_source_id = fields.Many2one(
        'pet.funding.source',
        string='Due To',
        required=True,
        domain="[('source_type', '=', 'partner'), ('company_id', '=', company_id)]",
        check_company=True,
        tracking=True,
    )
    pay_from_source_id = fields.Many2one(
        'pet.funding.source',
        string='Pay From',
        required=True,
        domain="[('source_type', 'in', ['cash', 'bank']), ('company_id', '=', company_id)]",
        check_company=True,
        tracking=True,
    )
    partner_id = fields.Many2one(
        related='partner_source_id.partner_id', store=True, readonly=True,
    )
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company, index=True,
    )
    notes = fields.Text()
    state = fields.Selection(
        [('draft', 'Draft'), ('posted', 'Posted'), ('cancelled', 'Cancelled')],
        default='draft', required=True, tracking=True, copy=False,
    )
    move_id = fields.Many2one('account.move', copy=False, readonly=True, check_company=True)
    reversal_move_id = fields.Many2one('account.move', copy=False, readonly=True, check_company=True)
    posted_uid = fields.Many2one('res.users', copy=False, readonly=True)
    posted_date = fields.Datetime(copy=False, readonly=True)
    outstanding_due = fields.Monetary(
        string='Outstanding Due',
        compute='_compute_outstanding_due',
        currency_field='currency_id',
    )

    _sql_constraints = [
        ('pet_partner_reimburse_move_uniq', 'unique(move_id)',
         'An accounting move can be linked to only one partner reimbursement.'),
        ('pet_partner_reimburse_amount_positive', 'CHECK(amount > 0)',
         'Reimbursement amount must be greater than zero.'),
    ]

    @api.depends('partner_source_id', 'company_id', 'date')
    def _compute_outstanding_due(self):
        for rec in self:
            if rec.partner_source_id:
                rec.outstanding_due = rec.partner_source_id.get_partner_due_balance(
                    company=rec.company_id, date_to=rec.date,
                )
            else:
                rec.outstanding_due = 0.0

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'pet.clinic.partner.reimbursement'
                ) or _('New')
        return super().create(vals_list)

    def _lock_rows(self):
        if not self.ids:
            return
        self.env.cr.execute(
            'SELECT id FROM pet_clinic_partner_reimbursement WHERE id IN %s FOR UPDATE',
            [tuple(self.ids)],
        )

    def _check_manager_access(self):
        if not (
            self.env.user.has_group('pet_management.group_pet_clinic_accountant')
            or self.env.user.has_group('base.group_system')
        ):
            raise AccessError(_(
                'Only Clinic Accountants / Billing Managers can manage partner reimbursements.'
            ))

    def action_post(self):
        self._check_manager_access()
        self._lock_rows()
        for rec in self.browse(self.ids):
            if rec.state == 'posted' and rec.move_id:
                continue
            if rec.state == 'cancelled':
                raise UserError(_('Cancelled reimbursements cannot be posted.'))
            partner_src = rec.partner_source_id
            pay_src = rec.pay_from_source_id
            if partner_src.source_type != 'partner' or not partner_src.partner_id:
                raise ValidationError(_('Select a partner funding source.'))
            if pay_src.source_type not in ('cash', 'bank') or not pay_src.liquidity_account_id:
                raise ValidationError(_('Pay-from source must be a configured cash/bank wallet.'))
            if partner_src.company_id != rec.company_id or pay_src.company_id != rec.company_id:
                raise ValidationError(_('All reimbursement documents must share the same company.'))

            due = partner_src.get_partner_due_balance(company=rec.company_id, date_to=rec.date)
            if rec.amount > due + 1e-6:
                raise ValidationError(_(
                    'Cannot reimburse %(amount)s: outstanding due to %(partner)s is only %(due)s. '
                    'Use standard accounting outside this workflow for overpayments.',
                    amount=rec.amount,
                    partner=partner_src.partner_id.display_name,
                    due=due,
                ))

            payable = partner_src.payable_account_id or partner_src.partner_id.with_company(
                rec.company_id
            ).property_account_payable_id
            if not payable:
                raise ValidationError(_('Partner has no payable account.'))

            # Dr payable (partner), Cr clinic liquidity — no P&L impact
            move = self.env['account.move'].create({
                'move_type': 'entry',
                'journal_id': pay_src.journal_id.id,
                'date': rec.date,
                'ref': _('Partner reimbursement %s') % rec.name,
                'company_id': rec.company_id.id,
                'partner_id': partner_src.partner_id.id,
                'line_ids': [
                    (0, 0, {
                        'name': _('Reimburse %s') % partner_src.partner_id.display_name,
                        'account_id': payable.id,
                        'partner_id': partner_src.partner_id.id,
                        'debit': rec.amount,
                        'credit': 0.0,
                    }),
                    (0, 0, {
                        'name': _('Reimburse %s') % partner_src.partner_id.display_name,
                        'account_id': pay_src.liquidity_account_id.id,
                        'partner_id': False,
                        'debit': 0.0,
                        'credit': rec.amount,
                    }),
                ],
            })
            move.action_post()
            rec.write({
                'move_id': move.id,
                'state': 'posted',
                'posted_uid': self.env.user.id,
                'posted_date': fields.Datetime.now(),
            })
        return True

    def action_cancel(self):
        self._check_manager_access()
        self._lock_rows()
        for rec in self.browse(self.ids):
            if rec.state == 'cancelled' and rec.reversal_move_id:
                continue
            if rec.state != 'posted' or not rec.move_id:
                raise UserError(_('Only posted reimbursements can be reversed.'))
            if rec.reversal_move_id:
                raise UserError(_('Reimbursement already reversed.'))
            reverse = rec.move_id._reverse_moves(
                default_values_list=[{
                    'date': fields.Date.context_today(rec),
                    'ref': _('Reversal of %s') % rec.name,
                }],
                cancel=True,
            )[:1]
            if reverse.state != 'posted':
                reverse.action_post()
            rec.write({'reversal_move_id': reverse.id, 'state': 'cancelled'})
        return True
