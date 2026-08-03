# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class MailingList(models.Model):
    _inherit = "mailing.list"

    company_id = fields.Many2one(
        "res.company",
        string="Company",
        index=True,
        default=lambda self: self.env.company,
    )

    @api.constrains("company_id")
    def _check_company_id(self):
        for rec in self:
            if rec.name and rec.name.startswith("Sabry") and not rec.company_id:
                raise ValidationError("Sabry mailing lists require a company.")
