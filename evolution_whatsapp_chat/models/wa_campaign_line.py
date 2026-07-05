# -*- coding: utf-8 -*-
"""
Campaign Line - Individual recipient tracking
"""
import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class WhatsAppCampaignLine(models.Model):
    _name = 'wa.campaign.line'
    _description = 'WhatsApp Campaign Recipient'
    _order = 'sent_date desc, create_date desc'

    # ── Relations ─────────────────────────────────────────────────────────────

    campaign_id = fields.Many2one(
        'wa.campaign', string='Campaign',
        required=True, ondelete='cascade', index=True
    )

    partner_id = fields.Many2one(
        'res.partner', string='Contact',
        index=True, ondelete='set null'
    )

    lead_id = fields.Many2one(
        'crm.lead', string='Lead',
        index=True, ondelete='set null'
    )

    # ── Message Data ──────────────────────────────────────────────────────────

    phone = fields.Char(
        string='Phone Number', required=True, index=True,
        help='Normalised phone number'
    )

    message = fields.Text(
        string='Personalised Message',
        help='Final message sent to this contact (after personalisation)'
    )

    # ── Status Tracking ───────────────────────────────────────────────────────

    status = fields.Selection([
        ('pending',   'Pending'),
        ('sent',      'Sent'),
        ('delivered', 'Delivered'),
        ('read',      'Read'),
        ('failed',    'Failed'),
        ('skipped',   'Skipped'),
    ], string='Status', default='pending', required=True, index=True)

    error_msg = fields.Char(
        string='Error Message',
        help='Reason for failure or skip'
    )

    # ── Evolution Integration ─────────────────────────────────────────────────

    wa_message_id = fields.Char(
        string='WhatsApp Message ID',
        help='Evolution API message ID'
    )

    queue_id = fields.Many2one(
        'integration.outbound.queue', string='Queue Record',
        help='Link to outbound queue entry'
    )

    # ── Timestamps ────────────────────────────────────────────────────────────

    sent_date = fields.Datetime(
        string='Sent At', readonly=True, index=True
    )

    delivered_date = fields.Datetime(
        string='Delivered At', readonly=True
    )

    read_date = fields.Datetime(
        string='Read At', readonly=True
    )

    # ── Display ───────────────────────────────────────────────────────────────

    recipient_name = fields.Char(
        string='Recipient', compute='_compute_recipient_name', store=True
    )

    @api.depends('partner_id', 'lead_id')
    def _compute_recipient_name(self):
        for line in self:
            if line.partner_id:
                line.recipient_name = line.partner_id.name
            elif line.lead_id:
                line.recipient_name = line.lead_id.partner_name or line.lead_id.name
            else:
                line.recipient_name = line.phone or '—'

    # ── Status Badge for UI ───────────────────────────────────────────────────

    status_badge = fields.Char(
        compute='_compute_status_badge', string='Status Badge'
    )

    @api.depends('status')
    def _compute_status_badge(self):
        badge_map = {
            'pending':   '⏳ Pending',
            'sent':      '✅ Sent',
            'delivered': '✓✓ Delivered',
            'read':      '👁 Read',
            'failed':    '❌ Failed',
            'skipped':   '⊘ Skipped',
        }
        for line in self:
            line.status_badge = badge_map.get(line.status, line.status)

    # ── Actions ───────────────────────────────────────────────────────────────

    def action_retry(self):
        """Retry sending this message."""
        for line in self:
            if line.status == 'failed':
                line.write({
                    'status': 'pending',
                    'error_msg': False,
                })
        return True

    def action_mark_sent(self):
        """Manually mark as sent."""
        self.write({
            'status': 'sent',
            'sent_date': fields.Datetime.now(),
        })

    def action_open_contact(self):
        """Open related contact or lead."""
        self.ensure_one()
        if self.partner_id:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'res.partner',
                'res_id': self.partner_id.id,
                'view_mode': 'form',
                'target': 'current',
            }
        elif self.lead_id:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'crm.lead',
                'res_id': self.lead_id.id,
                'view_mode': 'form',
                'target': 'current',
            }

    def _post_to_chatter(self, message, status):
        """Post sent message to partner/lead chatter."""
        self.ensure_one()
        body = f"""
        <p><b>📱 WhatsApp Campaign Message ({status})</b></p>
        <p>Campaign: {self.campaign_id.name}</p>
        <p>Phone: {self.phone}</p>
        <div style="border-left: 3px solid #25D366; padding-left: 10px; margin-top: 10px;">
            <pre>{message}</pre>
        </div>
        """
        if self.lead_id:
            self.lead_id.message_post(
                body=body,
                subject=f"WhatsApp Campaign: {self.campaign_id.name}",
                message_type='comment',
                subtype_xmlid='mail.mt_note',
            )
        elif self.partner_id:
            self.partner_id.message_post(
                body=body,
                subject=f"WhatsApp Campaign: {self.campaign_id.name}",
                message_type='comment',
                subtype_xmlid='mail.mt_note',
            )

    # ── Webhook Status Updates ────────────────────────────────────────────────

    def update_status_from_webhook(self, wa_msg_id, new_status):
        """
        Update line status based on Evolution webhook.
        Called from bridge controller when delivery status changes.
        """
        line = self.search([('wa_message_id', '=', wa_msg_id)], limit=1)
        if not line:
            return False

        status_map = {
            'delivered': 'delivered',
            'read': 'read',
            'failed': 'failed',
        }

        if new_status in status_map:
            vals = {'status': status_map[new_status]}
            if new_status == 'delivered':
                vals['delivered_date'] = fields.Datetime.now()
            elif new_status == 'read':
                vals['read_date'] = fields.Datetime.now()
            line.write(vals)
            _logger.info(f"[Campaign] Updated line {line.id} status to {new_status}")
            return True
        return False
