# -*- coding: utf-8 -*-
from odoo import fields, models


class PetspotPortalSubmitLog(models.Model):
    _name = 'petspot.portal.submit.log'
    _description = 'PetSpot Portal Submit Audit Log'
    _order = 'id desc'

    name = fields.Char(required=True, default='Submit')
    submit_type = fields.Selection(
        [
            ('book', 'Booking'),
            ('exam', 'Exam'),
        ],
        required=True,
        index=True,
    )
    token_id = fields.Many2one('petspot.portal.token', ondelete='set null')
    phone = fields.Char(index=True)
    partner_id = fields.Many2one('res.partner')
    pet_id = fields.Many2one('pet.pet')
    appointment_id = fields.Many2one('pet.appointment')
    medical_visit_id = fields.Many2one('pet.medical.visit')
    chatwoot_conversation_id = fields.Integer()
    source = fields.Selection(
        [
            ('portal', 'Portal'),
            ('chatwoot', 'Chatwoot'),
            ('whatsapp_group', 'WhatsApp Group'),
            ('manual', 'Manual'),
        ],
        default='portal',
    )
    submit_time = fields.Datetime(default=fields.Datetime.now, required=True, index=True)
    notes = fields.Text()
