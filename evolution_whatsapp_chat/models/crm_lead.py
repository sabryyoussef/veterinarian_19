# -*- coding: utf-8 -*-
from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)


class CrmLeadWhatsApp(models.Model):
    _inherit = 'crm.lead'

    wa_message_count_lead = fields.Integer(
        string='WhatsApp Messages',
        compute='_compute_wa_message_count_lead',
    )

    @api.depends('partner_id', 'partner_id.wa_channel_id')
    def _compute_wa_message_count_lead(self):
        for lead in self:
            partner = lead.partner_id
            if partner and partner.wa_channel_id:
                lead.wa_message_count_lead = self.env['mail.message'].search_count([
                    ('res_id',       '=', partner.wa_channel_id.id),
                    ('model',        '=', 'discuss.channel'),
                    ('message_type', 'in', ['comment', 'email']),
                ])
            else:
                lead.wa_message_count_lead = 0

    def action_open_wa_channel_lead(self):
        """
        Smart button behaviour:
        - If partner has a WA channel → open it (full chat history)
        - If no channel yet → open the send wizard popup
        - If no partner linked → warn
        """
        self.ensure_one()
        if not self.partner_id:
            return {
                'type':  'ir.actions.client',
                'tag':   'display_notification',
                'params': {
                    'title':   'No Contact',
                    'message': 'Please link a contact to this lead first.',
                    'type':    'warning',
                },
            }
        return self.partner_id.action_open_wa_channel()

    def action_send_whatsapp_lead(self):
        """Open the WhatsApp quick-send wizard for this lead."""
        self.ensure_one()
        phone = self.phone or self.mobile or (
            (getattr(self.partner_id, 'mobile', None) or self.partner_id.phone)
            if self.partner_id else ''
        ) or ''
        return {
            'type':      'ir.actions.act_window',
            'name':      'Send WhatsApp',
            'res_model': 'whatsapp.send.wizard',
            'view_mode': 'form',
            'target':    'new',
            'context': {
                'default_lead_id':    self.id,
                'default_partner_id': self.partner_id.id if self.partner_id else False,
                'default_phone':      phone,
            },
        }
