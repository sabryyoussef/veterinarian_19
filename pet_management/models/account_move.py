# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError


class AccountMove(models.Model):
    _inherit = 'account.move'

    appointment_id = fields.Many2one(
        'pet.appointment',
        string='Appointment',
        index=True,
        copy=False,
        ondelete='set null',
        help='Clinic appointment linked to this invoice/credit note.',
    )
    is_additional_invoice = fields.Boolean(
        string='Additional Appointment Invoice',
        copy=False,
        default=False,
        help='Created via the controlled additional-invoice workflow after a primary invoice.',
    )
    additional_invoice_reason = fields.Text(
        string='Additional Invoice Reason',
        copy=False,
    )
    billing_revision = fields.Integer(
        string='Billing Revision',
        copy=False,
        default=0,
        help='Incremented for controlled billing corrections.',
    )

    def button_draft(self):
        """Block draft reset on paid/reconciled appointment customer invoices."""
        for move in self:
            if move.move_type not in ('out_invoice', 'out_refund') or not move.appointment_id:
                continue
            if move.state != 'posted':
                continue
            has_reconcile = any(
                line.matched_debit_ids or line.matched_credit_ids
                for line in move.line_ids.filtered(
                    lambda l: l.account_id.account_type == 'asset_receivable'
                )
            )
            paid_like = move.payment_state in ('paid', 'in_payment', 'partial', 'reversed')
            if has_reconcile or paid_like:
                if not self.env.user.has_group('pet_management.group_pet_clinic_accountant'):
                    raise UserError(_(
                        'Invoice %(inv)s for appointment %(appt)s has payments or '
                        'reconciliations and cannot be reset to draft. '
                        'Use a credit note, refund, or ask an accountant.',
                        inv=move.display_name,
                        appt=move.appointment_id.display_name,
                    ))
                # Even accountants: prefer credit-note path for paid docs.
                raise UserError(_(
                    'Invoice %(inv)s is paid or reconciled. '
                    'Do not reset it to draft (this orphans payments). '
                    'Create a credit note or refund instead.',
                    inv=move.display_name,
                ))
            if not self.env.user.has_group('pet_management.group_pet_clinic_accountant') \
                    and not self.env.user.has_group('base.group_system'):
                raise AccessError(_(
                    'Only clinic accountants may reset appointment invoices to draft.'
                ))
        return super().button_draft()


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    appointment_service_line_id = fields.Many2one(
        'pet.appointment.service.line',
        string='Appointment Service Line',
        copy=False,
        index=True,
        ondelete='set null',
        help='Stable source link to the appointment extra service line.',
    )
