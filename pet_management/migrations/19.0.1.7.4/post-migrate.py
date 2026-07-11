# -*- coding: utf-8 -*-


def migrate(cr, version):
    """Point Clinic InstaPay funding source at the real INPY payment journal."""
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})
    env['pet.clinic.finance.setup'].setup_all_companies()
