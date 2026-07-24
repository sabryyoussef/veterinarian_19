# -*- coding: utf-8 -*-
"""Deterministic message segmentation for WhatsApp AI batches."""
from __future__ import annotations

from datetime import timedelta

from odoo import api, fields, models


class DevWhatsappAnalysisSegment(models.AbstractModel):
    _name = "dev.whatsapp.analysis.segment"
    _description = "WhatsApp AI message segmentation helpers"

    @api.model
    def segment_messages(self, messages, max_per_segment=12, gap_minutes=45):
        """Split messages into coherent segments (deterministic).

        Returns list of recordsets. Conservative: reply/time-gap based.
        """
        if not messages:
            return []
        ordered = messages.sorted(
            key=lambda m: (m.message_timestamp or fields.Datetime.now(), m.id)
        )
        segments = []
        current = self.env["whatsapp.message"]
        last_ts = None
        for msg in ordered:
            ts = msg.message_timestamp or fields.Datetime.now()
            if current and last_ts and (ts - last_ts) > timedelta(minutes=gap_minutes):
                segments.append(current)
                current = self.env["whatsapp.message"]
            if len(current) >= max_per_segment:
                segments.append(current)
                current = self.env["whatsapp.message"]
            current |= msg
            last_ts = ts
        if current:
            segments.append(current)
        return segments or [messages]
