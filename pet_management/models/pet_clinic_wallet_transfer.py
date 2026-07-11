# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError


class PetClinicWalletTransfer(models.Model):
    _name = 'pet.clinic.wallet.transfer'
    _description = 'Clinic Wallet Transfer'
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
    from_source_id = fields.Many2one(
        'pet.funding.source', string='From', required=True,
        domain="[('source_type', 'in', ['cash', 'bank']), ('company_id', '=', company_id)]",
        check_company=True, tracking=True,
    )
    to_source_id = fields.Many2one(
        'pet.funding.source', string='To', required=True,
        domain="[('source_type', 'in', ['cash', 'bank']), ('company_id', '=', company_id)]",
        check_company=True, tracking=True,
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

    _sql_constraints = [
        ('pet_wallet_transfer_move_uniq', 'unique(move_id)',
         'An accounting move can be linked to only one wallet transfer.'),
        ('pet_wallet_transfer_amount_positive', 'CHECK(amount > 0)',
         'Transfer amount must be greater than zero.'),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'pet.clinic.wallet.transfer'
                ) or _('New')
        return super().create(vals_list)

    def _lock_rows(self):
        if not self.ids:
            return
        self.env.cr.execute(
            'SELECT id FROM pet_clinic_wallet_transfer WHERE id IN %s FOR UPDATE',
            [tuple(self.ids)],
        )

    def _check_manager_access(self):
        if not (
            self.env.user.has_group('pet_management.group_pet_clinic_accountant')
            or self.env.user.has_group('base.group_system')
        ):
            raise AccessError(_('Only Clinic Accountants / Billing Managers can manage wallet transfers.'))

    @api.constrains('from_source_id', 'to_source_id', 'company_id')
    def _check_sources(self):
        for rec in self:
            if rec.from_source_id == rec.to_source_id:
                raise ValidationError(_('Source and destination wallets must differ.'))
            for src in (rec.from_source_id, rec.to_source_id):
                if src.source_type not in ('cash', 'bank'):
                    raise ValidationError(_('Wallet transfers are only allowed between cash/bank sources.'))
                if src.company_id != rec.company_id:
                    raise ValidationError(_('Transfer sources must belong to the same company.'))
                if not src.liquidity_account_id:
                    raise ValidationError(_(
                        'Funding source "%(src)s" has no liquidity account.',
                        src=src.display_name,
                    ))

    def action_post(self):
        self._check_manager_access()
        self._lock_rows()
        for rec in self.browse(self.ids):
            if rec.state == 'posted' and rec.move_id:
                continue
            if rec.state == 'cancelled':
                raise UserError(_('Cancelled transfers cannot be posted.'))
            rec._check_sources()
            # Single balanced entry: Dr destination liquidity, Cr source liquidity.
            # Posted on the source journal for traceability (Odoo 19 entry move).
            journal = rec.from_source_id.journal_id
            move = self.env['account.move'].create({
                'move_type': 'entry',
                'journal_id': journal.id,
                'date': rec.date,
                'ref': _('Wallet transfer %s') % rec.name,
                'company_id': rec.company_id.id,
                'line_ids': [
                    (0, 0, {
                        'name': _('Transfer to %s') % rec.to_source_id.display_name,
                        'account_id': rec.to_source_id.liquidity_account_id.id,
                        'debit': rec.amount,
                        'credit': 0.0,
                    }),
                    (0, 0, {
                        'name': _('Transfer from %s') % rec.from_source_id.display_name,
                        'account_id': rec.from_source_id.liquidity_account_id.id,
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
                raise UserError(_('Only posted transfers can be reversed.'))
            if rec.reversal_move_id:
                raise UserError(_('Transfer already reversed.'))
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
