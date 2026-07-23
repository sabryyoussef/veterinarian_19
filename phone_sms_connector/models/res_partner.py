# -*- coding: utf-8 -*-
from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)


class ResPartnerSms(models.Model):
    _inherit = 'res.partner'

    sms_message_count = fields.Integer(
        string='SMS Messages', compute='_compute_sms_message_count',
    )

    def _compute_sms_message_count(self):
        Log = self.env['sms.message.log']
        for partner in self:
            partner.sms_message_count = Log.search_count([('partner_id', '=', partner.id)]) if partner.id else 0

    def action_send_sms_message(self):
        """Open the SMS send wizard pre-filled for this contact."""
        self.ensure_one()
        phone_raw = getattr(self, 'mobile', None) or self.phone or ''
        return {
            'type': 'ir.actions.act_window',
            'name': 'Send SMS',
            'res_model': 'sms.send.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_partner_id': self.id,
                'default_phone': phone_raw,
            },
        }

    def action_view_sms_messages(self):
        """Open the SMS message log for this contact."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'SMS — {self.name}',
            'res_model': 'sms.message.log',
            'view_mode': 'list,form',
            'domain': [('partner_id', '=', self.id)],
            'context': {'default_partner_id': self.id},
        }
