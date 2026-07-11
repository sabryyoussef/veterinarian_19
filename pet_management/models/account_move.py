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
        ondelete='restrict',
        help='Clinic appointment linked to this invoice/credit note. '
             'Restrict delete: appointments with invoices cannot be removed.',
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

    def _pet_clinic_customer_doc(self):
        return self.filtered(lambda m: m.move_type in ('out_invoice', 'out_refund'))

    def _pet_link_appointment_from_origin(self):
        """Auto-link customer invoices/credit notes to appointments from SO or APT origin."""
        Appointment = self.env['pet.appointment']
        SaleOrder = self.env['sale.order']
        for move in self._pet_clinic_customer_doc().filtered(lambda m: not m.appointment_id):
            origin = (move.invoice_origin or '').strip()
            if not origin:
                continue
            so = SaleOrder.search([('name', '=', origin)], limit=1)
            if so and so.appointment_id:
                move.appointment_id = so.appointment_id.id
                continue
            appt = Appointment.search([('name', '=', origin)], limit=1)
            if appt:
                move.appointment_id = appt.id

    def _pet_sync_linked_appointments(self):
        """Keep appointment primary pointer and billing totals aligned after invoice changes."""
        appts = self.mapped('appointment_id')
        if not appts:
            return
        appts._recompute_primary_invoice()
        appts.invalidate_recordset([
            'total_invoiced', 'total_paid', 'total_residual', 'draft_invoice_total',
            'billing_variance', 'amount_total', 'payment_status', 'billing_warning',
            'has_billing_mismatch', 'service_total', 'sale_order_total',
        ])

    @api.model_create_multi
    def create(self, vals_list):
        moves = super().create(vals_list)
        moves._pet_link_appointment_from_origin()
        return moves

    def write(self, vals):
        if 'appointment_id' in vals and not vals.get('appointment_id'):
            for move in self._pet_clinic_customer_doc():
                if move.state == 'posted' and move.appointment_id:
                    raise UserError(_(
                        'Cannot clear the appointment link on posted invoice %(inv)s. '
                        'Cancel or credit-note the invoice first, or keep the appointment.',
                        inv=move.display_name,
                    ))
        res = super().write(vals)
        if any(k in vals for k in (
            'appointment_id', 'state', 'payment_state', 'amount_total', 'amount_residual',
        )):
            self._pet_sync_linked_appointments()
            # Also sync appointments newly linked
            if vals.get('appointment_id'):
                self.env['pet.appointment'].browse(vals['appointment_id'])._recompute_primary_invoice()
        return res

    def action_post(self):
        self._pet_link_appointment_from_origin()
        # Clinic invoices that still have no appointment after auto-link: block if origin is APT*
        for move in self._pet_clinic_customer_doc():
            origin = (move.invoice_origin or '').strip()
            if move.appointment_id or not origin:
                continue
            if origin.upper().startswith('APT'):
                raise UserError(_(
                    'Invoice %(inv)s origin %(origin)s looks like an appointment, '
                    'but no matching appointment was found. '
                    'Create/restore the appointment and set Appointment on the invoice '
                    'before posting — otherwise Accounting and Appointments will diverge.',
                    inv=move.display_name or _('New'),
                    origin=origin,
                ))
        res = super().action_post()
        posted = self._pet_clinic_customer_doc().filtered(lambda m: m.state == 'posted' and m.appointment_id)
        for appt in posted.filtered(lambda m: m.move_type == 'out_invoice').mapped('appointment_id'):
            appt._recompute_primary_invoice()
            # Keep service lines aligned with posted invoice content (metadata only)
            try:
                appt._sync_services_from_invoice()
            except Exception:  # noqa: BLE001 — never block posting on sync edge cases
                appt.message_post(body=_(
                    'Invoice posted but automatic service sync failed; run Repair Billing Metadata.'
                ))
        posted._pet_sync_linked_appointments()
        return res

    def button_cancel(self):
        appts = self._pet_clinic_customer_doc().mapped('appointment_id')
        res = super().button_cancel()
        if appts:
            appts._recompute_primary_invoice()
            appts.invalidate_recordset()
        return res

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
