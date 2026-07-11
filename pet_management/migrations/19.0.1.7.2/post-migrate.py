# -*- coding: utf-8 -*-


def migrate(cr, version):
    """Backfill appointment Owner (intake_owner_id) from pet.owner_id when empty."""
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})
    env['pet.appointment']._backfill_all_missing_intake_owners()
