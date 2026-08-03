# -*- coding: utf-8 -*-
def migrate(cr, version):
    """Seed verified answer library for personal account id=2."""
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})
    Account = env["linkedin.account"].sudo()
    account = Account.browse(2).exists()
    if not account or account.account_type != "personal":
        return
    env["linkedin.answer.library"].seed_personal_account_defaults(account_id=2)
