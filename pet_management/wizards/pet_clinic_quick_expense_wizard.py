# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError


class PetClinicQuickExpenseWizard(models.TransientModel):
    _name = 'pet.clinic.quick.expense.wizard'
    _description = 'Quick Clinic Expense'

    date = fields.Date(required=True, default=fields.Date.context_today)
    amount = fields.Monetary(required=True, currency_field='currency_id')
    currency_id = fields.Many2one(
        'res.currency', required=True,
        default=lambda self: self.env.company.currency_id,
    )
    description = fields.Char(required=True)
    category_id = fields.Many2one(
        'pet.expense.category', required=True,
        domain="[('active', '=', True), ('company_id', '=', company_id)]",
        check_company=True,
    )
    funding_source_id = fields.Many2one(
        'pet.funding.source', string='Paid From', required=True,
        domain="[('active', '=', True), ('company_id', '=', company_id)]",
        check_company=True,
    )
    notes = fields.Text()
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company,
    )
    analytic_account_id = fields.Many2one(
        'account.analytic.account', check_company=True,
    )
    attachment_ids = fields.Many2many('ir.attachment', string='Receipt')

    @api.onchange('category_id')
    def _onchange_category(self):
        if self.category_id.analytic_account_id and not self.analytic_account_id:
            self.analytic_account_id = self.category_id.analytic_account_id

    def _create_expense(self):
        self.ensure_one()
        expense = self.env['pet.clinic.expense'].create({
            'date': self.date,
            'amount': self.amount,
            'currency_id': self.currency_id.id,
            'description': self.description,
            'category_id': self.category_id.id,
            'funding_source_id': self.funding_source_id.id,
            'notes': self.notes,
            'company_id': self.company_id.id,
            'analytic_account_id': self.analytic_account_id.id,
        })
        if self.attachment_ids:
            self.attachment_ids.write({
                'res_model': 'pet.clinic.expense',
                'res_id': expense.id,
            })
        return expense

    def action_save_draft(self):
        expense = self._create_expense()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Clinic Expense'),
            'res_model': 'pet.clinic.expense',
            'view_mode': 'form',
            'res_id': expense.id,
            'target': 'current',
        }

    def action_save_and_post(self):
        if not (
            self.env.user.has_group('pet_management.group_pet_clinic_accountant')
            or self.env.user.has_group('base.group_system')
        ):
            raise AccessError(_('Only Clinic Accountants can Save & Post.'))
        expense = self._create_expense()
        expense.action_post()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Clinic Expense'),
            'res_model': 'pet.clinic.expense',
            'view_mode': 'form',
            'res_id': expense.id,
            'target': 'current',
        }
