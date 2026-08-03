# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class MailingContact(models.Model):
    _inherit = "mailing.contact"

    company_id = fields.Many2one(
        "res.company",
        string="Company",
        index=True,
        default=lambda self: self.env.company,
    )

    @api.constrains("company_id", "email")
    def _check_sabry_contact_company(self):
        sabry = self.env.ref(
            "sabry_odoo_company_isolation.company_sabry_odoo_development",
            raise_if_not_found=False,
        )
        if not sabry:
            return
        for rec in self:
            if rec.company_id and rec.company_id == sabry and not rec.email:
                raise ValidationError("Sabry mailing contacts require an email.")
