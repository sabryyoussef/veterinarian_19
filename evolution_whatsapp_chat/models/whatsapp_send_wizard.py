# -*- coding: utf-8 -*-
import mimetypes
import logging

from odoo import models, fields, api
from odoo.exceptions import UserError

from .discuss_channel import _send_via_evolution
from .res_partner import _normalise_phone

_logger = logging.getLogger(__name__)


class WhatsappSendWizard(models.TransientModel):
    _name        = 'whatsapp.send.wizard'
    _description = 'Send WhatsApp Message'

    # ── Context fields ────────────────────────────────────────────────────────

    partner_id = fields.Many2one(
        'res.partner', string='Contact',
        help='Contact this message is sent to'
    )

    lead_id = fields.Many2one(
        'crm.lead', string='CRM Lead',
        help='Lead this message is associated with'
    )

    # ── Message fields ────────────────────────────────────────────────────────

    phone = fields.Char(
        string='WhatsApp Number', required=True,
        help='Number in any format — will be normalised automatically'
    )

    template_id = fields.Many2one(
        'evo.wa.template', string='Template',
        domain=[('active', '=', True)],
        help='Select a template to pre-fill the message'
    )

    message = fields.Text(
        string='Message', required=True,
        help='The text to send via WhatsApp'
    )

    send_mode = fields.Selection([
        ('now',       'Send Now (direct)'),
        ('queue',     'Add to Outbound Queue'),
        ('scheduled', 'Schedule for Later'),
    ], string='Send Mode', default='now', required=True)

    scheduled_at = fields.Datetime(
        string='Send At',
        help='Date/time to send this message (only used when Send Mode = Schedule)'
    )

    attachment_ids = fields.Many2many(
        'ir.attachment',
        'whatsapp_wizard_attachment_rel',
        'wizard_id', 'attachment_id',
        string='Attachments',
        help='Files to send with the message (PDF, image, etc.)'
    )

    # ── Preview ───────────────────────────────────────────────────────────────

    preview = fields.Text(
        string='Preview', compute='_compute_preview', readonly=True
    )

    @api.depends('message')
    def _compute_preview(self):
        for rec in self:
            rec.preview = rec.message or ''

    # ── Template auto-fill ────────────────────────────────────────────────────

    @api.onchange('template_id')
    def _onchange_template_id(self):
        if not self.template_id:
            return
        partner = self.partner_id
        lead    = self.lead_id
        self.message = self.template_id.render_body(partner=partner, lead=lead)

    # ── Default phone from context ────────────────────────────────────────────

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        ctx = self.env.context

        # Pre-fill partner/lead from context
        if not res.get('partner_id') and ctx.get('default_partner_id'):
            res['partner_id'] = ctx['default_partner_id']
        if not res.get('lead_id') and ctx.get('default_lead_id'):
            res['lead_id'] = ctx['default_lead_id']

        # Auto-resolve phone
        if not res.get('phone'):
            if ctx.get('default_phone'):
                res['phone'] = ctx['default_phone']
            elif res.get('partner_id'):
                partner = self.env['res.partner'].browse(res['partner_id'])
                res['phone'] = (
                    getattr(partner, 'mobile', None) or partner.phone or ''
                )
            elif res.get('lead_id'):
                lead = self.env['crm.lead'].browse(res['lead_id'])
                res['phone'] = lead.phone or lead.mobile or ''

        return res

    # ── Send action ───────────────────────────────────────────────────────────

    def action_send(self):
        """Send the WhatsApp message via Evolution API or queue it."""
        self.ensure_one()

        clean_phone = _normalise_phone(self.phone)
        if not clean_phone:
            raise UserError("Please enter a valid phone number.")
        if not self.message or not self.message.strip():
            raise UserError("Message cannot be empty.")

        partner = self.partner_id
        lead    = self.lead_id

        ICP = self.env['ir.config_parameter'].sudo()
        evo_url      = ICP.get_param('integration_bridge.evolution_url',     'http://127.0.0.1:8099')
        evo_key      = ICP.get_param('integration_bridge.evolution_key',      '')
        evo_instance = ICP.get_param('integration_bridge.evolution_instance', 'sabry')

        if self.send_mode == 'now':
            success, response, wa_msg_id = _send_via_evolution(self.env, clean_phone, self.message)
            if not success:
                raise UserError(f"WhatsApp delivery failed: {response}")
            # Send attachments
            for att in self._get_attachment_info():
                from .whatsapp_bulk_wizard import _send_media_evolution
                _send_media_evolution(self.env, clean_phone, att)
            self._post_to_chatter_and_channel(clean_phone, self.message, 'sent')
            return self._success_notification(f"Message sent to {clean_phone}")

        else:  # queue or scheduled
            if self.send_mode == 'scheduled' and not self.scheduled_at:
                raise UserError("Please set a date/time for the scheduled send.")

            scheduled_dt = self.scheduled_at if self.send_mode == 'scheduled' else None
            rel_model    = lead._name if lead else (partner._name if partner else '')
            rel_id       = lead.id if lead else (partner.id if partner else 0)

            # Queue text
            endpoint = f"{evo_url}/message/sendText/{evo_instance}"
            self.env['integration.outbound.queue'].sudo().create_outbound_message(
                name=f"WhatsApp → {clean_phone}",
                platform='evolution',
                endpoint_url=endpoint,
                payload={'number': clean_phone, 'text': self.message, 'options': {'delay': 1000}},
                headers={'apikey': evo_key, 'Content-Type': 'application/json'},
                related_model=rel_model, related_res_id=rel_id,
                priority=7,
                scheduled_at=scheduled_dt,
            )
            # Queue attachments
            for att in self._get_attachment_info():
                self.env['integration.outbound.queue'].sudo().create_outbound_message(
                    name=f"WhatsApp Media → {clean_phone}",
                    platform='evolution',
                    endpoint_url=f"{evo_url}/message/sendMedia/{evo_instance}",
                    payload={'number': clean_phone, 'mediatype': att['type'],
                             'media': att['url'], 'caption': att['name']},
                    headers={'apikey': evo_key, 'Content-Type': 'application/json'},
                    related_model=rel_model, related_res_id=rel_id,
                    priority=6,
                    scheduled_at=scheduled_dt,
                )
            status_label = f"scheduled for {self.scheduled_at}" if self.send_mode == 'scheduled' else 'queued'
            self._post_to_chatter_and_channel(clean_phone, self.message, status_label)
            return self._success_notification(f"Message {status_label} for {clean_phone}")

    def _get_attachment_info(self):
        """Return list of {url, type, name} dicts for Evolution /sendMedia."""
        from .whatsapp_bulk_wizard import _mime_to_evo_type
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

    def _post_to_chatter_and_channel(self, phone, text, status):
        """Post the sent message to the lead/partner chatter and wa_channel."""
        body_html = (
            f"<div style='padding:8px;border-left:3px solid #25D366'>"
            f"<b>📱 WhatsApp {status} → {phone}</b><br/>"
            f"<div style='white-space:pre-wrap;margin-top:6px'>{text}</div>"
            f"</div>"
        )
        subtype = 'mail.mt_note'

        # Post to lead chatter
        lead = self.lead_id
        if lead:
            lead.message_post(body=body_html, message_type='comment', subtype_xmlid=subtype)

        # Post to partner chatter
        partner = self.partner_id
        if partner and (not lead or lead.partner_id != partner):
            partner.message_post(body=body_html, message_type='comment', subtype_xmlid=subtype)

        # Post to wa_channel (creates it if needed)
        if partner:
            channel = partner._get_or_create_wa_channel()
            # Post as internal user — but skip re-sending to Evolution
            # by posting as 'notification' so the override won't trigger
            channel.sudo().message_post(
                body=f"<p>{text}</p>",
                author_id=self.env.user.partner_id.id,
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
            )

    def _success_notification(self, msg):
        return {
            'type':  'ir.actions.client',
            'tag':   'display_notification',
            'params': {
                'title':   'WhatsApp',
                'message': msg,
                'type':    'success',
                'sticky':  False,
                'next':    {'type': 'ir.actions.act_window_close'},
            },
        }
