# -*- coding: utf-8 -*-
from odoo import fields, models


class LoyaltyCard(models.Model):
    _inherit = "loyalty.card"

    petspot_campaign_id = fields.Many2one("petspot.campaign", index=True, copy=False)
    survey_user_input_id = fields.Many2one("survey.user_input", copy=False, readonly=True)
