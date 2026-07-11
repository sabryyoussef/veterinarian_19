# -*- coding: utf-8 -*-


def post_init_hook(env):
    """Idempotent per-company clinic finance accounting + source/category setup."""
    env['pet.clinic.finance.setup'].setup_all_companies()
    # Owner field on the form is intake_owner_id; backfill from pet for legacy rows.
    env['pet.appointment']._backfill_all_missing_intake_owners()
    if 'appointment.type' in env:
        env['appointment.type'].ensure_clinic_pet_appointment_types()
    env['pet.appointment']._backfill_missing_calendar_events()
