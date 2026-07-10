# -*- coding: utf-8 -*-
from odoo import fields, models, _
from odoo.exceptions import AccessError, UserError


class AppointmentBillingRepairWizard(models.TransientModel):
    _name = 'pet.appointment.billing.repair.wizard'
    _description = 'Metadata-Only Appointment Billing Repair'

    appointment_id = fields.Many2one('pet.appointment', required=True, ondelete='cascade')
    repair_mode = fields.Selection([
        ('sync_services', 'Sync appointment services from posted invoices'),
        ('align_sale_order', 'Align sale order metadata with posted invoices'),
        ('both', 'Sync services and align sale order'),
    ], required=True, default='both')
    note = fields.Text(
        string='Repair Note',
        help='Optional note posted on the appointment chatter.',
    )
    preview_service_total = fields.Monetary(
        related='appointment_id.service_total', readonly=True, currency_field='currency_id')
    preview_sale_order_total = fields.Monetary(
        related='appointment_id.sale_order_total', readonly=True, currency_field='currency_id')
    preview_posted_invoice_total = fields.Monetary(
        related='appointment_id.total_invoiced', readonly=True, currency_field='currency_id')
    currency_id = fields.Many2one(related='appointment_id.currency_id')

    def action_apply_metadata_repair(self):
        self.ensure_one()
        if not self.env.user.has_group('pet_management.group_pet_clinic_accountant') \
                and not self.env.user.has_group('pet_management.group_pet_clinic_billing_manager') \
                and not self.env.user.has_group('base.group_system'):
            raise AccessError(_('Only clinic accountants may run billing metadata repair.'))
        appt = self.appointment_id
        posted = appt._get_linked_invoices().filtered(
            lambda m: m.move_type == 'out_invoice' and m.state == 'posted'
        )
        if not posted:
            raise UserError(_('No posted invoice found. This wizard never creates invoices.'))

        before_amounts = posted.mapped('amount_total')
        if self.repair_mode in ('sync_services', 'both'):
            appt._sync_services_from_invoice()
        if self.repair_mode in ('align_sale_order', 'both'):
            appt._align_sale_order_metadata_from_invoices()

        posted.invalidate_recordset()
        after_amounts = posted.mapped('amount_total')
        if before_amounts != after_amounts:
            raise UserError(_(
                'Abort: posted invoice totals changed during metadata repair. '
                'No accounting overwrite is allowed.'
            ))

        body = _(
            'Metadata-only billing repair applied (mode=%(mode)s). '
            'Posted invoices unchanged: %(invs)s.',
            mode=self.repair_mode,
            invs=', '.join('%s=%s' % (i.name, i.amount_total) for i in posted),
        )
        if self.note:
            body = '%s\n%s' % (body, self.note.strip())
        appt.message_post(body=body)
        appt.invalidate_recordset()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'pet.appointment',
            'res_id': appt.id,
            'view_mode': 'form',
            'target': 'current',
        }
