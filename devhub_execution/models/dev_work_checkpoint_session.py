# -*- coding: utf-8 -*-
from odoo import fields, models


class DevWorkCheckpointSession(models.Model):
    _inherit = "dev.work.checkpoint"

    session_id = fields.Many2one(
        "dev.session", ondelete="restrict", readonly=True, index=True
    )
