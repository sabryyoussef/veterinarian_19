# -*- coding: utf-8 -*-


def migrate(cr, version):
    """Force Default pricelist + historical SO/invoices/payments onto company currency (EGP)."""
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})
    env['pet.clinic.finance.setup'].setup_all_companies()
