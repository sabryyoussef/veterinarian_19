# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ResPartner(models.Model):
    _inherit = "res.partner"

    x_source_partner_id = fields.Many2one(
        "res.partner",
        string="Source PetSpot Partner",
        index=True,
        ondelete="set null",
        help="Audit link from Sabry outreach copy back to the source partner.",
    )
    x_outreach_eligible = fields.Boolean(
        string="Outreach Eligible",
        default=False,
        index=True,
        help="True for curated Sabry-company outreach copies.",
    )

    @api.constrains("company_id", "x_outreach_eligible")
    def _check_outreach_company_required(self):
        for partner in self:
            if partner.x_outreach_eligible and not partner.company_id:
                raise ValidationError(
                    "Outreach partners must belong to a company (Sabry Odoo Development)."
                )
