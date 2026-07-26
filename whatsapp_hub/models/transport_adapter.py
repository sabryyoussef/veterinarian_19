# -*- coding: utf-8 -*-
"""Hub → integration_bridge_core Evolution transport adapter (Phase 3).

Hub never stores or returns Evolution API keys. When bridge is missing, the
unified outbound path fails closed (no silent credential fallback from Hub
instance keys for the Phase-3 API). Legacy ``service_queue_outbound`` may still
use Hub instance keys for clinic compatibility.
"""
from __future__ import annotations

import logging

from odoo import api, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class WhatsappHubTransport(models.AbstractModel):
    _name = "whatsapp.hub.transport"
    _description = "WhatsApp Hub Transport Adapter"

    @api.model
    def send_text(self, *, destination, body, purpose=None, instance_reference=None,
                  hub_instance=None):
        """
        Execute one Evolution text send via integration_bridge_core.

        Returns normalized dict:
          ok, accepted, provider_message_id, http_status, error, temporary,
          bridge_instance_id, transport
        """
        Evo = self.env.get("evolution.instance")
        if Evo is None:
            raise UserError(
                "integration_bridge_core (evolution.instance) is required for "
                "unified Hub outbound transport."
            )
        instance_name = instance_reference
        if hub_instance and hub_instance.instance_name:
            instance_name = hub_instance.instance_name
        # Prefer linked evolution.instance id when Hub row was synced
        if hub_instance and hub_instance.evolution_instance_id:
            evo = Evo.sudo().browse(int(hub_instance.evolution_instance_id))
            if evo.exists() and evo.active:
                result = evo.send_whatsapp_text(destination, body)
                result = dict(result)
                result["bridge_instance_id"] = evo.id
                result["transport"] = "evolution.instance"
                return result
        result = Evo.sudo().send_whatsapp_text_for_purpose(
            destination,
            body,
            purpose=purpose if purpose in ("clinic", "developer", "other") else None,
            instance_name=instance_name,
        )
        result = dict(result)
        result.setdefault("bridge_instance_id", False)
        result.setdefault("transport", "evolution.instance")
        return result

    @api.model
    def send_media(self, **kwargs):
        """Media not implemented in Phase 3 unified API."""
        raise UserError(
            "Unified Hub outbound does not support media yet "
            "(deferred to a later phase)."
        )
