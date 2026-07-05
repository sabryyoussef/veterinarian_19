# -*- coding: utf-8 -*-
import logging
import re

from odoo import models, fields, api

_logger = logging.getLogger(__name__)


def _normalise_phone(raw):
    """Strip non-digits; convert Egyptian local 01… to international 201…"""
    if not raw:
        return ''
    clean = re.sub(r'\D', '', str(raw))
    if not clean:
        return ''
    # Fix +2001… / 2001… double-zero artefact → 201…
    if clean.startswith('2001') and len(clean) >= 12:
        clean = '20' + clean[3:]
    # Egyptian mobile: 01xxxxxxxxx → 201xxxxxxxxx
    elif clean.startswith('0') and len(clean) == 11:
        clean = '20' + clean[1:]
    return clean


class ResPartnerWhatsApp(models.Model):
    _inherit = 'res.partner'

    # ── WhatsApp channel link ─────────────────────────────────────────────────

    wa_channel_id = fields.Many2one(
        'discuss.channel',
        string='WhatsApp Channel',
        copy=False, ondelete='set null',
        help='Dedicated WhatsApp Discuss channel for this contact'
    )

    wa_message_count = fields.Integer(
        string='WhatsApp Messages',
        compute='_compute_wa_message_count',
        help='Total messages in the WhatsApp channel'
    )

    wa_unread_count = fields.Integer(
        string='Unread WhatsApp',
        compute='_compute_wa_unread_count',
        help='Unread inbound messages in the WhatsApp channel'
    )

    # ── Computed counts ───────────────────────────────────────────────────────

    @api.depends('wa_channel_id')
    def _compute_wa_message_count(self):
        for partner in self:
            if partner.wa_channel_id:
                partner.wa_message_count = self.env['mail.message'].search_count([
                    ('res_id',    '=', partner.wa_channel_id.id),
                    ('model',     '=', 'discuss.channel'),
                    ('message_type', 'in', ['comment', 'email']),
                ])
            else:
                partner.wa_message_count = 0

    @api.depends('wa_channel_id')
    def _compute_wa_unread_count(self):
        """Count inbound messages (from contact, not internal users) since last read."""
        for partner in self:
            if not partner.wa_channel_id:
                partner.wa_unread_count = 0
                continue
            # Messages authored by the contact partner (not internal users)
            partner.wa_unread_count = self.env['mail.message'].search_count([
                ('res_id',    '=', partner.wa_channel_id.id),
                ('model',     '=', 'discuss.channel'),
                ('author_id', '=', partner.id),
                ('message_type', '=', 'comment'),
            ])

    # ── Channel factory ───────────────────────────────────────────────────────

    def _get_or_create_wa_channel(self):
        """
        Return the dedicated WhatsApp discuss.channel for this partner,
        creating it lazily on first call.
        """
        self.ensure_one()

        if self.wa_channel_id:
            return self.wa_channel_id

        # Resolve best phone number
        phone_raw = (
            getattr(self, 'mobile', None)
            or self.phone
            or ''
        )
        phone = _normalise_phone(phone_raw)

        # Use channel_type='group' — NOT 'whatsapp'.
        # The enterprise WhatsApp module owns channel_type='whatsapp' and its
        # _check_whatsapp_number constraint requires whatsapp_number + wa_account_id.
        # We identify our channels by wa_phone being non-empty instead.
        channel = self.env['discuss.channel'].sudo().create({
            'name':          f"WA: {self.name}",
            'channel_type':  'group',
            'wa_partner_id': self.id,
            'wa_phone':      phone,
            'description':   f"Evolution WhatsApp — {self.name} ({phone})",
        })

        # Subscribe the current user so they see messages
        channel.sudo().add_members(self.env.user.partner_id.ids)

        self.sudo().write({'wa_channel_id': channel.id})
        _logger.info(f"[WA] Created channel #{channel.id} for partner {self.name} ({phone})")
        return channel

    # ── Action: open channel in Discuss ──────────────────────────────────────

    def action_open_wa_channel(self):
        """
        Smart button behaviour:
        - If a WA channel already exists → open it in current view (full chat history)
        - If no channel yet → open the send wizard so the first message creates it
        """
        self.ensure_one()
        if self.wa_channel_id:
            return {
                'type':      'ir.actions.act_window',
                'name':      f"WhatsApp — {self.name}",
                'res_model': 'discuss.channel',
                'res_id':    self.wa_channel_id.id,
                'view_mode': 'form',
                'target':    'current',
            }
        # No channel yet — go straight to send wizard
        return self.action_send_whatsapp()

    # ── Action: open send wizard ──────────────────────────────────────────────

    def action_send_whatsapp(self):
        """Open the WhatsApp quick-send wizard pre-filled for this partner."""
        self.ensure_one()
        phone_raw = (
            getattr(self, 'mobile', None)
            or self.phone
            or ''
        )
        return {
            'type':      'ir.actions.act_window',
            'name':      'Send WhatsApp',
            'res_model': 'whatsapp.send.wizard',
            'view_mode': 'form',
            'target':    'new',
            'context': {
                'default_partner_id': self.id,
                'default_phone':      phone_raw,
            },
        }
