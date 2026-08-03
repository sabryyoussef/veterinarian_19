# -*- coding: utf-8 -*-
import json
import logging
import urllib.error
import urllib.request

from odoo import api, models
from odoo.exceptions import UserError

from .settings import FORBIDDEN_INSTANCES, REQUIRED_INSTANCE

_logger = logging.getLogger(__name__)


class PetspotWaMarketingEvolutionClient(models.AbstractModel):
    _name = "petspot.wa.marketing.evolution.client"
    _description = "Evolution client locked to petspot-marketing"

    @api.model
    def _settings(self):
        return self.env["petspot.wa.marketing.settings"].sudo().get_settings()

    @api.model
    def _assert_instance(self, instance_name):
        name = (instance_name or "").strip()
        if name != REQUIRED_INSTANCE:
            raise UserError(self.env._("Refusing send: instance must be petspot-marketing."))
        if name.lower() in FORBIDDEN_INSTANCES or "sabry" in name.lower():
            raise UserError(self.env._("Refusing send: forbidden Evolution instance."))

    @api.model
    def connection_state(self):
        settings = self._settings()
        self._assert_instance(settings.evolution_instance)
        if settings.mock_send:
            return {"state": "open", "mock": True}
        # Real call — used only when mock_send False and allowlisted
        url = f"{settings.evolution_base_url.rstrip('/')}/instance/connectionState/{REQUIRED_INSTANCE}"
        try:
            # API key from system parameter only (never hardcode)
            key = (
                self.env["ir.config_parameter"]
                .sudo()
                .get_param("petspot_wa_marketing_queue.evolution_apikey", "")
            )
            if not key:
                return {"state": "unknown", "error": "missing_apikey_param"}
            req = urllib.request.Request(url, headers={"apikey": key})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
            state = (data.get("instance") or data).get("state")
            return {"state": state or "unknown"}
        except Exception as exc:
            _logger.warning("Evolution connectionState failed: %s", exc)
            return {"state": "error", "error": str(exc)[:200]}

    @api.model
    def send_text(self, mobile_e164, text):
        settings = self._settings()
        self._assert_instance(settings.evolution_instance)
        digits = "".join(ch for ch in (mobile_e164 or "") if ch.isdigit())
        if settings.mock_send:
            return {"ok": True, "mock": True, "message_id": f"MOCK-{digits[-4:]}-{abs(hash(text)) % 10**8}"}
        allow = settings.parse_allowlist()
        if mobile_e164 not in allow and f"+{digits}" not in allow:
            raise UserError(
                self.env._("Real Evolution send blocked: mobile not on internal test allowlist.")
            )
        key = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("petspot_wa_marketing_queue.evolution_apikey", "")
        )
        if not key:
            raise UserError(self.env._("Missing Evolution API key system parameter."))
        url = f"{settings.evolution_base_url.rstrip('/')}/message/sendText/{REQUIRED_INSTANCE}"
        payload = json.dumps({"number": digits, "text": text}).encode()
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"apikey": key, "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                data = json.loads(resp.read().decode())
            mid = (data.get("key") or {}).get("id") or data.get("messageId")
            return {"ok": True, "mock": False, "message_id": mid, "raw_status": resp.status}
        except urllib.error.HTTPError as exc:
            body = exc.read().decode(errors="replace")[:300]
            return {"ok": False, "error": f"http_{exc.code}", "detail": body}
        except Exception as exc:
            return {"ok": False, "error": "transport", "detail": str(exc)[:300]}
