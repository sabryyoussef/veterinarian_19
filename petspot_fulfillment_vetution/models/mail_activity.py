# -*- coding: utf-8 -*-
from odoo import fields, models


class MailActivity(models.Model):
    _inherit = "mail.activity"

    petspot_managed = fields.Boolean(
        default=False,
        index=True,
        help="True when created by PetSpot Vetution ops orchestrator.",
    )
    petspot_action_code = fields.Char(
        index=True,
        help="Stable ops action code (e.g. MAPPING_REQUIRED).",
    )
