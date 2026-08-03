# -*- coding: utf-8 -*-
from odoo import models
from odoo.exceptions import UserError

_MSG = (
    "Legacy WhatsApp marketing campaigns are retired. "
    "Customer marketing must use PetSpot WA Marketing Queue "
    "(petspot_wa_marketing_queue) only."
)


class WaCampaign(models.Model):
    _inherit = "wa.campaign"

    def _petspot_block_legacy_marketing(self):
        raise UserError(self.env._(_MSG))

    def action_start_campaign(self):
        self._petspot_block_legacy_marketing()

    def action_resume_campaign(self):
        self._petspot_block_legacy_marketing()

    def action_generate_lines(self):
        self._petspot_block_legacy_marketing()

    def action_load_recipients(self):
        self._petspot_block_legacy_marketing()

    def action_retry_failed(self):
        self._petspot_block_legacy_marketing()

    def action_clone_campaign(self):
        # Cloning would recreate a runnable marketing campaign.
        self._petspot_block_legacy_marketing()

    def _process_campaign_queue(self):
        # Defense in depth if anything calls processing directly.
        self._petspot_block_legacy_marketing()
