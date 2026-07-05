# -*- coding: utf-8 -*-
"""
wa.message.log — tracks every WhatsApp message (outbound & inbound).

Outbound messages are created when we call Evolution API.
Inbound messages are created when Evolution posts a webhook.
Delivery/read status is updated via the /bridge/evolution/webhook endpoint.
"""
import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class WaMessageLog(models.Model):
    _name        = 'wa.message.log'
    _description = 'WhatsApp Message Log'
    _order       = 'sent_at desc, id desc'
    _rec_name    = 'display_name'

    # ── Identification ────────────────────────────────────────────────────────

    partner_id = fields.Many2one('res.partner', string='Contact', index=True, ondelete='set null')
    lead_id    = fields.Many2one('crm.lead',    string='Lead',    index=True, ondelete='set null')
    phone      = fields.Char(string='Phone', required=True, index=True)
    channel_id = fields.Many2one('discuss.channel', string='WA Channel', ondelete='set null')
    queue_id   = fields.Many2one(
        'integration.outbound.queue', string='Queue Record', ondelete='set null'
    )

    # ── Message content ───────────────────────────────────────────────────────

    direction    = fields.Selection([
        ('out', 'Outbound'),
        ('in',  'Inbound'),
    ], string='Direction', required=True, index=True)

    message_text = fields.Text(string='Message')
    has_media    = fields.Boolean(string='Has Attachment', default=False)
    media_type   = fields.Char(string='Media Type')   # document / image / audio / video

    # ── Evolution tracking ────────────────────────────────────────────────────

    wa_message_id = fields.Char(
        string='WA Message ID', index=True,
        help='Message key.id returned by Evolution API — used to match delivery/read webhooks'
    )

    delivery_status = fields.Selection([
        ('pending',   'Pending'),
        ('sent',      'Sent'),
        ('delivered', 'Delivered'),
        ('read',      'Read'),
        ('failed',    'Failed'),
    ], string='Delivery Status', default='pending', index=True)

    # ── Timestamps ────────────────────────────────────────────────────────────

    sent_at      = fields.Datetime(string='Sent At',      default=fields.Datetime.now)
    delivered_at = fields.Datetime(string='Delivered At')
    read_at      = fields.Datetime(string='Read At')

    # ── Reply tracking ────────────────────────────────────────────────────────

    replied    = fields.Boolean(string='Got Reply', default=False, index=True)
    reply_at   = fields.Datetime(string='First Reply At')
    reply_text = fields.Text(string='First Reply Text')

    # ── Computed ──────────────────────────────────────────────────────────────

    display_name = fields.Char(compute='_compute_display_name', store=False)

    @api.depends('partner_id', 'lead_id', 'phone', 'direction')
    def _compute_display_name(self):
        for rec in self:
            name = (
                rec.partner_id.name or
                rec.lead_id.name or
                rec.phone
            )
            arrow = '→' if rec.direction == 'out' else '←'
            rec.display_name = f"{arrow} {name}"

    # ── Class method: update status from Evolution webhook ───────────────────

    @api.model
    def update_delivery_status(self, wa_message_id, status):
        """
        Called by the Evolution webhook handler when a MESSAGES_UPDATE event arrives.

        status values from Evolution: PENDING → SENT → DELIVERED → READ
        """
        if not wa_message_id:
            return

        STATUS_MAP = {
            'PENDING':   'pending',
            'SENT':      'sent',
            'DELIVERED': 'delivered',
            'READ':      'read',
            'ERROR':     'failed',
            'PLAYED':    'read',    # voice messages
        }
        odoo_status = STATUS_MAP.get(status.upper(), None)
        if not odoo_status:
            _logger.debug(f"[WA Log] Unknown status from Evolution: {status}")
            return

        logs = self.search([('wa_message_id', '=', wa_message_id)], limit=5)
        if not logs:
            _logger.debug(f"[WA Log] No log found for wa_message_id={wa_message_id}")
            return

        now = fields.Datetime.now()
        vals = {'delivery_status': odoo_status}
        if odoo_status == 'delivered' and not logs[0].delivered_at:
            vals['delivered_at'] = now
        if odoo_status == 'read' and not logs[0].read_at:
            vals['read_at'] = now

        logs.write(vals)
        _logger.info(f"[WA Log] Updated {len(logs)} log(s) id={wa_message_id} → {odoo_status}")

    @api.model
    def mark_replied(self, phone, reply_text=''):
        """
        Called when an inbound message arrives on a phone that has outbound logs.
        Marks the most recent unreplied outbound log as replied.
        """
        if not phone:
            return
        clean = phone.replace('+', '').replace(' ', '').strip()
        log = self.search([
            ('phone', '=', clean),
            ('direction', '=', 'out'),
            ('replied', '=', False),
        ], order='sent_at desc', limit=1)
        if log:
            log.write({
                'replied':    True,
                'reply_at':   fields.Datetime.now(),
                'reply_text': reply_text[:500] if reply_text else '',
            })
            _logger.info(f"[WA Log] Marked reply for phone={clean} log #{log.id}")
