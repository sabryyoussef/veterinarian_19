# -*- coding: utf-8 -*-
from odoo import fields, models


class MailTemplate(models.Model):
    _inherit = "mail.template"

    company_id = fields.Many2one(
        "res.company",
        string="Company",
        index=True,
        help="Optional company ownership for Sabry outreach templates.",
    )
