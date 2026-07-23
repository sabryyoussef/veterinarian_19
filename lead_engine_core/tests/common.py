# -*- coding: utf-8 -*-
"""
Shared helpers for Lead Engine tests.

Dependent addons can import with::

    from odoo.addons.lead_engine_core.tests.common import create_lead_engine_source
"""


def create_lead_engine_source(env, code="SRC_FIX", channel="api", company=None, **kwargs):
    """Create a ``lead.engine.source`` with sane defaults."""
    company = company or env.company
    vals = {
        "name": f"Source {code}",
        "code": code,
        "channel": channel,
        "company_id": company.id,
    }
    vals.update(kwargs)
    return env["lead.engine.source"].create(vals)
