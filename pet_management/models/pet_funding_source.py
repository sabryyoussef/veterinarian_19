# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class PetFundingSource(models.Model):
    _name = 'pet.funding.source'
    _description = 'Clinic Funding Source'
    _order = 'sequence, id'

    name = fields.Char(required=True, translate=True)
    name_ar = fields.Char(string='Arabic Name')
    technical_code = fields.Char(
        string='Technical Code',
        index=True,
        help='Stable code for setup/dashboard (clinic_cash, clinic_instapay, sabry, ahmed, …).',
    )
    source_type = fields.Selection(
        [
            ('cash', 'Cash'),
            ('bank', 'Bank / Wallet'),
            ('partner', 'Partner'),
        ],
        required=True,
        default='cash',
    )
    journal_id = fields.Many2one(
        'account.journal',
        string='Journal',
        domain="[('company_id', '=', company_id), ('type', 'in', ['cash', 'bank'])]",
        check_company=True,
    )
    liquidity_account_id = fields.Many2one(
        'account.account',
        string='Liquidity Account',
        related='journal_id.default_account_id',
        store=True,
        readonly=True,
    )
    partner_id = fields.Many2one('res.partner', string='Partner', check_company=True)
    payable_account_id = fields.Many2one(
        'account.account',
        string='Payable Account',
        domain="[('account_type', '=', 'liability_payable'), ('company_ids', 'in', company_id)]",
        check_company=True,
    )
    company_id = fields.Many2one(
        'res.company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        required=True,
        default=lambda self: self.env.company.currency_id,
    )
    sequence = fields.Integer(default=100)
    active = fields.Boolean(default=True)

    _sql_constraints = [
        (
            'pet_funding_source_tech_company_uniq',
            'unique(technical_code, company_id)',
            'Funding source technical code must be unique per company.',
        ),
    ]

    @api.constrains('source_type', 'journal_id', 'partner_id', 'payable_account_id', 'company_id')
    def _check_source_configuration(self):
        for rec in self:
            if rec.source_type in ('cash', 'bank'):
                if not rec.journal_id:
                    raise ValidationError(_(
                        'Funding source "%(name)s" requires a cash/bank journal.',
                        name=rec.display_name,
                    ))
                if rec.journal_id.company_id != rec.company_id:
                    raise ValidationError(_('Journal company must match the funding source company.'))
                if rec.journal_id.type not in ('cash', 'bank'):
                    raise ValidationError(_(
                        'Funding source "%(name)s" journal must be type Cash or Bank.',
                        name=rec.display_name,
                    ))
                if not rec.journal_id.default_account_id:
                    raise ValidationError(_(
                        'Journal "%(journal)s" has no default liquidity account.',
                        journal=rec.journal_id.display_name,
                    ))
            elif rec.source_type == 'partner':
                if not rec.partner_id:
                    raise ValidationError(_(
                        'Partner funding source "%(name)s" requires a partner.',
                        name=rec.display_name,
                    ))
                if not rec.payable_account_id:
                    raise ValidationError(_(
                        'Partner funding source "%(name)s" requires a payable account.',
                        name=rec.display_name,
                    ))

    def display_name_dashboard(self):
        self.ensure_one()
        if self.source_type == 'partner':
            # Prefer Arabic due-to phrasing when name_ar set
            if self.technical_code == 'sabry':
                return _('Due to Sabry')
            if self.technical_code == 'ahmed':
                return _('Due to Ahmed')
            return _('Due to %s') % (self.name_ar or self.name)
        return self.name_ar or self.name

    def get_partner_due_balance(self, company=None, date_to=None):
        """credit − debit on payable lines for the partner (positive = clinic owes)."""
        self.ensure_one()
        if self.source_type != 'partner' or not self.partner_id:
            return 0.0
        company = company or self.company_id
        payable = self.payable_account_id or self.partner_id.with_company(
            company
        ).property_account_payable_id
        if not payable:
            return 0.0
        domain = [
            ('company_id', '=', company.id),
            ('parent_state', '=', 'posted'),
            ('account_id', '=', payable.id),
            ('partner_id', '=', self.partner_id.id),
        ]
        if date_to:
            domain.append(('date', '<=', date_to))
        groups = self.env['account.move.line'].read_group(
            domain, ['credit:sum', 'debit:sum'], [],
        )
        if not groups:
            return 0.0
        credit = groups[0].get('credit', 0.0) or 0.0
        debit = groups[0].get('debit', 0.0) or 0.0
        return credit - debit

    def get_liquidity_balance(self, company=None, date_to=None):
        self.ensure_one()
        if self.source_type not in ('cash', 'bank'):
            return 0.0
        account = self.liquidity_account_id
        if not account:
            return 0.0
        company = company or self.company_id
        domain = [
            ('company_id', '=', company.id),
            ('parent_state', '=', 'posted'),
            ('account_id', '=', account.id),
        ]
        if date_to:
            domain.append(('date', '<=', date_to))
        groups = self.env['account.move.line'].read_group(
            domain, ['balance:sum'], [],
        )
        if not groups:
            return 0.0
        # asset_cash balance: debit − credit → positive means funds available
        return groups[0].get('balance', 0.0) or 0.0
