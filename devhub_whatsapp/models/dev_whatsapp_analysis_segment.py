# -*- coding: utf-8 -*-
"""Deterministic message segmentation for WhatsApp AI batches."""
from __future__ import annotations

from datetime import timedelta

from odoo import api, fields, models

from odoo.addons.devhub_work.models.dev_project_alias import normalize_alias


class DevWhatsappAnalysisSegment(models.AbstractModel):
    _name = "dev.whatsapp.analysis.segment"
    _description = "WhatsApp AI message segmentation helpers"

    @api.model
    def _primary_alias_project_ids(self, text):
        """Return set of project ids matched by aliases in text (strong hits)."""
        Alias = self.env["dev.project.alias"].sudo()
        hay = normalize_alias(text or "")
        if not hay:
            return set()
        hits = Alias.match_text(text or "", limit=5)
        return {a.dev_project_id.id for a in hits if a.dev_project_id}

    @api.model
    def _alias_switch(self, prev_projects, curr_projects):
        """True when current message introduces a different project alias set."""
        if not prev_projects or not curr_projects:
            return False
        # Switch only when sets are non-empty and disjoint
        return bool(prev_projects.isdisjoint(curr_projects))

    @api.model
    def segment_messages(self, messages, max_per_segment=12, gap_minutes=45):
        """Split messages into coherent segments (deterministic).

        Boundaries:
        - time gap > gap_minutes
        - max messages per segment
        - explicit project-alias switch (different non-overlapping alias sets)
        """
        if not messages:
            return []
        ordered = messages.sorted(
            key=lambda m: (m.message_timestamp or fields.Datetime.now(), m.id)
        )
        segments = []
        current = self.env["whatsapp.message"]
        last_ts = None
        segment_alias_projects = set()
        for msg in ordered:
            ts = msg.message_timestamp or fields.Datetime.now()
            msg_aliases = self._primary_alias_project_ids(msg.body or "")
            split = False
            if current and last_ts and (ts - last_ts) > timedelta(minutes=gap_minutes):
                split = True
            elif current and len(current) >= max_per_segment:
                split = True
            elif current and self._alias_switch(segment_alias_projects, msg_aliases):
                split = True
            if split:
                segments.append(current)
                current = self.env["whatsapp.message"]
                segment_alias_projects = set()
            current |= msg
            if msg_aliases:
                # Accumulate aliases for the open segment (same-project repeats OK)
                if not segment_alias_projects:
                    segment_alias_projects = set(msg_aliases)
                else:
                    segment_alias_projects |= msg_aliases
            last_ts = ts
        if current:
            segments.append(current)
        return segments or [messages]
