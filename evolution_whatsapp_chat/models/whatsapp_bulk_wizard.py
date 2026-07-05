# -*- coding: utf-8 -*-
"""
whatsapp.bulk.wizard  — send WhatsApp messages to many contacts at once.

Usage:
 - Select multiple res.partner records in list view → Action → Send WhatsApp
 - Select multiple crm.lead records in list view  → Action → Send WhatsApp
 - The wizard lets you pick a template / write a custom message,
   optionally schedule the batch, then queues every message via
   integration.outbound.queue for rate-limited delivery.
"""
import base64
import logging
import mimetypes
from datetime import timedelta

from odoo import models, fields, api
from odoo.exceptions import UserError

from .discuss_channel import _send_via_evolution, _evo_config, _create_wa_log
from .res_partner import _normalise_phone


def _mime_to_evo_type(mimetype):
    """Map a MIME type to Evolution API mediatype string."""
    if not mimetype:
        return 'document'
    if mimetype.startswith('image/'):
        return 'image'
    if mimetype.startswith('video/'):
        return 'video'
    if mimetype.startswith('audio/'):
        return 'audio'
    return 'document'


def _send_media_evolution(env, phone, att_info, caption=''):
    """Send a media attachment via Evolution API /message/sendMedia."""
    import requests as _requests
    cfg = _evo_config(env)
    if not cfg['key']:
        return False, 'Evolution not configured'
    clean = phone.replace('+', '').replace(' ', '').strip()
    endpoint = f"{cfg['url']}/message/sendMedia/{cfg['instance']}"
    payload = {
        'number':    clean,
        'mediatype': att_info['type'],
        'media':     att_info['url'],
        'caption':   caption or att_info['name'],
    }
    try:
        resp = _requests.post(endpoint, json=payload,
                              headers={'apikey': cfg['key'], 'Content-Type': 'application/json'},
                              timeout=20)
        return resp.ok, resp.text[:200]
    except Exception as e:
        return False, str(e)

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Batch summary line — one per contact
# ---------------------------------------------------------------------------

class WhatsappBulkLine(models.TransientModel):
    _name        = 'whatsapp.bulk.line'
    _description = 'WhatsApp Bulk Send — Contact Line'

    wizard_id    = fields.Many2one('whatsapp.bulk.wizard', ondelete='cascade')
    partner_id   = fields.Many2one('res.partner', string='Contact')  # not required — leads may have no partner
    lead_id      = fields.Many2one('crm.lead',    string='Lead')
    display_name = fields.Char(string='Name', compute='_compute_display_name_line', store=False)
    phone        = fields.Char(string='Phone')
    message      = fields.Text(string='Message')

    @api.depends('partner_id', 'lead_id')
    def _compute_display_name_line(self):
        for line in self:
            if line.partner_id:
                line.display_name = line.partner_id.name
            elif line.lead_id:
                line.display_name = line.lead_id.partner_name or line.lead_id.name
            else:
                line.display_name = '—'
    status     = fields.Selection([
        ('pending', 'Pending'),
        ('sent',    'Sent'),
        ('queued',  'Queued'),
        ('skip',    'Skipped — no phone'),
        ('error',   'Error'),
    ], default='pending', readonly=True)
    error_msg  = fields.Char(string='Error', readonly=True)


# ---------------------------------------------------------------------------
# Main wizard
# ---------------------------------------------------------------------------

class WhatsappBulkWizard(models.TransientModel):
    _name        = 'whatsapp.bulk.wizard'
    _description = 'Send WhatsApp to Multiple Contacts'

    # ── Recipients ────────────────────────────────────────────────────────────

    line_ids = fields.One2many(
        'whatsapp.bulk.line', 'wizard_id',
        string='Recipients'
    )

    recipient_count = fields.Integer(
        compute='_compute_counts', string='Total'
    )
    valid_count = fields.Integer(
        compute='_compute_counts', string='With Phone'
    )
    skip_count = fields.Integer(
        compute='_compute_counts', string='No Phone'
    )

    @api.depends('line_ids', 'line_ids.phone')
    def _compute_counts(self):
        for wiz in self:
            wiz.recipient_count = len(wiz.line_ids)
            wiz.valid_count     = len(wiz.line_ids.filtered(lambda l: l.phone))
            wiz.skip_count      = len(wiz.line_ids.filtered(lambda l: not l.phone))

    # ── Message ───────────────────────────────────────────────────────────────

    template_id = fields.Many2one(
        'evo.wa.template', string='Template',
        domain=[('active', '=', True)],
    )

    message = fields.Text(
        string='Message', required=True,
        help='Use {name}, {first}, {company} as placeholders'
    )

    personalise = fields.Boolean(
        string='Personalise per Contact',
        default=True,
        help='If enabled, {name} and {company} are replaced for each contact individually'
    )

    # ── Delivery ──────────────────────────────────────────────────────────────

    send_mode = fields.Selection([
        ('now',       'Send Now — direct via Evolution API'),
        ('queue',     'Queue — processed by cron job (every 15 min)'),
        ('scheduled', 'Schedule for Later'),
    ], string='Send Mode', default='now', required=True)

    scheduled_at = fields.Datetime(
        string='Send At',
        help='When to start sending this batch (used when Send Mode = Schedule)'
    )

    delay_between = fields.Integer(
        string='Delay Between Messages (seconds)',
        default=2,
        help='Seconds to wait between each message when sending directly'
    )

    # ── Attachment ────────────────────────────────────────────────────────────

    attachment_ids = fields.Many2many(
        'ir.attachment',
        'whatsapp_bulk_wizard_attachment_rel',
        'wizard_id', 'attachment_id',
        string='Attachments',
        help='Files to send with the message (PDF, image, etc.)'
    )

    # ── Results ───────────────────────────────────────────────────────────────

    sent_count   = fields.Integer(readonly=True, default=0)
    queued_count = fields.Integer(readonly=True, default=0)
    error_count  = fields.Integer(readonly=True, default=0)
    done         = fields.Boolean(readonly=True, default=False)

    # ── Template auto-fill ────────────────────────────────────────────────────

    @api.onchange('template_id')
    def _onchange_template_id(self):
        if self.template_id:
            self.message = self.template_id.body or ''

    # ── Pre-fill lines with personal messages on send ─────────────────────────

    def _render_message(self, template_body, partner=None, lead=None):
        """Render a message body for a single partner/lead."""
        body = template_body or ''
        if not self.personalise:
            return body

        contact_name = ''
        company_name = ''
        if lead:
            contact_name = lead.partner_name or (lead.partner_id.name if lead.partner_id else '') or ''
            company_name = lead.partner_id.company_name if lead.partner_id else ''
        elif partner:
            contact_name = partner.name or ''
            company_name = (
                partner.company_name
                or (partner.parent_id.name if partner.parent_id else '')
                or ''
            )

        first_name = contact_name.split()[0] if contact_name else 'Hiring Manager'

        body = body.replace('{name}',    contact_name or 'Hiring Manager')
        body = body.replace('{first}',   first_name)
        body = body.replace('{company}', company_name or 'your company')
        return body

    # ── Default get: populate lines from active_ids context ──────────────────

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        ctx = self.env.context
        active_model = ctx.get('active_model', '')
        active_ids   = ctx.get('active_ids', [])

        if not active_ids:
            return res

        lines = []

        if active_model == 'res.partner':
            for partner in self.env['res.partner'].browse(active_ids):
                phone_raw = getattr(partner, 'mobile', None) or partner.phone or ''
                lines.append((0, 0, {
                    'partner_id': partner.id,
                    'phone':      _normalise_phone(phone_raw),
                }))

        elif active_model == 'crm.lead':
            for lead in self.env['crm.lead'].browse(active_ids):
                partner   = lead.partner_id
                phone_raw = lead.phone or lead.mobile or (
                    (getattr(partner, 'mobile', None) or partner.phone)
                    if partner else ''
                ) or ''
                vals = {
                    'lead_id': lead.id,
                    'phone':   _normalise_phone(phone_raw),
                }
                # Only set partner_id if the lead actually has one
                if partner:
                    vals['partner_id'] = partner.id
                lines.append((0, 0, vals))

        if lines:
            res['line_ids'] = lines
        return res

    # ── Attachment helpers ────────────────────────────────────────────────────

    def _get_attachment_info(self):
        """
        Return list of dicts with {url, type, name} for each attachment.
        The URL is the Odoo download URL — Evolution will fetch it.
        """
        base_url = self.env['ir.config_parameter'].sudo().get_param(
            'web.base.url', 'http://localhost:8069')
        result = []
        for att in self.attachment_ids:
            mimetype  = att.mimetype or mimetypes.guess_type(att.name or '')[0] or 'application/octet-stream'
            evo_type  = _mime_to_evo_type(mimetype)
            # Build a public download URL (works because auth='public' on /web/content)
            url = f"{base_url}/web/content/{att.id}?download=true"
            result.append({'url': url, 'type': evo_type, 'name': att.name or 'file'})
        return result

    # ── Send action ───────────────────────────────────────────────────────────

    def action_send_bulk(self):
        """Send / queue all messages."""
        self.ensure_one()

        if not self.message or not self.message.strip():
            raise UserError("Message cannot be empty.")

        valid_lines = self.line_ids.filtered(lambda l: l.phone)
        if not valid_lines:
            raise UserError("No recipients have a valid phone number.")

        ICP = self.env['ir.config_parameter'].sudo()
        evo_url      = ICP.get_param('integration_bridge.evolution_url',     'http://127.0.0.1:8099')
        evo_key      = ICP.get_param('integration_bridge.evolution_key',      '')
        evo_instance = ICP.get_param('integration_bridge.evolution_instance', 'sabry')

        sent   = 0
        queued = 0
        errors = 0

        # Build public attachment URLs if any
        attachment_info = self._get_attachment_info()

        for line in self.line_ids:
            if not line.phone:
                line.status = 'skip'
                continue

            # Render personalised message for this contact
            rendered = self._render_message(
                self.message,
                partner=line.partner_id or None,
                lead=line.lead_id or None,
            )
            line.message = rendered

            related_model  = 'crm.lead' if line.lead_id else ('res.partner' if line.partner_id else '')
            related_res_id = line.lead_id.id if line.lead_id else (line.partner_id.id if line.partner_id else 0)

            if self.send_mode == 'now':
                # Send text first
                success, resp, wa_msg_id = _send_via_evolution(
                    self.env, line.phone, rendered,
                    partner_id=line.partner_id.id if line.partner_id else None,
                    lead_id=line.lead_id.id if line.lead_id else None,
                )
                if success:
                    # Send each attachment as a separate media message
                    for att in attachment_info:
                        ok, _r = _send_media_evolution(self.env, line.phone, att, '')
                        _create_wa_log(
                            self.env, line.phone, att['name'], None,
                            partner_id=line.partner_id.id if line.partner_id else None,
                            lead_id=line.lead_id.id if line.lead_id else None,
                            has_media=True, media_type=att['type'], delivery_status='sent',
                        )
                    line.status = 'sent'
                    sent += 1
                    self._post_chatter(line, rendered, 'sent')
                else:
                    line.status = 'error'
                    line.error_msg = resp[:200]
                    errors += 1

            else:  # queue or scheduled
                scheduled_dt = self.scheduled_at if self.send_mode == 'scheduled' else False
                try:
                    # Queue text message
                    queue_rec = None
                    if rendered.strip():
                        endpoint = f"{evo_url}/message/sendText/{evo_instance}"
                        queue_rec = self.env['integration.outbound.queue'].sudo().create_outbound_message(
                            name=f"Bulk WA → {line.phone}",
                            platform='evolution',
                            endpoint_url=endpoint,
                            payload={'number': line.phone, 'text': rendered, 'options': {'delay': 1200}},
                            headers={'apikey': evo_key, 'Content-Type': 'application/json'},
                            related_model=related_model,
                            related_res_id=related_res_id,
                            priority=5,
                            scheduled_at=scheduled_dt,
                        )
                        # Pre-create log in 'pending' state — updated when queue sends
                        _create_wa_log(
                            self.env, line.phone, rendered, None,
                            partner_id=line.partner_id.id if line.partner_id else None,
                            lead_id=line.lead_id.id if line.lead_id else None,
                            queue_id=queue_rec.id if queue_rec else None,
                            delivery_status='pending',
                        )
                    # Queue each attachment
                    for att in attachment_info:
                        endpoint = f"{evo_url}/message/sendMedia/{evo_instance}"
                        self.env['integration.outbound.queue'].sudo().create_outbound_message(
                            name=f"Bulk WA Media → {line.phone}",
                            platform='evolution',
                            endpoint_url=endpoint,
                            payload={
                                'number':    line.phone,
                                'mediatype': att['type'],
                                'media':     att['url'],
                                'caption':   att['name'],
                            },
                            headers={'apikey': evo_key, 'Content-Type': 'application/json'},
                            related_model=related_model,
                            related_res_id=related_res_id,
                            priority=4,
                            scheduled_at=scheduled_dt,
                        )
                    line.status = 'queued'
                    queued += 1
                    self._post_chatter(line, rendered, 'queued')
                except Exception as e:
                    line.status = 'error'
                    line.error_msg = str(e)[:200]
                    errors += 1

        self.write({'sent_count': sent, 'queued_count': queued,
                    'error_count': errors, 'done': True})

        return {
            'type':  'ir.actions.client',
            'tag':   'display_notification',
            'params': {
                'title':   'WhatsApp Bulk Send',
                'message': (
                    f"Done: {sent} sent directly, {queued} queued"
                    + (f", {errors} errors" if errors else "")
                ),
                'type':    'success' if not errors else 'warning',
                'sticky':  True,
            },
        }

    def _post_chatter(self, line, text, status):
        """Post a note on the lead or partner chatter."""
        body = (
            f"<div style='padding:8px;border-left:3px solid #25D366'>"
            f"<b>📱 WhatsApp {status} → {line.phone}</b><br/>"
            f"<div style='white-space:pre-wrap;margin-top:4px;font-size:12px'>{text[:300]}</div>"
            f"</div>"
        )
        if line.lead_id:
            line.lead_id.message_post(body=body, message_type='comment',
                                      subtype_xmlid='mail.mt_note')
        elif line.partner_id:
            line.partner_id.message_post(body=body, message_type='comment',
                                         subtype_xmlid='mail.mt_note')
