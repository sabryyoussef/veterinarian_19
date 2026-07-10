# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError


class AppointmentAdditionalInvoiceWizard(models.TransientModel):
    _name = 'pet.appointment.additional.invoice.wizard'
    _description = 'Create Additional Appointment Invoice'

    appointment_id = fields.Many2one('pet.appointment', required=True, ondelete='cascade')
    reason = fields.Text(required=True, help='Why an additional invoice is needed.')
    sale_order_id = fields.Many2one(related='appointment_id.sale_order_id', readonly=True)
    uninvoiced_amount = fields.Monetary(
        compute='_compute_uninvoiced_amount',
        currency_field='currency_id',
    )
    currency_id = fields.Many2one(related='appointment_id.currency_id')

    @api.depends('sale_order_id', 'sale_order_id.order_line.qty_to_invoice')
    def _compute_uninvoiced_amount(self):
        for wiz in self:
            order = wiz.sale_order_id
            if not order:
                wiz.uninvoiced_amount = 0.0
                continue
            total = 0.0
            for line in order.order_line.filtered(lambda l: not l.display_type):
                total += (line.qty_to_invoice or 0.0) * (line.price_unit or 0.0) * (
                    1.0 - (line.discount or 0.0) / 100.0
                )
            wiz.uninvoiced_amount = total

    def action_create_additional_invoice(self):
        self.ensure_one()
        if not self.env.user.has_group('pet_management.group_pet_clinic_accountant') \
                and not self.env.user.has_group('pet_management.group_pet_clinic_billing_manager') \
                and not self.env.user.has_group('base.group_system'):
            raise AccessError(_('Only clinic accountants may create additional appointment invoices.'))
        if not (self.reason or '').strip():
            raise UserError(_('A reason is required for an additional invoice.'))
        appt = self.appointment_id
        order = appt.sale_order_id
        if not order:
            raise UserError(_('No sale order found on this appointment.'))
        if not any(line.qty_to_invoice for line in order.order_line if not line.display_type):
            raise UserError(_('There are no uninvoiced quantities left on the sale order.'))

        invoices = order.with_context(
            allow_additional_appointment_invoice=True,
            additional_invoice_reason=self.reason.strip(),
        )._create_invoices()
        if not invoices:
            raise UserError(_('No additional invoice could be created.'))
        invoices.action_post()
        for inv in invoices:
            inv.write({
                'is_additional_invoice': True,
                'additional_invoice_reason': self.reason.strip(),
                'appointment_id': appt.id,
                'billing_revision': (appt.billing_revision or 0) + 1,
            })
        appt.billing_revision = (appt.billing_revision or 0) + 1
        appt.message_post(body=_(
            'Additional invoice %(inv)s created. Reason: %(reason)s',
            inv=', '.join(invoices.mapped('name')),
            reason=self.reason.strip(),
        ))
        appt._recompute_primary_invoice()
        return appt.action_view_invoices()
