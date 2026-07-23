# -*- coding: utf-8 -*-
"""
Extends crm.lead with Chatwoot / Evolution WhatsApp tracking fields.
Replaces the old error.report extension from Odoo 18.
"""
from odoo import models, fields, api
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)


class CrmLeadChatwoot(models.Model):
    _inherit = 'crm.lead'

    x_source_platform = fields.Selection([
        ('whatsapp', 'WhatsApp'),
        ('chatwoot', 'Chatwoot'),
        ('evolution', 'Evolution API'),
        ('web',      'Web UI'),
        ('other',    'Other'),
    ], string='Source Platform', tracking=True,
       help='Channel that originated this lead')

    x_reporter_phone = fields.Char(
        string='WA Phone (Sanitized)',
        help='WhatsApp phone without + and @s.whatsapp.net'
    )

    x_reporter_name = fields.Char(
        string='WA Push Name',
        help='pushName from Evolution API message'
    )

    x_reporter_email = fields.Char(
        string='Reporter Email',
        help='Email from Chatwoot contact'
    )

    x_chatwoot_account_id = fields.Char(string='Chatwoot Account ID')
    x_chatwoot_inbox_id   = fields.Char(string='Chatwoot Inbox ID')
    x_chatwoot_conversation_id = fields.Char(
        string='Chatwoot Conversation ID',
        index=True,
        help='Critical for replying back via Chatwoot API'
    )
    x_chatwoot_contact_id  = fields.Char(string='Chatwoot Contact ID')
    x_chatwoot_message_id  = fields.Char(string='Last Chatwoot Message ID')
    x_chatwoot_payload     = fields.Text(string='Chatwoot Payload (JSON)')

    x_external_ref = fields.Char(
        string='External Reference',
        index=True,
        copy=False,
        help='Unique external ref, e.g. CW-{conversation_id}'
    )

    @api.constrains('x_external_ref')
    def _check_unique_external_ref(self):
        for record in self:
            if record.x_external_ref and self.search_count(
                    [('x_external_ref', '=', record.x_external_ref),
                     ('id', '!=', record.id)]) > 0:
                raise ValidationError(
                    'External reference must be unique across leads.')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('x_chatwoot_conversation_id') and not vals.get('x_external_ref'):
                vals['x_external_ref'] = f"CW-{vals['x_chatwoot_conversation_id']}"
        return super().create(vals_list)

    def get_chatwoot_reply_message(self):
        """Return a formatted WhatsApp/Chatwoot reply for this lead."""
        self.ensure_one()
        stage = self.stage_id.name if self.stage_id else 'New'
        return (
            f"✅ *Lead Updated*\n\n"
            f"*Ref:* CRM-{self.id:05d}\n"
            f"*Stage:* {stage}\n"
            f"*Lead:* {self.name}\n\n"
            f"Our team will follow up with you shortly. 🙏"
        )
