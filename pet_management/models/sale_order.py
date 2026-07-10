# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    appointment_id = fields.Many2one(
        'pet.appointment',
        string='Appointment',
        index=True,
        copy=False,
        ondelete='set null',
        help='Clinic appointment that generated this sale order.',
    )

    def _prepare_invoice(self):
        vals = super()._prepare_invoice()
        if self.appointment_id:
            vals['appointment_id'] = self.appointment_id.id
        return vals

    def _appointment_active_invoices(self):
        """Non-cancelled customer invoices linked to this appointment-aware SO."""
        self.ensure_one()
        Move = self.env['account.move']
        invoices = self.invoice_ids.filtered(
            lambda m: m.move_type in ('out_invoice', 'out_refund') and m.state != 'cancel'
        )
        if self.appointment_id:
            invoices |= Move.search([
                ('appointment_id', '=', self.appointment_id.id),
                ('move_type', 'in', ('out_invoice', 'out_refund')),
                ('state', '!=', 'cancel'),
            ])
        return invoices

    def _create_invoices(self, grouped=False, final=False, date=None):
        """Block silent second primary invoices for appointment-linked orders.

        Controlled additional invoices must pass
        ``allow_additional_appointment_invoice=True`` in the context.
        Credit notes / final=True refunds remain allowed.
        """
        allow_additional = self.env.context.get('allow_additional_appointment_invoice')
        for order in self.filtered('appointment_id'):
            if final:
                continue
            active = order._appointment_active_invoices().filtered(
                lambda m: m.move_type == 'out_invoice'
            )
            primary = active.filtered(lambda m: not m.is_additional_invoice)
            if primary and not allow_additional:
                raise UserError(_(
                    'Appointment %(appt)s already has invoice %(inv)s. '
                    'Open the existing invoice, or use "Create Additional Invoice" '
                    'with a reason for uninvoiced services only.',
                    appt=order.appointment_id.name,
                    inv=primary[:1].display_name,
                ))
            if active and allow_additional:
                # Only invoice remaining quantities; standard _get_invoiceable_lines handles this.
                pass
        invoices = super()._create_invoices(grouped=grouped, final=final, date=date)
        if invoices and any(self.mapped('appointment_id')):
            for inv in invoices:
                order = inv.invoice_line_ids.mapped('sale_line_ids.order_id')[:1]
                appt = order.appointment_id if order else self[:1].appointment_id
                if appt and not inv.appointment_id:
                    inv.appointment_id = appt.id
                if allow_additional and inv.move_type == 'out_invoice':
                    inv.is_additional_invoice = True
                    reason = self.env.context.get('additional_invoice_reason')
                    if reason:
                        inv.additional_invoice_reason = reason
        return invoices
