# -*- coding: utf-8 -*-
"""
sms.gateway.config — connection settings for the phone SMS gateway.

The phone runs an SMS gateway app (e.g. SMSGate / android-sms-gateway) reachable
over USB/Bluetooth tethering or the LAN. This model stores the connection details
and exposes a tiny urllib-based JSON/HTTP client so we have **no external deps**
(mirrors the Evolution API client style of ``evolution_whatsapp_chat`` but without
the ``requests`` dependency).

The backend is pluggable via ``gateway_type`` so it can be swapped later.
"""
import base64
import json
import logging
import ssl
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

_USER_AGENT = 'Odoo-PhoneSMSConnector/19.0'
_DEFAULT_TIMEOUT = 15


# ---------------------------------------------------------------------------
# Tiny JSON/HTTP client (urllib, no external deps)
# ---------------------------------------------------------------------------

def _http_json(method, url, headers=None, payload=None, timeout=_DEFAULT_TIMEOUT):
    """
    Perform an HTTP request and return ``(status_code, text, data)``.

    ``data`` is the parsed JSON body when the response is JSON, else ``None``.
    Network/HTTP errors are converted into ``(status_code, text, None)`` when a
    response is available, otherwise they raise so the caller can report them.
    """
    data_bytes = None
    req_headers = {
        'User-Agent': _USER_AGENT,
        'Accept': 'application/json',
    }
    if headers:
        req_headers.update(headers)
    if payload is not None:
        data_bytes = json.dumps(payload).encode('utf-8')
        req_headers.setdefault('Content-Type', 'application/json')

    req = urlrequest.Request(url=url, data=data_bytes, headers=req_headers, method=method)
    ctx = ssl.create_default_context()
    # Local phone gateways often use self-signed certs / plain HTTP; be lenient on https.
    if url.lower().startswith('https'):
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    try:
        with urlrequest.urlopen(req, timeout=timeout, context=ctx) as resp:
            raw = resp.read().decode('utf-8', errors='replace')
            status = resp.getcode()
    except HTTPError as e:
        raw = e.read().decode('utf-8', errors='replace') if e.fp else str(e)
        status = e.code
    except URLError as e:
        raise UserError(f"Could not reach the SMS gateway at {url}: {e.reason}")
    except Exception as e:  # noqa: BLE001
        raise UserError(f"SMS gateway request failed: {e}")

    parsed = None
    if raw:
        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError):
            parsed = None
    return status, raw, parsed


class SmsGatewayConfig(models.Model):
    _name = 'sms.gateway.config'
    _description = 'Phone SMS Gateway Configuration'
    _order = 'is_default desc, sequence, id'
    _rec_name = 'name'

    name = fields.Char(string='Name', required=True, help='Label for this gateway configuration')
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    is_default = fields.Boolean(
        string='Default Gateway',
        help='Use this gateway when none is explicitly selected. Only one should be default.',
    )

    gateway_type = fields.Selection(
        selection=[
            ('smsgate', 'Android SMS Gateway (SMSGate)'),
            ('generic', 'Generic HTTP JSON'),
        ],
        string='Backend',
        default='smsgate',
        required=True,
        help='Pluggable backend. Determines how requests are shaped for send/inbound.',
    )

    base_url = fields.Char(
        string='Base URL', required=True,
        help='Root URL of the phone SMS gateway, e.g. http://10.92.110.233:8080',
    )
    # Secrets — restricted to system administrators.
    api_key = fields.Char(
        string='API Key / Token', groups='base.group_system',
        help='Bearer token, API key, or "user:password" for HTTP Basic auth.',
    )
    default_sender = fields.Char(
        string='Default Sender',
        help='Optional SIM / sender id to use when the gateway supports multiple SIMs.',
    )

    # Connection test results
    last_test_state = fields.Selection(
        selection=[('none', 'Not Tested'), ('ok', 'OK'), ('failed', 'Failed')],
        string='Last Test', default='none', readonly=True,
    )
    last_test_message = fields.Char(string='Last Test Message', readonly=True)
    last_test_date = fields.Datetime(string='Last Tested On', readonly=True)

    _sql_constraints = [
        ('name_uniq', 'unique(name)', 'A gateway configuration with this name already exists.'),
    ]

    # ── Defaults / lookup ─────────────────────────────────────────────────────

    @api.model
    def _get_default_gateway(self):
        """Return the default (or first active) gateway, or an empty recordset."""
        gw = self.search([('is_default', '=', True), ('active', '=', True)], limit=1)
        if not gw:
            gw = self.search([('active', '=', True)], limit=1)
        return gw

    @api.onchange('is_default')
    def _onchange_is_default(self):
        if self.is_default:
            others = self.search([('is_default', '=', True), ('id', '!=', self._origin.id)])
            if others:
                return {'warning': {
                    'title': 'Default Gateway',
                    'message': 'Another gateway is already the default; it will be unset on save.',
                }}

    def write(self, vals):
        res = super().write(vals)
        if vals.get('is_default'):
            for rec in self.filtered('is_default'):
                (self.search([('is_default', '=', True), ('id', '!=', rec.id)])).write({'is_default': False})
        return res

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records.filtered('is_default'):
            (self.search([('is_default', '=', True), ('id', '!=', rec.id)])).write({'is_default': False})
        return records

    # ── Auth headers ──────────────────────────────────────────────────────────

    def _auth_headers(self):
        """Build auth headers from the stored api_key. Supports Bearer / Basic / X-Api-Key."""
        self.ensure_one()
        key = self.sudo().api_key or ''
        headers = {}
        if not key:
            return headers
        if ':' in key:
            # user:password → HTTP Basic (SMSGate default auth scheme)
            token = base64.b64encode(key.encode('utf-8')).decode('ascii')
            headers['Authorization'] = f'Basic {token}'
        else:
            headers['Authorization'] = f'Bearer {key}'
            headers['X-Api-Key'] = key
        return headers

    def _url(self, path):
        self.ensure_one()
        base = (self.base_url or '').rstrip('/')
        return f"{base}/{path.lstrip('/')}"

    # ── Connection test ───────────────────────────────────────────────────────

    def action_test_connection(self):
        """Ping the gateway and record the result in last_test_* fields."""
        self.ensure_one()
        state, message = 'failed', ''
        # SMSGate exposes /health; fall back to the base URL for generic backends.
        candidates = ['health', 'api/health', ''] if self.gateway_type == 'smsgate' else ['', 'health']
        last_err = ''
        for path in candidates:
            url = self._url(path)
            try:
                status, text, _data = _http_json('GET', url, headers=self._auth_headers())
            except UserError as e:
                last_err = str(e)
                continue
            if 200 <= status < 500:
                # Any structured HTTP answer (even 401/404) means the host is reachable.
                if status in (200, 204):
                    state, message = 'ok', f'Connected (HTTP {status}) at {url}'
                    break
                state, message = 'ok', f'Reachable (HTTP {status}) at {url}'
                if status < 300:
                    break
            else:
                last_err = f'HTTP {status} at {url}: {text[:120]}'
        if state != 'ok' and last_err:
            message = last_err

        self.write({
            'last_test_state': state,
            'last_test_message': message[:250] if message else '',
            'last_test_date': fields.Datetime.now(),
        })
        notif_type = 'success' if state == 'ok' else 'danger'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'SMS Gateway',
                'message': message or ('Connection OK' if state == 'ok' else 'Connection failed'),
                'type': notif_type,
                'sticky': False,
            },
        }

    # ── Send ──────────────────────────────────────────────────────────────────

    def send_sms(self, phone, body):
        """
        Send an SMS through this gateway.

        Returns ``(success: bool, external_id: str|False, error: str)``.
        """
        self.ensure_one()
        if not phone:
            return False, False, 'No phone number'
        if not body:
            return False, False, 'Empty message'

        if self.gateway_type == 'smsgate':
            url = self._url('message')
            payload = {'message': body, 'phoneNumbers': [phone]}
            if self.default_sender:
                payload['simNumber'] = self.default_sender
        else:  # generic
            url = self._url('send')
            payload = {'to': phone, 'text': body}
            if self.default_sender:
                payload['from'] = self.default_sender

        try:
            status, text, data = _http_json('POST', url, headers=self._auth_headers(), payload=payload)
        except UserError as e:
            return False, False, str(e)

        if 200 <= status < 300:
            external_id = False
            if isinstance(data, dict):
                external_id = data.get('id') or data.get('messageId') or data.get('message_id') or False
            _logger.info("[Phone SMS] Sent to %s via %s (HTTP %s, id=%s)", phone, self.name, status, external_id)
            return True, external_id, ''
        error = f'HTTP {status}: {text[:200]}'
        _logger.error("[Phone SMS] Send failed to %s via %s: %s", phone, self.name, error)
        return False, False, error

    # ── Inbound fetch ─────────────────────────────────────────────────────────

    def fetch_inbound(self):
        """
        Fetch inbound messages from the gateway.

        Returns a list of dicts: ``{'external_id', 'phone', 'body', 'received_at'}``.
        Best-effort — returns ``[]`` on any error so the cron never crashes.
        """
        self.ensure_one()
        if self.gateway_type == 'smsgate':
            url = self._url('messages/inbox')
        else:
            url = self._url('inbound')
        try:
            status, _text, data = _http_json('GET', url, headers=self._auth_headers())
        except UserError as e:
            _logger.warning("[Phone SMS] Inbound fetch failed for %s: %s", self.name, e)
            return []
        if not (200 <= status < 300) or not isinstance(data, (list, dict)):
            return []
        items = data if isinstance(data, list) else data.get('messages', [])
        result = []
        for it in items or []:
            if not isinstance(it, dict):
                continue
            result.append({
                'external_id': it.get('id') or it.get('messageId') or False,
                'phone': it.get('phoneNumber') or it.get('from') or it.get('address') or '',
                'body': it.get('message') or it.get('text') or it.get('body') or '',
                'received_at': it.get('receivedAt') or it.get('received') or False,
            })
        return result
