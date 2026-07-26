# -*- coding: utf-8 -*-

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    vetution_default_connection_id = fields.Many2one(
        "vetution.connection",
        string="Default Vetution Connection",
        config_parameter="vetution_supplier.default_connection_id",
    )
