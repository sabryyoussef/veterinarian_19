# -*- coding: utf-8 -*-
"""Mirror wa.message.log into WhatsApp Hub when both modules are installed.

Observational only — never triggers Hub outbound or recursive log creates.
"""
from odoo import api, models


class WaMessageLogHubMirror(models.Model):
    _inherit = "wa.message.log"

    def _hub_mirror_enabled(self):
        # Skip when Hub (or tests) asks us not to mirror, or when a Hub write
        # somehow re-enters log create/write (loop prevention).
        if self.env.context.get("whatsapp_hub_skip_mirror"):
            return False
        if self.env.context.get("whatsapp_hub_mirroring"):
            return False
        return self.env.get("whatsapp.hub.compat") is not None

    def _mirror_to_hub(self):
        Compat = self.env.get("whatsapp.hub.compat")
        if Compat is None:
            return
        for rec in self:
            try:
                Compat.mirror_wa_message_log(rec)
            except Exception:
                # Never break legacy CRM / Campaign / Discuss send path
                pass

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if records._hub_mirror_enabled():
            records._mirror_to_hub()
        return records

    def write(self, vals):
        sync_keys = {
            "delivery_status",
            "wa_message_id",
            "message_text",
            "partner_id",
            "lead_id",
            "channel_id",
            "queue_id",
            "campaign_id",
            "campaign_line_id",
            "mail_message_id",
            "hub_message_id",
            "send_origin",
            "delivered_at",
            "read_at",
            "sent_at",
            "replied",
            "reply_text",
        }
        result = super().write(vals)
        if self._hub_mirror_enabled() and sync_keys.intersection(vals.keys()):
            self._mirror_to_hub()
        return result
