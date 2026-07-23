# -*- coding: utf-8 -*-
"""sms.send.wizard — transient wizard to compose and send phone SMS."""
import logging

from odoo import models, fields, api
from odoo.exceptions import UserError

from .sms_message_log import _normalize_phone

_logger = logging.getLogger(__name__)


class SmsSendWizard(models.TransientModel):
    _name = 'sms.send.wizard'
    _description = 'Send Phone SMS'

    # ── Recipients ────────────────────────────────────────────────────────────
    partner_ids = fields.Many2many(
        'res.partner', 'sms_send_wizard_partner_rel', 'wizard_id', 'partner_id',
        string='Recipients', help='Contacts to send this SMS to (uses their mobile/phone).',
    )
    lead_id = fields.Many2one('crm.lead', string='CRM Lead')
    phone = fields.Char(string='Phone Number',
                        help='Free phone number (used when no recipient contact is chosen).')

    # ── Message ───────────────────────────────────────────────────────────────
    template_id = fields.Many2one('phone.sms.template', string='Template', domain=[('active', '=', True)])
    body = fields.Text(string='Message', required=True)
    gateway_id = fields.Many2one('sms.gateway.config', string='Gateway',
                                 domain=[('active', '=', True)])

    recipient_count = fields.Integer(compute='_compute_recipient_count', string='# Recipients')

    @api.depends('partner_ids', 'phone')
    def _compute_recipient_count(self):
        for rec in self:
            count = len(rec.partner_ids)
            if not count and rec.phone:
                count = 1
            rec.recipient_count = count

    # ── Defaults ──────────────────────────────────────────────────────────────
    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        ctx = self.env.context

        if not res.get('gateway_id'):
            gw = self.env['sms.gateway.config']._get_default_gateway()
            if gw:
                res['gateway_id'] = gw.id

        if 'partner_ids' in fields_list and not res.get('partner_ids'):
            ids = ctx.get('default_partner_ids')
            if ctx.get('default_partner_id'):
                res['partner_ids'] = [(6, 0, [ctx['default_partner_id']])]
            elif ctx.get('active_model') == 'res.partner' and ctx.get('active_ids'):
                res['partner_ids'] = [(6, 0, ctx['active_ids'])]
            elif ids:
                res['partner_ids'] = [(6, 0, ids)]

        if not res.get('lead_id') and ctx.get('default_lead_id'):
            res['lead_id'] = ctx['default_lead_id']

        if not res.get('phone') and ctx.get('default_phone'):
            res['phone'] = ctx['default_phone']
        return res

    # ── Template auto-fill ────────────────────────────────────────────────────
    @api.onchange('template_id')
    def _onchange_template_id(self):
        if not self.template_id:
            return
        partner = self.partner_ids[:1] or (self.lead_id.partner_id if self.lead_id else None)
        self.body = self.template_id.render_body(partner=partner or None, lead=self.lead_id or None)

    # ── Build recipient list: [(partner|False, phone), ...] ───────────────────
    def _iter_recipients(self):
        self.ensure_one()
        recipients = []
        for partner in self.partner_ids:
            raw = getattr(partner, 'mobile', None) or partner.phone or ''
            recipients.append((partner, raw))
        if not self.partner_ids and self.phone:
            recipients.append((self.env['res.partner'], self.phone))
        return recipients

    # ── Send ──────────────────────────────────────────────────────────────────
    def action_send(self):
        self.ensure_one()
        if not self.body or not self.body.strip():
            raise UserError("Message cannot be empty.")
        gateway = self.gateway_id or self.env['sms.gateway.config']._get_default_gateway()
        if not gateway:
            raise UserError("No SMS gateway configured. Create one under Phone SMS ▸ Configuration.")

        recipients = self._iter_recipients()
        if not recipients:
            raise UserError("Please choose at least one recipient or enter a phone number.")

        Log = self.env['sms.message.log']
        sent = failed = 0
        for partner, raw_phone in recipients:
            phone = _normalize_phone(self.env, raw_phone)
            if not phone:
                failed += 1
                Log.create({
                    'partner_id': partner.id or False,
                    'lead_id': self.lead_id.id or False,
                    'phone': raw_phone or '(missing)',
                    'direction': 'out', 'body': self.body,
                    'state': 'failed', 'gateway_id': gateway.id,
                    'error_message': 'Invalid or missing phone number',
                })
                continue
            body = self.body
            if self.template_id and partner:
                body = self.template_id.render_body(partner=partner, lead=self.lead_id or None)
            ok, external_id, error = gateway.send_sms(phone, body)
            log = Log.create({
                'partner_id': partner.id or False,
                'lead_id': self.lead_id.id or False,
                'phone': phone,
                'direction': 'out',
                'body': body,
                'state': 'sent' if ok else 'failed',
                'gateway_id': gateway.id,
                'external_id': external_id or False,
                'error_message': error or False,
            })
            if ok:
                sent += 1
                if partner:
                    partner.message_post(
                        body=f"<div style='border-left:3px solid #198754;padding:8px'>"
                             f"<b>📤 SMS sent → {phone}</b>"
                             f"<div style='white-space:pre-wrap;margin-top:6px'>{body}</div></div>",
                        message_type='comment', subtype_xmlid='mail.mt_note',
                    )
                if self.lead_id:
                    self.lead_id.message_post(
                        body=f"<b>📤 SMS sent → {phone}</b>",
                        message_type='comment', subtype_xmlid='mail.mt_note',
                    )
            else:
                failed += 1
            _ = log

        msg = f"{sent} sent" + (f", {failed} failed" if failed else "")
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Phone SMS',
                'message': msg,
                'type': 'success' if failed == 0 else ('warning' if sent else 'danger'),
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
