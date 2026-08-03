# -*- coding: utf-8 -*-
from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    is_sabry_outreach_company = fields.Boolean(
        string="Sabry Outreach Company",
        default=False,
        help="Marks the Sabry Odoo Development company used for professional outreach.",
    )
