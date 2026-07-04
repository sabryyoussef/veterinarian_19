# -*- coding: utf-8 -*-
import logging

from odoo import http
from odoo.http import request

from odoo.addons.integration_bridge_core.controllers.bridge_base import BridgeControllerBase

_logger = logging.getLogger(__name__)


class PetspotWaIntakeController(BridgeControllerBase):
    """Secured intake endpoint for Chatwoot / n8n / Evolution fan-out."""

    @http.route(
        '/petspot/wa/intake',
        type='http',
        auth='public',
        methods=['POST', 'OPTIONS'],
        csrf=False,
        cors='*',
    )
    def petspot_wa_intake(self, **kwargs):
        if request.httprequest.method == 'OPTIONS':
            return self._json_response({'ok': True})

        auth = self._validate_token(expected_platform=None)
        if auth == 'IP_BLOCKED':
            return self._json_response({'ok': False, 'error': 'ip_blocked'}, status=403)
        if not auth:
            return self._json_response({'ok': False, 'error': 'unauthorized'}, status=401)

        payload = self._get_json_payload(**kwargs)
        try:
            intake = request.env['petspot.wa.intake'].sudo().create_from_webhook(payload)
        except Exception as exc:
            _logger.warning('petspot_wa_intake rejected: %s', exc)
            return self._json_response({'ok': False, 'error': str(exc)}, status=400)

        return self._json_response({
            'ok': True,
            'intake_id': intake.id,
            'name': intake.name,
            'state': intake.state,
            'intent': intake.intent,
            'partner_id': intake.partner_id.id or False,
            'pet_id': intake.pet_id.id or False,
        })

    @http.route('/petspot/wa/intake/health', type='http', auth='public', methods=['GET'], csrf=False)
    def petspot_wa_intake_health(self, **kwargs):
        return self._json_response({
            'ok': True,
            'module': 'petspot_wa_intake',
            'endpoint': '/petspot/wa/intake',
        })
