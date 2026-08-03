# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

FORBIDDEN_SENDERS = ("vetelsahel@gmail.com",)


class MailingMailing(models.Model):
    _inherit = "mailing.mailing"

    company_id = fields.Many2one(
        "res.company",
        string="Company",
        index=True,
        default=lambda self: self.env.company,
    )

    @api.constrains("company_id", "email_from")
    def _check_sabry_sender(self):
        sabry = self.env.ref(
            "sabry_odoo_company_isolation.company_sabry_odoo_development",
            raise_if_not_found=False,
        )
        for rec in self:
            email_from = (rec.email_from or "").lower()
            for forbidden in FORBIDDEN_SENDERS:
                if forbidden in email_from and sabry and rec.company_id == sabry:
                    raise ValidationError(
                        "Sabry outreach mailings must not use vetelsahel@gmail.com."
                    )

    def _sabry_blocks_mass_launch(self):
        """Production partner list must not be mass-launched without explicit context."""
        self.ensure_one()
        sabry = self.env.ref(
            "sabry_odoo_company_isolation.company_sabry_odoo_development",
            raise_if_not_found=False,
        )
        if not sabry or self.company_id != sabry:
            return False
        if self.env.context.get("allow_sabry_partner_send"):
            return False
        for lst in self.contact_list_ids:
            name = lst.name or ""
            if "Gold Silver" in name and "Test" not in name and "Sample" not in name:
                return True
        return False

    def action_launch(self):
        for mailing in self:
            if mailing._sabry_blocks_mass_launch():
                raise UserError(
                    "Production Sabry partner campaigns must stay in Draft. "
                    "Use Test for abhorya/vendorah2 only."
                )
        return super().action_launch()

    def action_put_in_queue(self):
        for mailing in self:
            if mailing._sabry_blocks_mass_launch():
                raise UserError(
                    "Production Sabry partner campaigns must stay in Draft. "
                    "Use Test for abhorya/vendorah2 only."
                )
        return super().action_put_in_queue()
