# -*- coding: utf-8 -*-
"""Central non-mutation guard for Historical Review / media evaluation."""
from __future__ import annotations

from odoo import api, models
from odoo.exceptions import ValidationError

CTX_NON_MUTATING = "historical_review_non_mutating"


class WhatsappMessageHistoricalGuard(models.Model):
    _inherit = "whatsapp.message"

    @api.model
    def _historical_non_mutating_active(self):
        return bool(self.env.context.get(CTX_NON_MUTATING))

    def _messages_with_historical_media(self):
        """Messages currently under historical media review."""
        Media = self.env["dev.whatsapp.media"].sudo()
        return Media.search(
            [
                ("whatsapp_message_id", "in", self.ids),
                ("is_historical_review", "=", True),
            ]
        ).mapped("whatsapp_message_id")

    def _assert_historical_non_mutating(self, action):
        if self._historical_non_mutating_active():
            raise ValidationError(
                "Historical review non-mutating mode forbids %s on WhatsApp "
                "messages." % action
            )

    def _log_historical_skip(self, action, note=""):
        Event = self.env["dev.whatsapp.inbox.event"].sudo()
        for rec in self:
            Event.create(
                {
                    "message_id": rec.id,
                    "event_type": "historical_skip",
                    "from_state": rec.inbox_state or False,
                    "to_state": rec.inbox_state or False,
                    "note": (
                        "skipped_historical_media:%s %s"
                        % (action, (note or "").strip())
                    )[:200],
                }
            )

    def write(self, vals):
        if self._historical_non_mutating_active() and any(
            key in vals for key in ("inbox_state", "previous_inbox_state")
        ):
            raise ValidationError(
                "Historical review non-mutating mode forbids inbox field writes."
            )
        return super().write(vals)
