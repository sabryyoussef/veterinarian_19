# -*- coding: utf-8 -*-

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    lead_engine_payload_max_chars = fields.Integer(
        string="Lead Engine intake payload max length",
        config_parameter="lead_engine.payload_max_chars",
        default=65536,
        help="Maximum characters stored in lead.engine.intake.log payload_raw (truncation).",
    )
