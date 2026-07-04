# -*- coding: utf-8 -*-
from datetime import datetime, timedelta, time

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class PetspotClinicSlot(models.Model):
    _name = 'petspot.clinic.slot'
    _description = 'PetSpot Clinic Booking Slot'
    _order = 'start_datetime'

    name = fields.Char(compute='_compute_name', store=True)
    start_datetime = fields.Datetime(required=True, index=True)
    end_datetime = fields.Datetime(required=True)
    capacity = fields.Integer(default=1, required=True)
    booked_count = fields.Integer(compute='_compute_booked', store=True)
    is_available = fields.Boolean(compute='_compute_booked', store=True)
    active = fields.Boolean(default=True)
    appointment_ids = fields.One2many('pet.appointment', 'portal_slot_id', string='Appointments')

    @api.depends('start_datetime', 'end_datetime')
    def _compute_name(self):
        for rec in self:
            if rec.start_datetime:
                rec.name = fields.Datetime.to_string(rec.start_datetime)
            else:
                rec.name = _('Slot')

    @api.depends('appointment_ids', 'appointment_ids.state', 'capacity')
    def _compute_booked(self):
        for rec in self:
            active_appts = rec.appointment_ids.filtered(
                lambda a: a.state not in ('cancelled',)
            )
            rec.booked_count = len(active_appts)
            rec.is_available = rec.active and rec.booked_count < rec.capacity

    @api.model
    def get_available_slots(self, limit=20):
        now = fields.Datetime.now()
        slots = self.search([
            ('active', '=', True),
            ('start_datetime', '>=', now),
        ], order='start_datetime', limit=max(limit * 3, 30))
        return slots.filtered(lambda s: s.booked_count < s.capacity)[:limit]

    @api.model
    def ensure_upcoming_slots(self, days=7):
        """Generate simple daily slots from working hours config if none exist."""
        ICP = self.env['ir.config_parameter'].sudo()
        hours_raw = ICP.get_param('petspot_clinic_portal.slot_hours', '10:00,12:00,14:00,16:00,18:00')
        duration = int(ICP.get_param('petspot_clinic_portal.default_appointment_minutes', '30'))
        hour_list = []
        for part in hours_raw.split(','):
            part = part.strip()
            if not part:
                continue
            try:
                hh, mm = part.split(':')
                hour_list.append((int(hh), int(mm)))
            except Exception:
                continue
        if not hour_list:
            hour_list = [(10, 0), (12, 0), (14, 0), (16, 0), (18, 0)]

        today = fields.Date.today()
        created = self.browse()
        for day_offset in range(days):
            day = today + timedelta(days=day_offset)
            # Skip Fridays optionally? keep all days for clinic flexibility
            for hh, mm in hour_list:
                start = datetime.combine(day, time(hh, mm))
                # store as naive UTC-ish Odoo datetime string
                start_dt = fields.Datetime.to_datetime(start.strftime('%Y-%m-%d %H:%M:%S'))
                if start_dt < fields.Datetime.now():
                    continue
                end_dt = start_dt + timedelta(minutes=duration)
                existing = self.search([
                    ('start_datetime', '=', start_dt),
                    ('active', '=', True),
                ], limit=1)
                if existing:
                    continue
                created |= self.create({
                    'start_datetime': start_dt,
                    'end_datetime': end_dt,
                    'capacity': 3,
                })
        return created

    def reserve_for_appointment(self):
        self.ensure_one()
        self.invalidate_recordset(['booked_count', 'is_available'])
        self._compute_booked()
        if not self.is_available:
            raise ValidationError(_('هذا الموعد ممتلئ، اختر موعدًا آخر.'))
        return True
