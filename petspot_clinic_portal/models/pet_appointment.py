# -*- coding: utf-8 -*-
from odoo import fields, models


class PetAppointment(models.Model):
    _inherit = 'pet.appointment'

    portal_source = fields.Selection(
        [
            ('backend', 'Backend'),
            ('portal', 'Clinic Portal'),
            ('chatwoot', 'Chatwoot / WhatsApp'),
        ],
        default='backend',
        string='Portal Source',
    )
    chatwoot_conversation_id = fields.Integer(index=True, string='Chatwoot Conversation')
