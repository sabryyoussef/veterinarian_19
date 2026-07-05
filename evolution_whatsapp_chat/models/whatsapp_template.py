# -*- coding: utf-8 -*-
from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)


class WhatsappTemplate(models.Model):
    _name        = 'evo.wa.template'
    _description = 'Evolution WhatsApp Message Template'
    _order       = 'sequence, name'
    _rec_name    = 'name'

    name = fields.Char(
        string='Template Name', required=True,
        help='Short label shown in the wizard dropdown'
    )
    sequence = fields.Integer(default=10)
    active   = fields.Boolean(default=True)

    language = fields.Selection([
        ('en', 'English'),
        ('ar', 'Arabic'),
        ('both', 'Bilingual'),
    ], string='Language', default='en', required=True)

    category = fields.Selection([
        ('intro',     'Introduction / CV'),
        ('followup',  'Follow-up'),
        ('interview', 'Interview Invitation'),
        ('general',   'General'),
    ], string='Category', default='general', required=True)

    body = fields.Text(
        string='Message Body', required=True,
        help='Use {name} for contact name, {company} for company name, {phone} for phone number'
    )

    note = fields.Char(string='Internal Note')

    def render_body(self, partner=None, lead=None):
        """
        Render the template body substituting placeholders.
        Supports {name}, {company}, {phone}.
        """
        self.ensure_one()
        body = self.body or ''

        contact_name = ''
        company_name = ''
        phone        = ''

        if lead:
            contact_name = lead.partner_name or (lead.partner_id.name if lead.partner_id else '') or ''
            company_name = lead.partner_id.company_name if lead.partner_id else ''
            phone        = lead.phone or lead.mobile or ''
        elif partner:
            contact_name = partner.name or ''
            company_name = partner.company_name or (partner.parent_id.name if partner.parent_id else '') or ''
            phone        = getattr(partner, 'mobile', None) or partner.phone or ''

        # Friendly salutation: use first word of name
        first_name = contact_name.split()[0] if contact_name else 'Hiring Manager'

        body = body.replace('{name}',    contact_name or 'Hiring Manager')
        body = body.replace('{first}',   first_name)
        body = body.replace('{company}', company_name or 'your company')
        body = body.replace('{phone}',   phone)

        return body
