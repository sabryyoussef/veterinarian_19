# -*- coding: utf-8 -*-
"""
Webhook controller for the phone SMS gateway.

The gateway can push callbacks here to:
  - record inbound SMS  (event = "sms:received" / payload has body+phone)
  - update delivery state (event = "sms:sent" / "sms:delivered" / "sms:failed")

The endpoint is token-protected: the caller must present the token stored in the
``phone_sms_connector.webhook_token`` system parameter, either as the
``token`` field in the JSON body or as an ``X-Webhook-Token`` header.
"""
import json
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class PhoneSmsWebhook(http.Controller):

    def _check_token(self, payload):
        expected = request.env['ir.config_parameter'].sudo().get_param(
            'phone_sms_connector.webhook_token')
        if not expected:
            # No token configured → reject to stay safe.
            return False
        provided = (
            request.httprequest.headers.get('X-Webhook-Token')
            or request.httprequest.args.get('token')
            or (payload.get('token') if isinstance(payload, dict) else None)
        )
        return bool(provided) and provided == expected

    @http.route('/phone_sms/webhook', type='http', auth='public',
                methods=['POST'], csrf=False, save_session=False)
    def webhook(self, **kwargs):
        try:
            raw = request.httprequest.get_data(as_text=True) or '{}'
            payload = json.loads(raw) if raw.strip() else {}
        except (ValueError, TypeError):
            payload = dict(kwargs)

        if not self._check_token(payload):
            _logger.warning("[Phone SMS] Webhook rejected: invalid/missing token")
            return request.make_json_response({'status': 'error', 'message': 'unauthorized'}, status=401)

        event = (payload.get('event') or payload.get('type') or '').lower()
        data = payload.get('payload') if isinstance(payload.get('payload'), dict) else payload

        Log = request.env['sms.message.log'].sudo()
        try:
            if 'receiv' in event or (not event and (data.get('message') or data.get('text') or data.get('body'))):
                Log.record_inbound(
                    phone=data.get('phoneNumber') or data.get('from') or data.get('phone') or data.get('address'),
                    body=data.get('message') or data.get('text') or data.get('body'),
                    external_id=data.get('id') or data.get('messageId') or False,
                    received_at=data.get('receivedAt') or data.get('received') or False,
                )
                result = 'inbound recorded'
            else:
                status = (data.get('state') or data.get('status')
                          or event.split(':')[-1] if event else 'sent')
                Log.update_delivery_status(
                    data.get('id') or data.get('messageId') or data.get('external_id'),
                    status,
                )
                result = 'status updated'
        except Exception as e:  # noqa: BLE001
            _logger.exception("[Phone SMS] Webhook processing error: %s", e)
            return request.make_json_response({'status': 'error', 'message': str(e)}, status=500)

        return request.make_json_response({'status': 'ok', 'result': result})
