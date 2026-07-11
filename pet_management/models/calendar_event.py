# -*- coding: utf-8 -*-
"""Appointment-app bookings → pet.appointment (Phase 3)."""
import logging

from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)


class CalendarEvent(models.Model):
    _inherit = 'calendar.event'

    pet_appointment_id = fields.Many2one(
        'pet.appointment',
        string='Pet Appointment',
        index=True,
        copy=False,
        ondelete='set null',
        help='Clinic appointment linked to this calendar / Appointment booking.',
    )

    def get_formview_action(self, access_uid=None):
        """Clinic meetings open the pet appointment (clinic source of truth)."""
        self.ensure_one()
        if (
            self.pet_appointment_id
            and not self.env.context.get('calendar_event_keep_form')
        ):
            return self.pet_appointment_id.get_formview_action(access_uid=access_uid)
        return super().get_formview_action(access_uid=access_uid)

    def action_open_pet_appointment(self):
        """Open the linked clinic pet.appointment from Calendar / Appointment."""
        self.ensure_one()
        if not self.pet_appointment_id:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Info'),
                    'message': _('No pet appointment is linked to this meeting.'),
                    'type': 'warning',
                    'sticky': False,
                },
            }
        return {
            'type': 'ir.actions.act_window',
            'name': _('Pet Appointment'),
            'res_model': 'pet.appointment',
            'res_id': self.pet_appointment_id.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'current',
        }

    def action_open_meeting_or_pet(self):
        """Used when clicking a meeting in Calendar / Appointment list/gantt/calendar."""
        self.ensure_one()
        if self.pet_appointment_id and not self.env.context.get('calendar_event_keep_form'):
            return self.action_open_pet_appointment()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Meeting'),
            'res_model': 'calendar.event',
            'res_id': self.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'current',
            'context': {'calendar_event_keep_form': True},
        }

    def action_open_calendar_event(self):
        """Popover / Linked document open — prefer pet appointment when linked."""
        self.ensure_one()
        if self.pet_appointment_id and not self.env.context.get('calendar_event_keep_form'):
            return self.action_open_pet_appointment()
        return super().action_open_calendar_event()

    @api.model_create_multi
    def create(self, vals_list):
        events = super().create(vals_list)
        if self.env.context.get('skip_pet_appointment_from_booking'):
            return events
        events._maybe_create_pet_appointments_from_booking()
        return events

    def write(self, vals):
        res = super().write(vals)
        if self.env.context.get('skip_pet_appointment_from_booking'):
            return res
        # Keep pet appointment times in sync when booking is rescheduled from Calendar/Appointment.
        sync_fields = {'start', 'stop', 'user_id', 'appointment_type_id', 'partner_ids'}
        if sync_fields & set(vals):
            self.filtered('pet_appointment_id')._sync_linked_pet_appointment_from_event()
            self.filtered(lambda e: not e.pet_appointment_id)._maybe_create_pet_appointments_from_booking()
        return res

    def _clinic_appointment_type(self):
        self.ensure_one()
        atype = self.appointment_type_id
        if atype and atype.pet_primary_type:
            return atype
        return self.env['appointment.type'].browse()

    def _maybe_create_pet_appointments_from_booking(self):
        if 'appointment.type' not in self.env:
            return
        Appointment = self.env['pet.appointment'].with_context(
            skip_calendar_event_sync=True,
            skip_pet_appointment_from_booking=True,
        )
        for event in self:
            if event.pet_appointment_id or not event._clinic_appointment_type():
                continue
            if event.active is False:
                continue
            try:
                appt = Appointment._create_from_calendar_booking(event)
                if appt:
                    event.with_context(skip_pet_appointment_from_booking=True).write({
                        'pet_appointment_id': appt.id,
                    })
                    if not appt.calendar_event_id:
                        appt.with_context(skip_calendar_event_sync=True).write({
                            'calendar_event_id': event.id,
                        })
            except Exception:
                _logger.exception(
                    'Failed to create pet.appointment from calendar.event %s', event.id,
                )

    def _sync_linked_pet_appointment_from_event(self):
        for event in self:
            appt = event.pet_appointment_id
            if not appt or appt.state == 'cancelled':
                continue
            vals = {}
            if event.start and appt.start_datetime != event.start:
                vals['start_datetime'] = event.start
            if event.stop and appt.end_datetime != event.stop:
                vals['end_datetime'] = event.stop
            atype = event._clinic_appointment_type()
            if atype and atype.pet_primary_type and appt.primary_type != atype.pet_primary_type:
                if atype.pet_primary_type in dict(appt._fields['primary_type'].selection):
                    vals['primary_type'] = atype.pet_primary_type
            # Map organizer user → vet employee when possible
            if event.user_id:
                employee = self.env['hr.employee'].search([
                    ('user_id', '=', event.user_id.id),
                ], limit=1)
                if employee and appt.vet_employee_id != employee:
                    vals['vet_employee_id'] = employee.id
            # Prefer first non-staff attendee as owner
            owner = event._booking_customer_partner()
            if owner and appt.intake_owner_id != owner:
                vals['intake_owner_id'] = owner.id
            if vals:
                appt.with_context(skip_calendar_event_sync=True).write(vals)

    def _booking_customer_partner(self):
        self.ensure_one()
        staff_partners = self.user_id.partner_id
        if self.appointment_type_id:
            staff_partners |= self.appointment_type_id.staff_user_ids.partner_id
        customers = self.partner_ids - staff_partners
        return customers[:1]
