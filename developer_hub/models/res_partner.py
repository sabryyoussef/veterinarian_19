# -*- coding: utf-8 -*-
from odoo import api, fields, models

TIER_BY_CATEGORY_NAME = {
    "Gold": "gold",
    "Silver": "silver",
    "Ready for Outreach": "ready",
    "Bronze": "bronze",
}
TIER_RANK = {"gold": 1, "silver": 2, "ready": 3, "bronze": 4}


class ResPartner(models.Model):
    _inherit = "res.partner"

    odoo_partner_tier = fields.Selection(
        selection=[
            ("gold", "Gold"),
            ("silver", "Silver"),
            ("ready", "Ready"),
            ("bronze", "Bronze"),
        ],
        string="Partnership Level",
        compute="_compute_odoo_partner_tier",
        store=True,
        index=True,
    )

    @api.depends("category_id", "category_id.name")
    def _compute_odoo_partner_tier(self):
        for partner in self:
            tier = False
            best_rank = 99
            for cat in partner.category_id:
                code = TIER_BY_CATEGORY_NAME.get(cat.name)
                if not code:
                    continue
                rank = TIER_RANK[code]
                if rank < best_rank:
                    tier = code
                    best_rank = rank
            partner.odoo_partner_tier = tier
