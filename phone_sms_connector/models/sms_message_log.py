# -*- coding: utf-8 -*-
"""
sms.message.log — one row per SMS (outbound & inbound).

Outbound rows are created by the send wizard / partner-lead actions.
Inbound rows are created by the poll-inbound cron and the webhook controller.
"""
import logging
import re
from datetime import datetime, timezone

from odoo import models, fields, api

_logger = logging.getLogger(__name__)


def _parse_received_at(value):
    """
    Normalise a gateway ``receivedAt`` into a naive UTC datetime for Odoo.

    Accepts ISO-8601 (``2026-07-17T23:49:28.000+03:00`` / ``...Z``) and the
    plain ``%Y-%m-%d %H:%M:%S`` format. Returns ``None`` on failure so the
    caller falls back to ``now()``.
    """
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        dt = None
        try:
            dt = datetime.fromisoformat(text.replace('Z', '+00:00'))
        except ValueError:
            for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S'):
                try:
                    dt = datetime.strptime(text, fmt)
                    break
                except ValueError:
                    continue
        if dt is None:
            return None
    # Convert tz-aware → naive UTC (Odoo stores naive UTC datetimes).
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _normalize_phone(env, raw, country_code='EG'):
    """
    Normalise a phone number to E.164 using ``phone_validation`` when possible,
    with a regex fallback (Egyptian local 01… → +201…).
    """
    if not raw:
        return ''
    raw = str(raw).strip()
    try:
        from odoo.addons.phone_validation.tools import phone_validation
        country = env.ref('base.%s' % country_code.lower(), raise_if_not_found=False) if country_code else None
        code = country.code if country else 'EG'
        phone_code = country.phone_code if country else 20
        formatted = phone_validation.phone_format(
            raw, code, phone_code, force_format='E164', raise_exception=False,
        )
        if formatted:
            return formatted
    except Exception:  # noqa: BLE001
        pass
    # Regex fallback
    clean = re.sub(r'[^\d+]', '', raw)
    if clean.startswith('00'):
        clean = '+' + clean[2:]
    if clean.startswith('+'):
        return clean
    digits = re.sub(r'\D', '', clean)
    if digits.startswith('0') and len(digits) == 11:  # Egyptian mobile
        return '+20' + digits[1:]
    if digits.startswith('20'):
        return '+' + digits
    return ('+' + digits) if digits else ''


class SmsMessageLog(models.Model):
    _name = 'sms.message.log'
    _description = 'Phone SMS Message Log'
    _inherit = ['mail.thread']
    _order = 'sent_at desc, id desc'
    _rec_name = 'display_name'

    partner_id = fields.Many2one('res.partner', string='Contact', index=True,
                                 ondelete='set null', tracking=True)
    lead_id = fields.Many2one('crm.lead', string='Lead', index=True, ondelete='set null')
    phone = fields.Char(string='Phone', required=True, index=True, tracking=True)

    direction = fields.Selection(
        selection=[('out', 'Outbound'), ('in', 'Inbound')],
        string='Direction', required=True, index=True, default='out', tracking=True,
    )
    body = fields.Text(string='Message')

    state = fields.Selection(
        selection=[
            ('queued', 'Queued'),
            ('sent', 'Sent'),
            ('delivered', 'Delivered'),
            ('failed', 'Failed'),
            ('received', 'Received'),
        ],
        string='Status', default='queued', required=True, index=True, tracking=True,
    )

    gateway_id = fields.Many2one('sms.gateway.config', string='Gateway', ondelete='set null')
    error_message = fields.Char(string='Error Message')
    external_id = fields.Char(string='External ID', index=True,
                              help='Message id returned by the gateway — matches delivery callbacks')

    sent_at = fields.Datetime(string='Sent At', default=fields.Datetime.now)
    delivered_at = fields.Datetime(string='Delivered At')

    display_name = fields.Char(compute='_compute_display_name', store=False)

    @api.depends('partner_id', 'phone', 'direction')
    def _compute_display_name(self):
        for rec in self:
            name = rec.partner_id.name or rec.phone or 'SMS'
            arrow = '→' if rec.direction == 'out' else '←'
            rec.display_name = f"{arrow} {name}"

    # ── Delivery status update (from webhook) ─────────────────────────────────

    @api.model
    def update_delivery_status(self, external_id, status):
        """Update the state of logs matching ``external_id`` from a gateway callback."""
        if not external_id:
            return False
        STATUS_MAP = {
            'pending': 'sent', 'queued': 'queued', 'sent': 'sent',
            'delivered': 'delivered', 'read': 'delivered',
            'failed': 'failed', 'error': 'failed',
        }
        odoo_state = STATUS_MAP.get(str(status).lower())
        if not odoo_state:
            return False
        logs = self.sudo().search([('external_id', '=', external_id)], limit=5)
        if not logs:
            _logger.debug("[Phone SMS] No log for external_id=%s", external_id)
            return False
        vals = {'state': odoo_state}
        if odoo_state == 'delivered':
            vals['delivered_at'] = fields.Datetime.now()
        logs.write(vals)
        _logger.info("[Phone SMS] %s log(s) id=%s → %s", len(logs), external_id, odoo_state)
        return True

    # ── Record an inbound message ─────────────────────────────────────────────

    @api.model
    def record_inbound(self, phone, body, external_id=False, gateway=None, received_at=False):
        """Create a direction='in' log, attaching to the matching partner by phone."""
        norm = _normalize_phone(self.env, phone)
        # De-dupe on external_id
        if external_id and self.sudo().search_count([
            ('external_id', '=', external_id), ('direction', '=', 'in')]):
            return False
        partner = self._find_partner_by_phone(norm or phone)
        vals = {
            'phone': norm or phone or '',
            'body': body or '',
            'direction': 'in',
            'state': 'received',
            'external_id': external_id or False,
            'sent_at': _parse_received_at(received_at) or fields.Datetime.now(),
            'partner_id': partner.id if partner else False,
            'gateway_id': gateway.id if gateway else False,
        }
        log = self.sudo().create(vals)
        # Parse bank-notification SMS into a structured transaction (best-effort).
        try:
            from .bank_sms_transaction import parse_bank_sms
            parsed = parse_bank_sms(body or '')
            if parsed:
                self.env['bank.sms.transaction'].sudo().create({
                    'date': vals['sent_at'],
                    'body': body or '',
                    'sms_log_id': log.id,
                    'partner_id': partner.id if partner else False,
                    **parsed,
                })
        except Exception as e:  # noqa: BLE001 — never break inbound recording
            _logger.warning("[Phone SMS] Bank transaction parse failed: %s", e)
        if partner:
            body_html = (
                f"<div style='padding:8px;border-left:3px solid #0d6efd'>"
                f"<b>📩 SMS received from {norm or phone}</b>"
                f"<div style='white-space:pre-wrap;margin-top:6px'>{body or ''}</div></div>"
            )
            partner.sudo().message_post(body=body_html, message_type='comment',
                                        subtype_xmlid='mail.mt_note')
        _logger.info("[Phone SMS] Inbound recorded from %s (partner=%s)", norm or phone, partner.id if partner else '-')
        return log

    @api.model
    def _find_partner_by_phone(self, phone):
        """Best-effort partner match by phone/mobile (normalised)."""
        if not phone:
            return self.env['res.partner']
        norm = _normalize_phone(self.env, phone)
        digits = re.sub(r'\D', '', norm or phone)
        tail = digits[-9:] if len(digits) >= 9 else digits
        if not tail:
            return self.env['res.partner']
        Partner = self.env['res.partner'].sudo()
        # Only search phone-like fields that actually exist (Odoo 19 dropped
        # ``res.partner.mobile``).
        for field in ('phone', 'mobile'):
            if field not in Partner._fields:
                continue
            partner = Partner.search([(field, 'like', tail)], limit=1)
            if partner:
                return partner
        return self.env['res.partner']

    # ── Cron: poll inbound from all active gateways ───────────────────────────

    @api.model
    def _cron_poll_inbound(self):
        """Scheduled action: fetch new inbound SMS from every active gateway."""
        gateways = self.env['sms.gateway.config'].sudo().search([('active', '=', True)])
        total = 0
        for gw in gateways:
            for msg in gw.fetch_inbound():
                if not msg.get('phone') and not msg.get('body'):
                    continue
                created = self.record_inbound(
                    phone=msg.get('phone'), body=msg.get('body'),
                    external_id=msg.get('external_id'), gateway=gw,
                    received_at=msg.get('received_at') or False,
                )
                if created:
                    total += 1
        if total:
            _logger.info("[Phone SMS] Poll inbound created %s new message(s)", total)
        return total
