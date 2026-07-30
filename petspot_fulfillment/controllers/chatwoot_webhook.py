# -*- coding: utf-8 -*-
import json
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class PetspotChatwootWebhookController(http.Controller):
    """Authenticated Chatwoot → PetSpot availability intake (gated by ICP)."""

    def _json(self, payload, status=200):
        return request.make_response(
            json.dumps(payload),
            headers=[("Content-Type", "application/json")],
            status=status,
        )

    @http.route(
        "/petspot/fulfillment/chatwoot/webhook",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def chatwoot_webhook(self, **kwargs):
        Event = request.env["petspot.chatwoot.webhook.event"].sudo()
        headers = {k: v for k, v in request.httprequest.headers.items()}
        params = {k: v for k, v in request.httprequest.args.items()}
        if not Event.validate_webhook_secret(headers, params=params):
            _logger.warning(
                "petspot_ff chatwoot webhook unauthorized from %s",
                request.httprequest.remote_addr,
            )
            return self._json({"ok": False, "error": "unauthorized"}, status=401)
        try:
            raw = request.httprequest.get_data(as_text=True) or "{}"
            payload = json.loads(raw)
        except Exception:
            return self._json({"ok": False, "error": "malformed_json"}, status=400)
        if not isinstance(payload, dict):
            return self._json({"ok": False, "error": "malformed_payload"}, status=400)
        result = Event.process_webhook_payload(payload, headers=headers)
        status = int(result.pop("status", 200) or 200)
        if not result.get("ok") and status == 200:
            status = 400
        return self._json(result, status=status)

    @http.route(
        "/petspot/fulfillment/chatwoot/health",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def chatwoot_health(self, **kwargs):
        ICP = request.env["ir.config_parameter"].sudo()
        return self._json({
            "ok": True,
            "module": "petspot_fulfillment",
            "endpoint": "/petspot/fulfillment/chatwoot/webhook",
            "intake_enabled": ICP.get_param(
                "petspot_fulfillment.chatwoot_intake_enabled", "False"
            ) == "True",
        })
