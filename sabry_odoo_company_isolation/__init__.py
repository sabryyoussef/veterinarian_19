# -*- coding: utf-8 -*-
from . import models
from . import wizard


def post_init_hook(env):
    """Ensure admin can switch to Sabry company and rebind Sabry website."""
    from odoo.addons.sabry_odoo_company_isolation.models.outreach_service import (
        OutreachService,
    )

    OutreachService(env).ensure_company_bootstrap()
