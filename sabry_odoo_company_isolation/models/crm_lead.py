# -*- coding: utf-8 -*-
from odoo import api, models


class CrmLead(models.Model):
    _inherit = "crm.lead"

    @api.model_create_multi
    def create(self, vals_list):
        sabry = self.env.ref(
            "sabry_odoo_company_isolation.company_sabry_odoo_development",
            raise_if_not_found=False,
        )
        website = False
        if self.env.context.get("website_id"):
            website = self.env["website"].browse(self.env.context["website_id"])
        for vals in vals_list:
            if sabry and website and website.exists() and website.company_id == sabry:
                vals.setdefault("company_id", sabry.id)
                team = self.env["crm.team"].sudo().search(
                    [
                        ("name", "=", "Odoo Partner Outreach"),
                        "|",
                        ("company_id", "=", sabry.id),
                        ("company_id", "=", False),
                    ],
                    limit=1,
                )
                if team:
                    vals.setdefault("team_id", team.id)
        return super().create(vals_list)
