# -*- coding: utf-8 -*-
from odoo import fields, models

from .petspot_wa_intake import PETSPOT_GROUP_JID_DEFAULT, PETSPOT_INBOX_ID_DEFAULT


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    petspot_wa_group_jid = fields.Char(
        string='PetSpot WhatsApp Group JID',
        config_parameter='petspot_wa_intake.group_jid',
        default=PETSPOT_GROUP_JID_DEFAULT,
    )
    petspot_wa_chatwoot_inbox_id = fields.Char(
        string='PetSpot Chatwoot Inbox ID',
        config_parameter='petspot_wa_intake.chatwoot_inbox_id',
        default=PETSPOT_INBOX_ID_DEFAULT,
    )
    petspot_wa_chatwoot_label = fields.Char(
        string='PetSpot Chatwoot Label',
        config_parameter='petspot_wa_intake.chatwoot_label',
        default='petspot-sahel',
    )
