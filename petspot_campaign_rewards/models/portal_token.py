# -*- coding: utf-8 -*-
from odoo import fields, models


class PetspotPortalToken(models.Model):
    _inherit = "petspot.portal.token"

    loyalty_card_id = fields.Many2one("loyalty.card", copy=False, index=True)
    petspot_campaign_id = fields.Many2one("petspot.campaign", copy=False, index=True)
    survey_user_input_id = fields.Many2one("survey.user_input", copy=False, index=True)

    def _resolve_portal_source(self):
        self.ensure_one()
        if self.loyalty_card_id or self.prefill_discount_code:
            return "campaign"
        return super()._resolve_portal_source()

    def _appointment_booking_extra_vals(self):
        vals = super()._appointment_booking_extra_vals()
        if self.loyalty_card_id:
            vals["loyalty_card_id"] = self.loyalty_card_id.id
        if self.petspot_campaign_id:
            vals["petspot_campaign_id"] = self.petspot_campaign_id.id
        return vals
