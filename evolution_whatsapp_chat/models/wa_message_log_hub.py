# -*- coding: utf-8 -*-
"""Mirror wa.message.log into WhatsApp Hub when both modules are installed."""
from odoo import api, models


class WaMessageLogHubMirror(models.Model):
    _inherit = "wa.message.log"

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        Compat = self.env.get("whatsapp.hub.compat")
        if Compat is not None:
            for rec in records:
                try:
                    Compat.mirror_wa_message_log(rec)
                except Exception:
                    # Never break legacy CRM send path
                    pass
        return records
