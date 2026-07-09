# -*- coding: utf-8 -*-
from odoo import fields, models


class PetAppointment(models.Model):
    _inherit = "pet.appointment"

    portal_source = fields.Selection(
        selection_add=[("campaign", "Campaign Reward")],
        ondelete={"campaign": "set default"},
    )
    loyalty_card_id = fields.Many2one("loyalty.card", copy=False, index=True)
    petspot_campaign_id = fields.Many2one("petspot.campaign", copy=False, index=True)
