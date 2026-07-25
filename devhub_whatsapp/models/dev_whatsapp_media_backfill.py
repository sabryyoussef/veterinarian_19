# -*- coding: utf-8 -*-
"""Guarded deterministic selection for controlled WhatsApp media backfills."""
from __future__ import annotations

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from .dev_whatsapp_historical_guard import CTX_NON_MUTATING


class DevWhatsappMediaBackfill(models.AbstractModel):
    _name = "dev.whatsapp.media.backfill"
    _description = "WhatsApp Media Controlled Backfill"

    SUPPORTED_MEDIA_TYPES = ("image", "audio", "video")
    TERMINAL_RETRIEVAL_STATES = ("expired", "unavailable", "failed")
    OPEN_JOB_STATES = ("pending", "leased", "processing", "retry")

    @api.model
    def _require_manager(self):
        if not self.env.is_superuser() and not self.env.user.has_group(
            "devhub_core.group_dev_hub_manager"
        ):
            raise AccessError("Controlled media backfill requires Dev Hub manager rights.")

    @api.model
    def _parse_window(self, start_at, end_at):
        start = fields.Datetime.to_datetime(start_at)
        end = fields.Datetime.to_datetime(end_at)
        if not start or not end:
            raise ValidationError("Both start_at and end_at are required.")
        if start > end:
            raise ValidationError("start_at must be before end_at.")
        if (end - start).total_seconds() > (7 * 24 * 60 * 60 + 1):
            raise ValidationError("Controlled backfill window cannot exceed seven days.")
        return start, end

    @api.model
    def eligible_sources(self):
        """Return authoritative review-approved sources in deterministic order."""
        Source = self.env["dev.whatsapp.source"].sudo()
        sources = Source.search(
            [
                ("active", "=", True),
                ("historical_review_enabled", "=", True),
            ]
        )
        return sources.filtered(
            lambda s: (
                s.historical_review_lane == "confirmed_single"
                and s.project_mapping_state == "confirmed"
                and bool(s.dev_project_id)
            )
            or (
                s.historical_review_lane == "multi_project"
                and s.project_mapping_state == "ambiguous"
                and not s.ai_triage_enabled
                and s.require_human_confirm
            )
        ).sorted(
            lambda s: (
                {
                    "ASTA": 1,
                    "AZONE": 2,
                    "CYCLEX": 3,
                    "TOURZ": 4,
                    "PETSPOT": 5,
                }.get(s.dev_project_id.code or "", 9)
                if s.historical_review_lane != "multi_project"
                else 6,
                s.id,
            )
        )

    @api.model
    def _candidate_messages(
        self, start_at, end_at, source_ids=None, media_type=None
    ):
        start, end = self._parse_window(start_at, end_at)
        sources = self.eligible_sources()
        if source_ids:
            requested = {int(source_id) for source_id in source_ids}
            invalid = requested - set(sources.ids)
            if invalid:
                raise UserError(
                    "Sources are not eligible for historical media review: %s"
                    % sorted(invalid)
                )
            sources = sources.filtered(lambda source: source.id in requested)
        media_types = (
            [media_type] if media_type else list(self.SUPPORTED_MEDIA_TYPES)
        )
        if any(kind not in self.SUPPORTED_MEDIA_TYPES for kind in media_types):
            raise ValidationError(
                "Supported controlled-backfill types are image, audio, and video."
            )
        if not sources:
            return self.env["whatsapp.message"], {}

        # dh_source_id is computed from group_jid and has a guarded search method.
        source_domain = [("dh_source_id", "in", list(sources.ids))]
        base_domain = [
            ("message_timestamp", ">=", start),
            ("message_timestamp", "<=", end),
            ("has_media", "=", True),
            ("media_kind", "in", media_types),
            ("evolution_message_id", "!=", False),
        ]
        messages = (
            self.env["whatsapp.message"]
            .sudo()
            .search(
                base_domain + source_domain,
                order="message_timestamp asc, id asc",
            )
        )
        source_by_id = {source.id: source for source in sources}
        source_by_jid = {source.group_jid: source for source in sources}
        return messages, {
            message.id: (
                source_by_id.get(message.dh_source_id.id)
                or source_by_jid.get(message.group_jid)
            )
            for message in messages
        }

    @api.model
    def dry_run(self, start_at, end_at, source_ids=None, media_type=None):
        """Return selected and excluded messages without writing any records."""
        self._require_manager()
        messages, source_map = self._candidate_messages(
            start_at, end_at, source_ids=source_ids, media_type=media_type
        )
        Media = self.env["dev.whatsapp.media"].sudo()
        Job = self.env["dev.whatsapp.media.job"].sudo()
        selected = []
        excluded = []
        for message in messages:
            source = source_map.get(message.id)
            instance = (message.instance_reference or "sabry min").strip()
            identity_media = Media.search(
                [
                    ("source_provider", "=", "evolution"),
                    ("source_instance", "=", instance),
                    ("source_media_id", "=", message.evolution_message_id),
                    ("media_asset_index", "=", 0),
                ],
                limit=1,
            )
            reason = False
            if (
                identity_media.retrieval_state == "downloaded"
                and identity_media.attachment_id
            ):
                reason = "already_downloaded"
            elif identity_media.retrieval_state in self.TERMINAL_RETRIEVAL_STATES:
                reason = "terminal_%s" % identity_media.retrieval_state
            elif identity_media and Job.search_count(
                [
                    ("media_id", "=", identity_media.id),
                    ("kind", "=", "media_download"),
                    ("state", "in", self.OPEN_JOB_STATES),
                ]
            ):
                reason = "open_download_job"
            item = {
                "source_id": source.id,
                "source_name": source.name,
                "review_lane": source.historical_review_lane,
                "project_code": source.dev_project_id.code or "",
                "message_id": message.id,
                "message_timestamp": fields.Datetime.to_string(
                    message.message_timestamp
                ),
                "media_type": message.media_kind,
                "existing_media_id": identity_media.id or None,
            }
            if reason:
                item["reason"] = reason
                excluded.append(item)
            else:
                selected.append(item)
        return {
            "start_at": fields.Datetime.to_string(
                fields.Datetime.to_datetime(start_at)
            ),
            "end_at": fields.Datetime.to_string(fields.Datetime.to_datetime(end_at)),
            "selected": selected,
            "excluded": excluded,
            "selected_count": len(selected),
            "excluded_count": len(excluded),
        }

    @api.model
    def enqueue_batch(
        self,
        start_at,
        end_at,
        source_ids,
        media_type,
        limit=50,
        run_ref=None,
    ):
        """Idempotently enqueue one controlled source/type batch.

        This method never changes message inbox state or Work Item relations.
        """
        self._require_manager()
        limit = max(1, min(int(limit or 50), 50))
        dry = self.dry_run(
            start_at,
            end_at,
            source_ids=source_ids,
            media_type=media_type,
        )
        selected = dry["selected"][:limit]
        Message = self.env["whatsapp.message"].sudo().with_context(
            **{CTX_NON_MUTATING: True}
        )
        Media = self.env["dev.whatsapp.media"].sudo().with_context(
            **{CTX_NON_MUTATING: True}
        )
        Job = self.env["dev.whatsapp.media.job"].sudo().with_context(
            **{CTX_NON_MUTATING: True}
        )
        enqueued = []
        for item in selected:
            message = Message.browse(item["message_id"]).exists()
            if not message:
                continue
            inbox_before = message.inbox_state
            work_before = tuple(message.work_item_ids.ids)
            media = Media._ensure_for_message(
                message, is_historical_review=True
            )
            job = Job._enqueue_download(media)
            message.invalidate_recordset(["inbox_state", "work_item_ids"])
            if (
                message.inbox_state != inbox_before
                or tuple(message.work_item_ids.ids) != work_before
            ):
                raise UserError(
                    "Safety violation: backfill enqueue mutated message %s."
                    % message.id
                )
            if job:
                enqueued.append(
                    {
                        "message_id": message.id,
                        "media_id": media.id,
                        "job_id": job.id,
                        "media_type": media.media_type,
                        "source_id": item["source_id"],
                        "run_ref": (run_ref or "")[:100],
                    }
                )
        return {
            "start_at": dry["start_at"],
            "end_at": dry["end_at"],
            "requested_count": len(selected),
            "enqueued_count": len(enqueued),
            "enqueued": enqueued,
        }
