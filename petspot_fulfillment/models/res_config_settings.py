# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    petspot_ff_chatwoot_intake_enabled = fields.Boolean(
        string="Enable Chatwoot availability intake",
        config_parameter="petspot_fulfillment.chatwoot_intake_enabled",
    )
    petspot_ff_chatwoot_webhook_secret = fields.Char(
        string="Chatwoot webhook secret",
        config_parameter="petspot_fulfillment.chatwoot_webhook_secret",
    )
    petspot_ff_chatwoot_account_id = fields.Char(
        string="Permitted Chatwoot account ID",
        config_parameter="petspot_fulfillment.chatwoot_account_id",
        default="2",
    )
    petspot_ff_chatwoot_inbox_id = fields.Char(
        string="Permitted Chatwoot inbox ID",
        config_parameter="petspot_fulfillment.chatwoot_inbox_id",
        default="2",
    )
    petspot_ff_chatwoot_ack_enabled = fields.Boolean(
        string="Send Chatwoot acknowledgement",
        config_parameter="petspot_fulfillment.chatwoot_ack_enabled",
        default=True,
    )
    petspot_ff_chatwoot_test_mode = fields.Boolean(
        string="Chatwoot intake test mode",
        config_parameter="petspot_fulfillment.chatwoot_test_mode",
        help="When enabled without API token, ack is recorded locally only.",
    )
    petspot_ff_chatwoot_base_url = fields.Char(
        string="Chatwoot base URL",
        config_parameter="petspot_fulfillment.chatwoot_base_url",
    )
    petspot_ff_chatwoot_api_token = fields.Char(
        string="Chatwoot API token",
        config_parameter="petspot_fulfillment.chatwoot_api_token",
    )
