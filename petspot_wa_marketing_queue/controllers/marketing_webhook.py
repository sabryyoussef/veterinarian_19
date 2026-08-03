# -*- coding: utf-8 -*-
import json
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class PetspotWaMarketingWebhook(http.Controller):
    @http.route(
        "/petspot/wa/marketing/evolution/webhook",
        type="jsonrpc",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def evolution_webhook(self, **kwargs):
        """Inbound Evolution events for marketing instance only (public JSON)."""
        data = request.jsonrequest or {}
        # Never log secrets; minimal handling
        try:
            instance = (
                (data.get("instance") or data.get("instanceName") or "")
                if isinstance(data.get("instance"), str)
                else (data.get("instance") or {}).get("instanceName")
                or data.get("instanceName")
                or ""
            )
            if instance and instance != "petspot-marketing":
                return {"ok": False, "reason": "ignored_non_marketing_instance"}

            # Baileys-style message extract (best-effort)
            msg = data.get("data") or data.get("message") or {}
            key = msg.get("key") or {}
            if key.get("fromMe"):
                return {"ok": True, "ignored": "fromMe"}
            text = ""
            message = msg.get("message") or {}
            text = message.get("conversation") or (message.get("extendedTextMessage") or {}).get("text") or ""
            remote = key.get("remoteJidAlt") or key.get("remoteJid") or ""
            mobile = remote.split("@")[0] if remote else ""
            if text and mobile:
                result = (
                    request.env["petspot.wa.marketing.dispatcher"]
                    .sudo()
                    .handle_inbound_text(mobile, text)
                )
                return {"ok": True, "result": result}
        except Exception as exc:
            _logger.warning("marketing webhook error: %s", exc)
            return {"ok": False, "error": "handler_error"}
        return {"ok": True, "ignored": True}
