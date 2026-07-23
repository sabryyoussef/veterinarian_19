# -*- coding: utf-8 -*-
"""Optional HTTP ingress that delegates to the canonical RPC (compat)."""
import json
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class WhatsappHubIngressController(http.Controller):
    @http.route(
        "/whatsapp_hub/ingest",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def ingest_normalized(self, **kwargs):
        """
        HTTP wrapper around whatsapp.message.service_ingest_normalized.

        Auth: X-Bridge-Token (same as integration_bridge_core) when bridge installed,
        otherwise reject.
        """
        token = request.httprequest.headers.get("X-Bridge-Token") or ""
        if not self._validate_token(token):
            return request.make_json_response({"ok": False, "error": "unauthorized"}, status=401)
        try:
            raw = request.httprequest.get_data(as_text=True)
            payload = json.loads(raw) if raw else {}
        except Exception:
            return request.make_json_response({"ok": False, "error": "invalid_json"}, status=400)
        try:
            # Run as ingest service via sudo + explicit method ACL inside method
            result = (
                request.env["whatsapp.message"]
                .sudo()
                .service_ingest_normalized(payload)
            )
            return request.make_json_response({"ok": True, **result})
        except Exception as exc:
            _logger.exception("whatsapp_hub ingest failed")
            return request.make_json_response(
                {"ok": False, "error": str(exc)}, status=400
            )

    def _validate_token(self, token):
        if not token:
            return False
        Token = request.env.get("integration.bridge.token")
        if Token is not None:
            try:
                return bool(
                    Token.sudo().validate_token(
                        token, "n8n", request.httprequest.remote_addr
                    )
                )
            except Exception:
                pass
        ICP = request.env["ir.config_parameter"].sudo()
        master = ICP.get_param("integration_bridge.master_token") or ""
        return bool(master) and token == master

    @http.route("/whatsapp_hub/health", type="http", auth="public", methods=["GET"], csrf=False)
    def health(self, **kwargs):
        return request.make_json_response({"ok": True, "module": "whatsapp_hub"})
