# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    petspot_campaign_send_whatsapp = fields.Boolean(
        string="Send WhatsApp on Campaign Reward",
        config_parameter="petspot_campaign.send_whatsapp_rewards",
        default=True,
    )
