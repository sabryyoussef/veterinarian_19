# -*- coding: utf-8 -*-
"""sms.template — reusable SMS message templates with placeholder rendering."""
import logging

from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class SmsTemplate(models.Model):
    _name = 'phone.sms.template'
    _description = 'Phone SMS Template'
    _order = 'sequence, name'
    _rec_name = 'name'

    name = fields.Char(string='Template Name', required=True,
                       help='Short label shown in the send wizard dropdown')
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    category = fields.Selection(
        selection=[
            ('general', 'General'),
            ('reminder', 'Reminder'),
            ('followup', 'Follow-up'),
            ('promo', 'Promotion'),
            ('otp', 'OTP / Notification'),
        ],
        string='Category', default='general', required=True,
    )

    body = fields.Text(
        string='Message Body', required=True,
        help='Use {name} for contact name, {first} for first name, '
             '{company} for company, {phone} for phone number',
    )
    note = fields.Char(string='Internal Note')

    def render_body(self, partner=None, lead=None):
        """Render the template body substituting {name}, {first}, {company}, {phone}."""
        self.ensure_one()
        body = self.body or ''

        contact_name = company_name = phone = ''
        if lead:
            contact_name = lead.partner_name or (lead.partner_id.name if lead.partner_id else '') or ''
            company_name = (lead.partner_id.company_name if lead.partner_id else '') or ''
            phone = lead.phone or lead.mobile or ''
        elif partner:
            contact_name = partner.name or ''
            company_name = partner.company_name or (partner.parent_id.name if partner.parent_id else '') or ''
            phone = getattr(partner, 'mobile', None) or partner.phone or ''

        first_name = contact_name.split()[0] if contact_name else 'there'

        body = body.replace('{name}', contact_name or 'there')
        body = body.replace('{first}', first_name)
        body = body.replace('{company}', company_name or 'your company')
        body = body.replace('{phone}', phone or '')
        return body
