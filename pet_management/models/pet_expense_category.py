# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class PetExpenseCategory(models.Model):
    _name = 'pet.expense.category'
    _description = 'Clinic Expense Category'
    _order = 'sequence, id'

    name = fields.Char(required=True, translate=True)
    technical_code = fields.Char(index=True)
    account_id = fields.Many2one(
        'account.account',
        string='Expense Account',
        domain="[('account_type', 'in', ['expense', 'expense_direct_cost', 'expense_depreciation']), "
               "('company_ids', 'in', company_id)]",
        check_company=True,
    )
    analytic_account_id = fields.Many2one(
        'account.analytic.account',
        string='Default Analytic Account',
        check_company=True,
    )
    company_id = fields.Many2one(
        'res.company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    sequence = fields.Integer(default=100)
    active = fields.Boolean(default=True)
    configuration_warning = fields.Char(compute='_compute_configuration_warning')

    _sql_constraints = [
        (
            'pet_expense_category_tech_company_uniq',
            'unique(technical_code, company_id)',
            'Expense category technical code must be unique per company.',
        ),
    ]

    @api.depends('account_id', 'active')
    def _compute_configuration_warning(self):
        for rec in self:
            if not rec.account_id:
                rec.configuration_warning = _(
                    'No expense account configured. Activate only after assigning a valid account.'
                )
            else:
                rec.configuration_warning = False

    @api.constrains('account_id', 'active')
    def _check_account_when_active(self):
        for rec in self:
            if rec.active and not rec.account_id:
                raise ValidationError(_(
                    'Active expense category "%(name)s" requires an expense account.',
                    name=rec.display_name,
                ))
            if rec.account_id and rec.account_id.account_type not in (
                'expense', 'expense_direct_cost', 'expense_depreciation',
            ):
                raise ValidationError(_(
                    'Category "%(name)s" must map to an expense-type account.',
                    name=rec.display_name,
                ))
