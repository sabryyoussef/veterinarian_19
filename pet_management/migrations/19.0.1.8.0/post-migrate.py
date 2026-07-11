# -*- coding: utf-8 -*-


def migrate(cr, version):
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})
    if 'appointment.type' in env:
        env['appointment.type'].ensure_clinic_pet_appointment_types()
    env['pet.appointment']._backfill_missing_calendar_events()
    # Link reverse pet_appointment_id on existing calendar events
    cr.execute(
        """
        UPDATE calendar_event ce
           SET pet_appointment_id = pa.id
          FROM pet_appointment pa
         WHERE pa.calendar_event_id = ce.id
           AND (ce.pet_appointment_id IS NULL OR ce.pet_appointment_id = 0)
        """
    )
