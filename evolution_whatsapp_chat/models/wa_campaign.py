# -*- coding: utf-8 -*-
"""
WhatsApp Campaign Management

Persistent campaigns with full status tracking, anti-duplicate logic,
and comprehensive reporting.
"""
import logging
from datetime import datetime, timedelta
from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class WhatsAppCampaign(models.Model):
    _name = 'wa.campaign'
    _description = 'WhatsApp Campaign'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'

    # ── Basic Info ────────────────────────────────────────────────────────────

    name = fields.Char(
        string='Campaign Name', required=True, tracking=True,
        help='Internal name for this campaign'
    )

    description = fields.Text(
        string='Description',
        help='Purpose and details of this campaign'
    )

    state = fields.Selection([
        ('draft',     'Draft'),
        ('scheduled', 'Scheduled'),
        ('running',   'Running'),
        ('paused',    'Paused'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', required=True, tracking=True)

    # ── Message Template ──────────────────────────────────────────────────────

    template_id = fields.Many2one(
        'evo.wa.template', string='Message Template',
        domain=[('active', '=', True)],
        help='Select a template to use'
    )

    message = fields.Text(
        string='Message Content', required=True, tracking=True,
        help='Use placeholders: {name}, {first}, {company}, {phone}'
    )

    personalise = fields.Boolean(
        string='Personalise per Contact', default=True,
        help='Replace placeholders with contact-specific values'
    )

    attachment_ids = fields.Many2many(
        'ir.attachment', 'wa_campaign_attachment_rel',
        'campaign_id', 'attachment_id',
        string='Attachments',
        help='Media files to send with each message'
    )

    # ── Recipients ────────────────────────────────────────────────────────────

    campaign_line_ids = fields.One2many(
        'wa.campaign.line', 'campaign_id',
        string='Campaign Recipients'
    )

    # ── Targeting ─────────────────────────────────────────────────────────────

    target_model = fields.Selection([
        ('res.partner', 'Contacts'),
        ('crm.lead',    'CRM Leads'),
    ], string='Target', default='res.partner', required=True)

    partner_ids = fields.Many2many(
        'res.partner', 'wa_campaign_partner_rel',
        'campaign_id', 'partner_id',
        string='Selected Contacts'
    )

    lead_ids = fields.Many2many(
        'crm.lead', 'wa_campaign_lead_rel',
        'campaign_id', 'lead_id',
        string='Selected Leads'
    )

    filter_domain = fields.Char(
        string='Filter Domain',
        help='Optional domain filter for automatic contact selection'
    )

    # ── Scheduling ────────────────────────────────────────────────────────────

    send_mode = fields.Selection([
        ('immediate', 'Send Immediately'),
        ('scheduled', 'Schedule for Specific Time'),
        ('queue',     'Add to Queue (Rate Limited)'),
    ], string='Send Mode', default='queue', required=True)

    scheduled_date = fields.Datetime(
        string='Scheduled Send Time',
        help='When to start sending messages'
    )

    delay_between = fields.Integer(
        string='Delay Between Messages (seconds)',
        default=5,
        help='Seconds between each message to avoid rate limits'
    )

    # ── Anti-Duplicate Settings ───────────────────────────────────────────────

    check_duplicates = fields.Boolean(
        string='Prevent Duplicate Sends', default=True,
        help='Skip contacts who already received this campaign'
    )

    min_days_between = fields.Integer(
        string='Minimum Days Between Campaigns',
        default=0,
        help='Skip contacts contacted in last X days (0 = no check)'
    )

    # ── Statistics (computed) ─────────────────────────────────────────────────

    total_count = fields.Integer(
        string='Total Recipients', compute='_compute_stats', store=True
    )
    pending_count = fields.Integer(
        string='Pending', compute='_compute_stats', store=True
    )
    sent_count = fields.Integer(
        string='Sent', compute='_compute_stats', store=True
    )
    delivered_count = fields.Integer(
        string='Delivered', compute='_compute_stats', store=True
    )
    read_count = fields.Integer(
        string='Read', compute='_compute_stats', store=True
    )
    failed_count = fields.Integer(
        string='Failed', compute='_compute_stats', store=True
    )
    skipped_count = fields.Integer(
        string='Skipped', compute='_compute_stats', store=True
    )

    success_rate = fields.Float(
        string='Success Rate (%)', compute='_compute_stats', store=True
    )
    read_rate = fields.Float(
        string='Read Rate (%)', compute='_compute_stats', store=True
    )

    # ── Dates ─────────────────────────────────────────────────────────────────

    start_date = fields.Datetime(
        string='Started At', readonly=True, tracking=True
    )
    completed_date = fields.Datetime(
        string='Completed At', readonly=True, tracking=True
    )

    # ── Progress ──────────────────────────────────────────────────────────────

    progress = fields.Float(
        string='Progress (%)', compute='_compute_progress'
    )

    @api.depends('campaign_line_ids.status')
    def _compute_stats(self):
        for campaign in self:
            lines = campaign.campaign_line_ids
            campaign.total_count     = len(lines)
            campaign.pending_count   = len(lines.filtered(lambda l: l.status == 'pending'))
            campaign.sent_count      = len(lines.filtered(lambda l: l.status in ['sent', 'delivered', 'read']))
            campaign.delivered_count = len(lines.filtered(lambda l: l.status in ['delivered', 'read']))
            campaign.read_count      = len(lines.filtered(lambda l: l.status == 'read'))
            campaign.failed_count    = len(lines.filtered(lambda l: l.status == 'failed'))
            campaign.skipped_count   = len(lines.filtered(lambda l: l.status == 'skipped'))

            if campaign.total_count > 0:
                campaign.success_rate = (campaign.sent_count / campaign.total_count) * 100
                campaign.read_rate = (campaign.read_count / campaign.sent_count * 100) if campaign.sent_count > 0 else 0
            else:
                campaign.success_rate = 0
                campaign.read_rate = 0

    @api.depends('total_count', 'sent_count', 'failed_count', 'skipped_count')
    def _compute_progress(self):
        for campaign in self:
            processed = campaign.sent_count + campaign.failed_count + campaign.skipped_count
            campaign.progress = (processed / campaign.total_count * 100) if campaign.total_count > 0 else 0

    # ── Template auto-fill ────────────────────────────────────────────────────

    @api.onchange('template_id')
    def _onchange_template_id(self):
        if self.template_id:
            self.message = self.template_id.body or ''

    # ── Actions ───────────────────────────────────────────────────────────────

    def action_load_recipients(self):
        """Open wizard to select recipients."""
        self.ensure_one()
        return {
            'name': 'Select Recipients',
            'type': 'ir.actions.act_window',
            'res_model': 'wa.campaign.recipient.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_campaign_id': self.id,
                'default_target_model': self.target_model,
            }
        }

    def action_generate_lines(self):
        """Generate campaign lines from selected contacts/leads."""
        self.ensure_one()
        if self.state not in ['draft', 'scheduled']:
            raise UserError("Can only generate lines for draft or scheduled campaigns.")

        # Clear existing lines
        self.campaign_line_ids.unlink()

        lines = []
        from .res_partner import _normalise_phone

        if self.target_model == 'res.partner':
            contacts = self.partner_ids
            # Apply domain filter if provided
            if self.filter_domain:
                try:
                    domain = eval(self.filter_domain)
                    contacts = contacts.filtered_domain(domain)
                except Exception as e:
                    _logger.warning(f"Invalid domain filter: {e}")

            for partner in contacts:
                phone = _normalise_phone(getattr(partner, 'mobile', None) or partner.phone or '')
                if not phone and self.check_duplicates:
                    continue  # Skip contacts without phone

                # Check if already sent
                if self.check_duplicates:
                    if self._already_sent_to_partner(partner):
                        lines.append((0, 0, {
                            'partner_id': partner.id,
                            'phone': phone,
                            'status': 'skipped',
                            'error_msg': 'Already received this campaign',
                        }))
                        continue

                # Check minimum days between campaigns
                if self.min_days_between > 0:
                    if self._contacted_recently(partner):
                        lines.append((0, 0, {
                            'partner_id': partner.id,
                            'phone': phone,
                            'status': 'skipped',
                            'error_msg': f'Contacted in last {self.min_days_between} days',
                        }))
                        continue

                lines.append((0, 0, {
                    'partner_id': partner.id,
                    'phone': phone,
                    'status': 'pending',
                }))

        elif self.target_model == 'crm.lead':
            leads = self.lead_ids
            if self.filter_domain:
                try:
                    domain = eval(self.filter_domain)
                    leads = leads.filtered_domain(domain)
                except Exception as e:
                    _logger.warning(f"Invalid domain filter: {e}")

            for lead in leads:
                partner = lead.partner_id
                phone = _normalise_phone(
                    lead.phone or lead.mobile or
                    (getattr(partner, 'mobile', None) or partner.phone if partner else '')
                    or ''
                )
                if not phone and self.check_duplicates:
                    continue

                # Check duplicates
                if self.check_duplicates:
                    if self._already_sent_to_lead(lead):
                        lines.append((0, 0, {
                            'lead_id': lead.id,
                            'partner_id': partner.id if partner else False,
                            'phone': phone,
                            'status': 'skipped',
                            'error_msg': 'Already received this campaign',
                        }))
                        continue

                # Check recent contact
                if self.min_days_between > 0 and partner:
                    if self._contacted_recently(partner):
                        lines.append((0, 0, {
                            'lead_id': lead.id,
                            'partner_id': partner.id,
                            'phone': phone,
                            'status': 'skipped',
                            'error_msg': f'Contacted in last {self.min_days_between} days',
                        }))
                        continue

                lines.append((0, 0, {
                    'lead_id': lead.id,
                    'partner_id': partner.id if partner else False,
                    'phone': phone,
                    'status': 'pending',
                }))

        self.campaign_line_ids = lines
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'message': f'{len(lines)} recipients loaded successfully',
                'type': 'success',
                'sticky': False,
            }
        }

    def _already_sent_to_partner(self, partner):
        """Check if this partner already received this campaign."""
        return self.env['wa.campaign.line'].search_count([
            ('campaign_id', '=', self.id),
            ('partner_id', '=', partner.id),
            ('status', 'in', ['sent', 'delivered', 'read']),
        ]) > 0

    def _already_sent_to_lead(self, lead):
        """Check if this lead already received this campaign."""
        return self.env['wa.campaign.line'].search_count([
            ('campaign_id', '=', self.id),
            ('lead_id', '=', lead.id),
            ('status', 'in', ['sent', 'delivered', 'read']),
        ]) > 0

    def _contacted_recently(self, partner):
        """Check if partner was contacted in last X days."""
        if self.min_days_between <= 0:
            return False
        cutoff = fields.Datetime.now() - timedelta(days=self.min_days_between)
        return self.env['wa.message.log'].search_count([
            ('partner_id', '=', partner.id),
            ('direction', '=', 'out'),
            ('create_date', '>=', cutoff),
        ]) > 0

    def action_start_campaign(self):
        """Start sending campaign messages."""
        self.ensure_one()
        if self.state not in ['draft', 'scheduled', 'paused']:
            raise UserError("Can only start draft, scheduled or paused campaigns.")

        if not self.campaign_line_ids:
            raise UserError("No recipients loaded. Use 'Load Recipients' first.")

        pending = self.campaign_line_ids.filtered(lambda l: l.status == 'pending')
        if not pending:
            raise UserError("No pending messages to send.")

        self.write({
            'state': 'running',
            'start_date': fields.Datetime.now() if not self.start_date else self.start_date,
        })

        # Process in background
        self._process_campaign_queue()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'message': f'Campaign started! Processing {len(pending)} messages...',
                'type': 'success',
                'sticky': False,
            }
        }

    def _process_campaign_queue(self):
        """Process pending messages in campaign."""
        self.ensure_one()
        from .discuss_channel import _send_via_evolution, _create_wa_log
        from .whatsapp_bulk_wizard import _send_media_evolution, _mime_to_evo_type
        import time

        pending_lines = self.campaign_line_ids.filtered(lambda l: l.status == 'pending')

        ICP = self.env['ir.config_parameter'].sudo()
        evo_url = ICP.get_param('integration_bridge.evolution_url', 'http://127.0.0.1:8099')
        evo_key = ICP.get_param('integration_bridge.evolution_key', '')
        evo_instance = ICP.get_param('integration_bridge.evolution_instance', 'sabry')

        # Get attachment info
        attachment_info = self._get_attachment_info()

        for line in pending_lines:
            if self.state == 'paused':
                break

            # Render personalised message
            rendered = self._render_message_for_line(line)
            line.message = rendered

            if self.send_mode == 'immediate':
                # Send directly
                success, resp, wa_msg_id = _send_via_evolution(
                    self.env, line.phone, rendered,
                    partner_id=line.partner_id.id if line.partner_id else None,
                    lead_id=line.lead_id.id if line.lead_id else None,
                )
                if success:
                    line.write({
                        'status': 'sent',
                        'sent_date': fields.Datetime.now(),
                        'wa_message_id': wa_msg_id,
                    })
                    # Send attachments
                    for att in attachment_info:
                        _send_media_evolution(self.env, line.phone, att, '')
                    # Post to chatter
                    line._post_to_chatter(rendered, 'sent')
                else:
                    line.write({
                        'status': 'failed',
                        'error_msg': resp[:200],
                    })
                # Delay between messages
                if self.delay_between > 0:
                    time.sleep(self.delay_between)

            else:  # queue or scheduled
                # Add to outbound queue
                scheduled_dt = self.scheduled_date if self.send_mode == 'scheduled' else False
                try:
                    endpoint = f"{evo_url}/message/sendText/{evo_instance}"
                    queue_rec = self.env['integration.outbound.queue'].sudo().create_outbound_message(
                        name=f"Campaign '{self.name}' → {line.phone}",
                        platform='evolution',
                        endpoint_url=endpoint,
                        payload={'number': line.phone, 'text': rendered, 'options': {'delay': 1000}},
                        headers={'apikey': evo_key, 'Content-Type': 'application/json'},
                        related_model=line.lead_id._name if line.lead_id else (line.partner_id._name if line.partner_id else ''),
                        related_res_id=line.lead_id.id if line.lead_id else (line.partner_id.id if line.partner_id else 0),
                        priority=5,
                        scheduled_at=scheduled_dt,
                    )
                    line.write({
                        'status': 'sent',
                        'sent_date': fields.Datetime.now(),
                        'queue_id': queue_rec.id,
                    })
                    # Queue attachments
                    for att in attachment_info:
                        self.env['integration.outbound.queue'].sudo().create_outbound_message(
                            name=f"Campaign Media → {line.phone}",
                            platform='evolution',
                            endpoint_url=f"{evo_url}/message/sendMedia/{evo_instance}",
                            payload={'number': line.phone, 'mediatype': att['type'],
                                     'media': att['url'], 'caption': att['name']},
                            headers={'apikey': evo_key, 'Content-Type': 'application/json'},
                            related_model=line.lead_id._name if line.lead_id else (line.partner_id._name if line.partner_id else ''),
                            related_res_id=line.lead_id.id if line.lead_id else (line.partner_id.id if line.partner_id else 0),
                            priority=4,
                            scheduled_at=scheduled_dt,
                        )
                except Exception as e:
                    line.write({
                        'status': 'failed',
                        'error_msg': str(e)[:200],
                    })

        # Check if campaign completed
        if not self.campaign_line_ids.filtered(lambda l: l.status == 'pending'):
            self.write({
                'state': 'completed',
                'completed_date': fields.Datetime.now(),
            })

    def _render_message_for_line(self, line):
        """Render message with personalisation for a campaign line."""
        body = self.message or ''
        if not self.personalise:
            return body

        contact_name = ''
        company_name = ''
        if line.lead_id:
            contact_name = line.lead_id.partner_name or (line.partner_id.name if line.partner_id else '') or ''
            company_name = line.lead_id.partner_id.company_name if line.lead_id.partner_id else ''
        elif line.partner_id:
            contact_name = line.partner_id.name or ''
            company_name = (
                line.partner_id.company_name
                or (line.partner_id.parent_id.name if line.partner_id.parent_id else '')
                or ''
            )

        first_name = contact_name.split()[0] if contact_name else 'there'
        phone = line.phone or ''

        body = body.replace('{name}',    contact_name or 'there')
        body = body.replace('{first}',   first_name)
        body = body.replace('{company}', company_name or 'your company')
        body = body.replace('{phone}',   phone)
        return body

    def _get_attachment_info(self):
        """Return list of {url, type, name} for Evolution API."""
        from .whatsapp_bulk_wizard import _mime_to_evo_type
        import mimetypes
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', 'http://localhost:8069')
        result = []
        for att in self.attachment_ids:
            mimetype = att.mimetype or mimetypes.guess_type(att.name or '')[0] or 'application/octet-stream'
            result.append({
                'url':  f"{base_url}/web/content/{att.id}?download=true",
                'type': _mime_to_evo_type(mimetype),
                'name': att.name or 'file',
            })
        return result

    def action_pause_campaign(self):
        """Pause running campaign."""
        self.ensure_one()
        if self.state != 'running':
            raise UserError("Can only pause running campaigns.")
        self.state = 'paused'

    def action_resume_campaign(self):
        """Resume paused campaign."""
        self.ensure_one()
        if self.state != 'paused':
            raise UserError("Can only resume paused campaigns.")
        self.state = 'running'
        self._process_campaign_queue()

    def action_cancel_campaign(self):
        """Cancel campaign."""
        self.ensure_one()
        if self.state in ['completed', 'cancelled']:
            raise UserError("Campaign already finished.")
        self.state = 'cancelled'

    def action_retry_failed(self):
        """Retry all failed messages."""
        self.ensure_one()
        failed = self.campaign_line_ids.filtered(lambda l: l.status == 'failed')
        if not failed:
            raise UserError("No failed messages to retry.")
        failed.write({'status': 'pending', 'error_msg': False})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'message': f'{len(failed)} messages marked for retry',
                'type': 'success',
            }
        }

    def action_view_lines(self):
        """Open campaign lines view."""
        self.ensure_one()
        return {
            'name': f'Campaign Recipients: {self.name}',
            'type': 'ir.actions.act_window',
            'res_model': 'wa.campaign.line',
            'view_mode': 'list,form,pivot,graph',
            'domain': [('campaign_id', '=', self.id)],
            'context': {'default_campaign_id': self.id},
        }

    def action_clone_campaign(self):
        """Clone this campaign."""
        self.ensure_one()
        new_campaign = self.copy({
            'name': f"{self.name} (Copy)",
            'state': 'draft',
            'start_date': False,
            'completed_date': False,
            'campaign_line_ids': False,
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'wa.campaign',
            'res_id': new_campaign.id,
            'view_mode': 'form',
            'target': 'current',
        }
