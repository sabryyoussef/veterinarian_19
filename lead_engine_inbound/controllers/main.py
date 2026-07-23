# -*- coding: utf-8 -*-

import json

from odoo import http
from odoo.http import request


class LeadEngineInboundController(http.Controller):
    """MVP REST intake (Sprint 2). Auth: Authorization: Bearer <inbound_api_token>."""

    def _parse_bearer(self):
        auth = request.httprequest.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
        return ""

    def _json_response(self, data, status=200):
        body = json.dumps(data, default=str)
        return request.make_response(
            body,
            headers=[("Content-Type", "application/json;charset=utf-8")],
            status=status,
        )

    @http.route(
        "/lead_engine/v1/intake",
        type="http",
        auth="lead_engine_bearer",
        methods=["POST"],
        csrf=False,
    )
    def intake_v1(self, **kwargs):
        token = self._parse_bearer()
        # _auth_method_lead_engine_bearer already set session.uid = SUPERUSER_ID,
        # so request.env has a real uid and ORM flush works for monetary fields.
        env = request.env
        source = env["lead.engine.inbound.service"].resolve_source_from_token(token)
        if not source:
            return self._json_response(
                {
                    "ok": False,
                    "error": {"code": "unauthorized", "message": "Invalid or missing token."},
                },
                status=401,
            )
        raw = request.httprequest.get_data(cache=False, as_text=True) or ""
        try:
            payload = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            return self._json_response(
                {
                    "ok": False,
                    "error": {"code": "rejected", "message": "Body must be valid JSON."},
                },
                status=400,
            )
        result = env["lead.engine.inbound.service"].process_intake(source, payload, raw)
        status = 200
        if not result.get("ok"):
            code = (result.get("error") or {}).get("code")
            if code == "rejected":
                status = 400
            elif code == "error":
                status = 500
            else:
                status = 400
        return self._json_response(result, status=status)
