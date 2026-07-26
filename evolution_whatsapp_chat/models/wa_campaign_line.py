# -*- coding: utf-8 -*-
"""
Campaign Line - Individual recipient tracking
"""
import hashlib
import logging

from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


def campaign_line_body_hash(text):
    """Canonical SHA256 of the exact outbound text (no semantic rewriting)."""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


class WhatsAppCampaignLine(models.Model):
    _name = 'wa.campaign.line'
    _description = 'WA Campaign Recipient'
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

    # P5E: immutable render snapshot (authoring = campaign.message → freeze once)
    rendered_body = fields.Text(
        string='Frozen Rendered Body',
        help='Immutable snapshot used for Hub/shadow admit and send. '
             'Authoring source remains campaign.message; freeze once before send.',
    )
    rendered_body_hash = fields.Char(
        string='Rendered Body Hash',
        index=True,
        help='SHA256 of rendered_body',
    )
    rendered_at = fields.Datetime(
        string='Rendered At',
        readonly=True,
    )
    rendered_locked = fields.Boolean(
        string='Rendered Locked',
        default=False,
        index=True,
        help='When True, processor must not re-render from campaign.message',
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
        string='WA Message ID',
        help='Evolution API message ID'
    )

    queue_id = fields.Many2one(
        'integration.outbound.queue', string='Queue Record',
        help='Link to outbound queue entry'
    )

    # Phase 5A: soft Hub refs (projection; no hard FK to avoid module coupling)
    hub_message_id = fields.Integer(
        string='Hub Message ID',
        index=True,
        help='whatsapp.message id when sent via Hub unified outbound',
    )
    hub_outbound_id = fields.Integer(
        string='Hub Outbound Job ID',
        index=True,
        help='whatsapp.outbound.message id for Hub Campaign path',
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

    def service_freeze_rendered_body(self):
        """
        Freeze Campaign template render into an immutable line snapshot (P5E).

        Authoring source: campaign.message (+ personalise placeholders).
        If already locked with a valid snapshot, return it unchanged (idempotent).
        """
        self.ensure_one()
        if (
            self.rendered_locked
            and self.rendered_body is not False
            and self.rendered_body is not None
            and self.rendered_body_hash
        ):
            return self.rendered_body

        campaign = self.campaign_id
        if not campaign:
            raise ValueError("Campaign line has no campaign")
        body = campaign._render_message_for_line(self)
        body_hash = campaign_line_body_hash(body)
        self.write(
            {
                "rendered_body": body,
                "rendered_body_hash": body_hash,
                "rendered_at": fields.Datetime.now(),
                "rendered_locked": True,
                "message": body,
            }
        )
        return body

    def get_frozen_or_freeze_body(self):
        """Return frozen body, freezing once if needed."""
        self.ensure_one()
        return self.service_freeze_rendered_body()

    def action_admin_rerender_for_hub(self):
        """
        Admin: unlock+re-freeze from campaign.message only before Hub admission.

        Blocked when hub_message_id / hub_outbound_id exist (immutable logical payload).
        """
        for line in self:
            if line.hub_message_id or line.hub_outbound_id:
                raise UserError(
                    "Cannot re-render line %s: Hub message/job already exists "
                    "(immutable after Hub admission)."
                    % line.id
                )
            if line.wa_message_id:
                raise UserError(
                    "Cannot re-render line %s: provider ID already set."
                    % line.id
                )
            line.write(
                {
                    "rendered_locked": False,
                    "rendered_body": False,
                    "rendered_body_hash": False,
                    "rendered_at": False,
                }
            )
            line.service_freeze_rendered_body()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Re-render for Hub",
                "message": f"Re-froze {len(self)} line(s) from campaign.message",
                "type": "success",
                "sticky": False,
            },
        }

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
        """Retry sending this message (Hub-safe: no new business_key)."""
        for line in self:
            if line.status == 'failed' and line._hub_retry_allowed():
                line.write({
                    'status': 'pending',
                    'error_msg': False,
                })
        return True

    def _hub_retry_allowed(self):
        """
        True if this failed line may be reset to pending.

        Provider-accepted Hub jobs must not be resent under a new identity.
        Pending/processing Hub jobs should not be force-reset to create duplicates.
        """
        self.ensure_one()
        if not self.hub_outbound_id and not self.hub_message_id:
            return True  # legacy line
        if "whatsapp.outbound.message" not in self.env:
            return True
        Out = self.env["whatsapp.outbound.message"].sudo()
        job = Out.browse(self.hub_outbound_id) if self.hub_outbound_id else Out.browse()
        if not job and self.hub_message_id:
            job = Out.search(
                [("message_id", "=", self.hub_message_id)], limit=1
            )
        if not job:
            return True
        evo = (job.evolution_message_id or "").strip()
        if job.state == "sent" or evo:
            return False
        if job.state in ("pending", "processing"):
            return False
        # failed/cancelled without provider id → reuse same business_key on re-admit
        if job.state == "failed":
            job.write(
                {
                    "state": "pending",
                    "next_retry_at": False,
                    "error_message": False,
                    "retry_count": 0,
                }
            )
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
        <p><b>📱 WA Campaign Message ({status})</b></p>
        <p>Campaign: {self.campaign_id.name}</p>
        <p>Phone: {self.phone}</p>
        <div style="border-left: 3px solid #25D366; padding-left: 10px; margin-top: 10px;">
            <pre>{message}</pre>
        </div>
        """
        if self.lead_id:
            self.lead_id.message_post(
                body=body,
                subject=f"WA Campaign: {self.campaign_id.name}",
                message_type='comment',
                subtype_xmlid='mail.mt_note',
            )
        elif self.partner_id:
            self.partner_id.message_post(
                body=body,
                subject=f"WA Campaign: {self.campaign_id.name}",
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
