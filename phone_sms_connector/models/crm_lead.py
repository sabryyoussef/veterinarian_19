# -*- coding: utf-8 -*-
from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)


class CrmLeadSms(models.Model):
    _inherit = 'crm.lead'

    sms_message_count = fields.Integer(
        string='SMS Messages', compute='_compute_sms_message_count',
    )

    def _compute_sms_message_count(self):
        Log = self.env['sms.message.log']
        for lead in self:
            lead.sms_message_count = Log.search_count([('lead_id', '=', lead.id)]) if lead.id else 0

    def action_send_sms_lead(self):
        """Open the SMS send wizard pre-filled for this lead."""
        self.ensure_one()
        phone = self.phone or self.mobile or ''
        if not phone and self.partner_id:
            phone = getattr(self.partner_id, 'mobile', None) or self.partner_id.phone or ''
        return {
            'type': 'ir.actions.act_window',
            'name': 'Send SMS',
            'res_model': 'sms.send.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_lead_id': self.id,
                'default_partner_id': self.partner_id.id if self.partner_id else False,
                'default_phone': phone,
            },
        }

    def action_view_sms_messages_lead(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'SMS — {self.name}',
            'res_model': 'sms.message.log',
            'view_mode': 'list,form',
            'domain': [('lead_id', '=', self.id)],
            'context': {'default_lead_id': self.id},
        }
