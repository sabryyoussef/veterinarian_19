# -*- coding: utf-8 -*-

from odoo import fields, models


class LeadEngineSource(models.Model):
    _inherit = "lead.engine.source"

    inbound_api_token = fields.Char(
        copy=False,
        help="Bearer token for POST /lead_engine/v1/intake. Leave empty to disable HTTP intake for this source. "
        "Shown only to Lead Engine managers in the UI (see view groups).",
    )
