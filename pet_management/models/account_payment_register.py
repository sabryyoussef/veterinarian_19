# -*- coding: utf-8 -*-
from odoo import api, models, _
from odoo.exceptions import UserError
from odoo.tools import float_compare


class AccountPaymentRegister(models.TransientModel):
    _inherit = 'account.payment.register'

    def _get_appointment_linked_moves(self):
        moves = self.line_ids.move_id
        return moves.filtered(lambda m: m.appointment_id and m.move_type == 'out_invoice')

    @api.onchange('amount')
    def _onchange_appointment_payment_amount(self):
        appt_moves = self._get_appointment_linked_moves()
        if not appt_moves or not self.amount:
            return
        residual = sum(appt_moves.mapped('amount_residual'))
        currency = self.currency_id or appt_moves[:1].currency_id
        if float_compare(self.amount, residual, precision_rounding=currency.rounding) > 0:
            return {
                'warning': {
                    'title': _('Payment exceeds residual'),
                    'message': _(
                        'Amount %(amount)s exceeds the appointment invoice residual %(residual)s. '
                        'Reduce the amount or use a controlled customer-credit workflow.',
                        amount=self.amount,
                        residual=residual,
                    ),
                }
            }

    def action_create_payments(self):
        appt_moves = self._get_appointment_linked_moves()
        if appt_moves:
            residual = sum(appt_moves.mapped('amount_residual'))
            currency = self.currency_id or appt_moves[:1].currency_id
            for wizard in self:
                if float_compare(wizard.amount, residual, precision_rounding=currency.rounding) > 0:
                    raise UserError(_(
                        'Cannot register payment of %(amount)s for appointment invoice(s): '
                        'residual is only %(residual)s. '
                        'Use a partial payment or an accountant customer-credit workflow.',
                        amount=wizard.amount,
                        residual=residual,
                    ))
        return super().action_create_payments()
