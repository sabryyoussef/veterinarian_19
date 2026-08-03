# -*- coding: utf-8 -*-
from odoo import models
from odoo.exceptions import UserError

_MSG = (
    "Legacy WhatsApp marketing campaign recipients are retired. "
    "Customer marketing must use PetSpot WA Marketing Queue "
    "(petspot_wa_marketing_queue) only."
)


class WaCampaignRecipientWizard(models.TransientModel):
    _inherit = "wa.campaign.recipient.wizard"

    def action_add_recipients(self):
        raise UserError(self.env._(_MSG))
