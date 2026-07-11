# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class PetClinicPartnerReimbursementWizard(models.TransientModel):
    _name = 'pet.clinic.partner.reimbursement.wizard'
    _description = 'Quick Partner Reimbursement'

    date = fields.Date(required=True, default=fields.Date.context_today)
    amount = fields.Monetary(required=True, currency_field='currency_id')
    currency_id = fields.Many2one(
        'res.currency', required=True,
        default=lambda self: self.env.company.currency_id,
    )
    partner_source_id = fields.Many2one(
        'pet.funding.source', required=True,
        domain="[('source_type', '=', 'partner'), ('company_id', '=', company_id), ('active', '=', True)]",
    )
    pay_from_source_id = fields.Many2one(
        'pet.funding.source', required=True,
        domain="[('source_type', 'in', ['cash', 'bank']), ('company_id', '=', company_id), ('active', '=', True)]",
    )
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company,
    )
    notes = fields.Text()
    outstanding_due = fields.Monetary(
        compute='_compute_outstanding_due', currency_field='currency_id',
    )

    @api.depends('partner_source_id', 'company_id', 'date')
    def _compute_outstanding_due(self):
        for wiz in self:
            wiz.outstanding_due = (
                wiz.partner_source_id.get_partner_due_balance(
                    company=wiz.company_id, date_to=wiz.date,
                ) if wiz.partner_source_id else 0.0
            )

    def action_create_and_post(self):
        self.ensure_one()
        rec = self.env['pet.clinic.partner.reimbursement'].create({
            'date': self.date,
            'amount': self.amount,
            'currency_id': self.currency_id.id,
            'partner_source_id': self.partner_source_id.id,
            'pay_from_source_id': self.pay_from_source_id.id,
            'company_id': self.company_id.id,
            'notes': self.notes,
        })
        rec.action_post()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Partner Reimbursement'),
            'res_model': 'pet.clinic.partner.reimbursement',
            'res_id': rec.id,
            'view_mode': 'form',
            'target': 'current',
        }
