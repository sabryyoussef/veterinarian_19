# -*- coding: utf-8 -*-
"""Lease queue for WhatsApp media download jobs (separate from analysis)."""
from __future__ import annotations

import base64
import json
import random
import uuid
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from .dev_whatsapp_historical_guard import CTX_NON_MUTATING
from .dev_whatsapp_media_utils import (
    classify_evolution_error,
    idempotency_key,
    reconstruct_evolution_key,
)


def _uuid(*_a):
    return str(uuid.uuid4())


def _require_media_service(env):
    if not env.is_superuser() and not env.user.has_group(
        "devhub_whatsapp.group_dev_hub_wa_media_service"
    ):
        raise AccessError(
            "This operation requires the Dev Hub WhatsApp Media Service role."
        )


def _lease_expiry(seconds):
    seconds = max(30, min(int(seconds or 600), 3600))
    return fields.Datetime.now() + timedelta(seconds=seconds)


class DevWhatsappMediaJob(models.Model):
    _name = "dev.whatsapp.media.job"
    _description = "WhatsApp Media Job"
    _order = "requested_at desc, id desc"

    media_id = fields.Many2one(
        "dev.whatsapp.media",
        required=True,
        ondelete="cascade",
        index=True,
        readonly=True,
    )
    whatsapp_message_id = fields.Many2one(
        related="media_id.whatsapp_message_id",
        store=True,
        index=True,
        readonly=True,
    )
    kind = fields.Selection(
        [
            ("media_download", "Media Download"),
            ("image_ocr", "Image OCR"),
            ("audio_transcription", "Audio Transcription"),
            ("video_audio_extraction", "Video Audio Extraction"),
            ("video_keyframe_extraction", "Video Keyframe Extraction"),
            ("video_enrichment", "Video Enrichment"),
        ],
        required=True,
        default="media_download",
        readonly=True,
        index=True,
    )
    state = fields.Selection(
        [
            ("pending", "Pending"),
            ("leased", "Leased"),
            ("processing", "Processing"),
            ("retry", "Retrying"),
            ("dead_letter", "Dead Letter"),
            ("succeeded", "Succeeded"),
            ("cancelled", "Cancelled"),
        ],
        default="pending",
        required=True,
        readonly=True,
        index=True,
    )
    correlation_id = fields.Char(
        required=True, default=_uuid, index=True, readonly=True, copy=False
    )
    idempotency_key = fields.Char(required=True, index=True, readonly=True)
    payload_json = fields.Text(required=True, readonly=True)
    provider_response_json = fields.Text(readonly=True)
    requested_at = fields.Datetime(
        default=fields.Datetime.now, required=True, readonly=True, index=True
    )
    lease_owner_id = fields.Many2one("res.users", readonly=True)
    lease_consumer_ref = fields.Char(readonly=True)
    lease_token = fields.Char(readonly=True, copy=False, index=True)
    lease_version = fields.Integer(default=0, required=True, readonly=True)
    leased_at = fields.Datetime(readonly=True)
    lease_expires_at = fields.Datetime(readonly=True, index=True)
    processing_at = fields.Datetime(readonly=True)
    completed_at = fields.Datetime(readonly=True)
    attempt_count = fields.Integer(default=0, readonly=True)
    max_attempts = fields.Integer(default=3, required=True, readonly=True)
    next_attempt_at = fields.Datetime(
        default=fields.Datetime.now, required=True, readonly=True, index=True
    )
    last_error_code = fields.Char(readonly=True)
    last_error_summary = fields.Char(readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("dev_wa_media_internal"):
            raise AccessError("Media jobs may be created only by guarded enqueue.")
        for values in vals_list:
            if values.get("state", "pending") != "pending":
                raise ValidationError("Jobs must start Pending.")
        return super().create(vals_list)

    def write(self, values):
        if not self.env.context.get("dev_wa_media_action"):
            raise AccessError("Media jobs change only through guarded callbacks.")
        return super().write(values)

    def unlink(self):
        raise AccessError("Media jobs cannot be deleted.")

    @api.model
    def _enqueue_download(self, media, force=False):
        media.ensure_one()
        key = idempotency_key(
            media.source_provider,
            media.source_instance or "",
            media.source_media_id or "",
            media.media_asset_index,
        )
        existing = self.search(
            [
                ("idempotency_key", "=", key),
                ("kind", "=", "media_download"),
                ("state", "in", ["pending", "leased", "processing", "retry"]),
            ],
            limit=1,
        )
        if existing and not force:
            return existing
        if (
            not force
            and media.retrieval_state == "downloaded"
            and media.attachment_id
        ):
            return self.browse()
        message = media.whatsapp_message_id
        evo_key = reconstruct_evolution_key(message)
        payload = {
            "media_id": media.id,
            "message_id": message.id,
            "kind": "media_download",
            "media_type": media.media_type,
            "source_provider": media.source_provider,
            "source_instance": media.source_instance,
            "source_media_id": media.source_media_id,
            "evolution_key": evo_key,
            "is_historical_review": bool(media.is_historical_review),
            # Never mutate inbox / work items from media path
            "safety": {
                "no_inbox_mutation": True,
                "no_work_item_mutation": True,
                "no_openproject": True,
            },
        }
        return self.with_context(dev_wa_media_internal=True).create(
            {
                "media_id": media.id,
                "kind": "media_download",
                "idempotency_key": f"{key}|download|{_uuid()[:8]}" if force else key,
                "payload_json": json.dumps(payload, separators=(",", ":")),
                "state": "pending",
                "max_attempts": 3,
            }
        )

    ENRICHMENT_KINDS = (
        "image_ocr",
        "audio_transcription",
        "video_audio_extraction",
        "video_keyframe_extraction",
        "video_enrichment",
    )
    VIDEO_SUB_KINDS = ("video_audio_extraction", "video_keyframe_extraction")
    WHISPER_KINDS = ("audio_transcription", "video_audio_extraction")
    PROVIDER_ERROR_CODES = (
        "provider_outage",
        "provider_auth_failed",
        "provider_rate_limited",
        "transcription_failed",
    )

    @api.model
    def _transcription_circuit_open(self):
        """Return True when Whisper provider failure rate exceeds threshold."""
        ICP = self.env["ir.config_parameter"].sudo()
        force_closed = ICP.get_param(
            "devhub_whatsapp.media_transcription_circuit_force_closed_until"
        )
        if force_closed:
            try:
                closed_until = fields.Datetime.to_datetime(force_closed)
                if closed_until and closed_until > fields.Datetime.now():
                    return False
            except Exception:
                pass
        until = ICP.get_param("devhub_whatsapp.media_transcription_circuit_open_until")
        if until:
            try:
                until_dt = fields.Datetime.to_datetime(until)
                if until_dt and until_dt > fields.Datetime.now():
                    return True
            except Exception:
                pass
        window = int(
            ICP.get_param("devhub_whatsapp.media_transcription_circuit_window", "20")
            or 20
        )
        threshold = float(
            ICP.get_param(
                "devhub_whatsapp.media_transcription_circuit_threshold_pct", "10"
            )
            or 10
        )
        lookback = int(
            ICP.get_param(
                "devhub_whatsapp.media_transcription_circuit_lookback_sec", "3600"
            )
            or 3600
        )
        # Allow short lookbacks in tests; production ICP defaults remain hours.
        since = fields.Datetime.now() - timedelta(seconds=max(1, lookback))
        recent = self.search(
            [
                ("kind", "in", list(self.WHISPER_KINDS)),
                ("state", "in", ["retry", "dead_letter", "succeeded"]),
                ("write_date", ">=", since),
                ("attempt_count", ">", 0),
            ],
            order="id desc",
            limit=max(1, window),
        )
        if not recent:
            return False
        failures = recent.filtered(
            lambda job: (job.last_error_code or "") in self.PROVIDER_ERROR_CODES
            or (
                job.state in ("retry", "dead_letter")
                and (job.last_error_code or "").startswith("provider_")
            )
        )
        rate = 100.0 * len(failures) / float(len(recent))
        if rate > threshold:
            cooldown = int(
                ICP.get_param(
                    "devhub_whatsapp.media_transcription_circuit_cooldown_sec",
                    "900",
                )
                or 900
            )
            open_until = fields.Datetime.now() + timedelta(seconds=max(60, cooldown))
            ICP.set_param(
                "devhub_whatsapp.media_transcription_circuit_open_until",
                fields.Datetime.to_string(open_until),
            )
            ICP.set_param(
                "devhub_whatsapp.media_transcription_circuit_last_rate",
                "%.1f" % rate,
            )
            return True
        return False

    @api.model
    def _provider_backoff_seconds(self, attempt_count, provider_response=None):
        """Exponential backoff with jitter; honor Retry-After when present."""
        attempt = max(int(attempt_count or 1), 1)
        base = min(900, 30 * (2 ** max(attempt - 1, 0)))
        jitter = random.randint(0, min(30, base // 3 or 1))
        retry_after = 0
        if isinstance(provider_response, dict):
            raw = provider_response.get("retry_after") or provider_response.get(
                "Retry-After"
            )
            try:
                retry_after = int(float(raw))
            except (TypeError, ValueError):
                retry_after = 0
        return max(base + jitter, retry_after)

    @api.model
    def _enrichment_kinds_for_media(self, media):
        """Return the initial enrichment job kinds required for a media row."""
        return {
            "image": ["image_ocr"],
            "audio": ["audio_transcription"],
            "video": list(self.VIDEO_SUB_KINDS),
        }.get(media.media_type or "", [])

    @api.model
    def _enrichment_eligible(self, media):
        """Guard: only downloaded media with an attachment may be enriched."""
        if media.retrieval_state != "downloaded" or not media.attachment_id:
            return False, "media_not_downloaded"
        if media.media_type not in ("image", "audio", "video"):
            return False, "unsupported_media_type"
        mime = (media.mime_type or "").lower()
        if mime.startswith("application/") or mime in ("", "application/zip"):
            return False, "blocked_mime"
        return True, ""

    @api.model
    def _enqueue_enrichment(self, media, force=False):
        """Enqueue type-specific enrichment jobs for a downloaded media row."""
        media.ensure_one()
        ok, reason = self._enrichment_eligible(media)
        if not ok:
            if media.enrichment_state == "pending":
                media.write(
                    {
                        "enrichment_state": "skipped",
                        "enrichment_error_code": reason,
                    }
                )
            return self.browse()
        if not force and media.enrichment_state in ("succeeded", "partial"):
            return self.browse()
        jobs = self.browse()
        for kind in self._enrichment_kinds_for_media(media):
            jobs |= self._enqueue_enrichment_kind(media, kind, force=force)
        if jobs and (
            force
            or media.enrichment_state
            in ("pending", "failed", "manual_review", "skipped")
        ):
            vals = {"enrichment_state": "pending", "enrichment_error_code": False}
            if force:
                vals.update(
                    {
                        "needs_manual_review": False,
                        "enrichment_error_message": False,
                        "raw_enrichment_json": False
                        if media.media_type == "video"
                        else media.raw_enrichment_json,
                    }
                )
            media.write(vals)
        return jobs

    @api.model
    def _enqueue_enrichment_kind(self, media, kind, force=False, extra_payload=None):
        base_key = idempotency_key(
            media.source_provider,
            media.source_instance or "",
            media.source_media_id or "",
            media.media_asset_index,
        )
        key = f"{base_key}|{kind}"
        existing = self.search(
            [
                ("idempotency_key", "=", key),
                ("kind", "=", kind),
                ("state", "in", ["pending", "leased", "processing", "retry"]),
            ],
            limit=1,
        )
        if existing:
            return existing
        if not force:
            done = self.search(
                [
                    ("idempotency_key", "=", key),
                    ("kind", "=", kind),
                    ("state", "=", "succeeded"),
                ],
                limit=1,
            )
            if done:
                return self.browse()
        get_param = self.env["ir.config_parameter"].sudo().get_param
        payload = {
            "media_id": media.id,
            "message_id": media.whatsapp_message_id.id,
            "kind": kind,
            "media_type": media.media_type,
            "mime_type": media.mime_type,
            "filename": media.filename,
            "file_size": media.file_size,
            "attachment_id": media.attachment_id.id,
            "is_historical_review": bool(media.is_historical_review),
            "limits": {
                "audio_max_seconds": int(
                    get_param("devhub_whatsapp.media_audio_max_seconds", "600")
                ),
                "video_max_seconds": int(
                    get_param("devhub_whatsapp.media_video_max_seconds", "180")
                ),
                "video_max_keyframes": int(
                    get_param("devhub_whatsapp.media_video_max_keyframes", "10")
                ),
            },
            "safety": {
                "no_inbox_mutation": True,
                "no_work_item_mutation": True,
                "no_openproject": True,
                "extracted_text_is_untrusted": True,
            },
        }
        if extra_payload:
            payload.update(extra_payload)
        return self.with_context(dev_wa_media_internal=True).create(
            {
                "media_id": media.id,
                "kind": kind,
                "idempotency_key": f"{key}|{_uuid()[:8]}" if force else key,
                "payload_json": json.dumps(payload, separators=(",", ":")),
                "state": "pending",
                "max_attempts": 3,
            }
        )

    @api.model
    def _maybe_enqueue_video_final(self, media):
        """When both video sub-jobs are terminal, enqueue video_enrichment.

        Requires at least one succeeded sub-job; if both dead-lettered the
        media enrichment is marked failed instead.
        """
        media.ensure_one()
        subs = {}
        for kind in self.VIDEO_SUB_KINDS:
            job = self.search(
                [("media_id", "=", media.id), ("kind", "=", kind)],
                order="id desc",
                limit=1,
            )
            if not job or job.state not in ("succeeded", "dead_letter", "cancelled"):
                return self.browse()
            subs[kind] = job
        succeeded = [k for k, j in subs.items() if j.state == "succeeded"]
        if not succeeded:
            media.write(
                {
                    "enrichment_state": "failed",
                    "enrichment_error_code": "video_subjobs_failed",
                    "enrichment_error_message": "Both video sub-jobs failed.",
                    "needs_manual_review": True,
                    "enrichment_completed_at": fields.Datetime.now(),
                }
            )
            return self.browse()
        partials = media._get_video_partials()
        # force: a fresh sub-job round must always produce a fresh assembly,
        # even when an older video_enrichment job already succeeded.
        return self._enqueue_enrichment_kind(
            media,
            "video_enrichment",
            force=True,
            extra_payload={
                "audio_partial": partials.get("audio") or None,
                "keyframes_partial": partials.get("keyframes") or None,
                "sub_job_states": {k: j.state for k, j in subs.items()},
            },
        )

    @api.model
    def service_lease(self, limit=3, lease_seconds=900, consumer_ref=None):
        _require_media_service(self.env)
        limit = max(1, min(int(limit or 3), 10))
        now = fields.Datetime.now()
        expired = self.search(
            [
                ("state", "in", ["leased", "processing"]),
                ("lease_expires_at", "<=", now),
            ],
            limit=50,
        )
        for record in expired:
            if record.attempt_count >= record.max_attempts:
                record.with_context(dev_wa_media_action=True).write(
                    {
                        "state": "dead_letter",
                        "lease_owner_id": False,
                        "lease_consumer_ref": False,
                        "lease_token": False,
                        "lease_expires_at": False,
                        "last_error_code": "lease_expired",
                        "last_error_summary": "Lease expired on final attempt.",
                    }
                )
                if record.kind == "media_download":
                    record.media_id._mark_retrieval_failure(
                        record.media_id,
                        "lease_expired",
                        "Lease expired on final attempt.",
                    )
                else:
                    record.media_id._mark_enrichment_failure(
                        "lease_expired", "Lease expired on final attempt."
                    )
                    if record.kind in self.VIDEO_SUB_KINDS:
                        self._maybe_enqueue_video_final(record.media_id)
            else:
                backoff = self._provider_backoff_seconds(record.attempt_count)
                record.with_context(dev_wa_media_action=True).write(
                    {
                        "state": "retry",
                        "lease_owner_id": False,
                        "lease_consumer_ref": False,
                        "lease_token": False,
                        "lease_expires_at": False,
                        "next_attempt_at": now + timedelta(seconds=backoff),
                        "last_error_code": "lease_expired",
                        "last_error_summary": "Lease expired before completion.",
                    }
                )

        circuit_open = self._transcription_circuit_open()
        if self.env.context.get("dev_wa_media_bypass_transcription_circuit"):
            circuit_open = False
        candidates = self.search(
            [
                ("state", "in", ["pending", "retry"]),
                ("next_attempt_at", "<=", now),
            ],
            order="next_attempt_at asc, id asc",
            limit=limit * 3,
        )
        leased = []
        for record in candidates:
            if len(leased) >= limit:
                break
            if circuit_open and record.kind in self.WHISPER_KINDS:
                # Leave Whisper jobs pending; download/OCR continue independently.
                continue
            token = _uuid()
            record.with_context(
                dev_wa_media_action=True, **{CTX_NON_MUTATING: True}
            ).write(
                {
                    "state": "leased",
                    "lease_owner_id": self.env.user.id,
                    "lease_consumer_ref": consumer_ref or False,
                    "lease_token": token,
                    "lease_version": record.lease_version + 1,
                    "leased_at": now,
                    "lease_expires_at": _lease_expiry(lease_seconds),
                    "attempt_count": record.attempt_count + 1,
                }
            )
            if record.kind == "media_download":
                record.media_id.with_context(**{CTX_NON_MUTATING: True}).write(
                    {
                        "retrieval_state": "downloading",
                        "retrieval_attempts": record.media_id.retrieval_attempts + 1,
                    }
                )
            else:
                vals = {
                    "enrichment_state": "processing",
                    "enrichment_attempts": record.media_id.enrichment_attempts + 1,
                }
                if not record.media_id.enrichment_started_at:
                    vals["enrichment_started_at"] = now
                record.media_id.with_context(**{CTX_NON_MUTATING: True}).write(vals)
            leased.append(
                {
                    "job_id": record.id,
                    "media_id": record.media_id.id,
                    "message_id": record.whatsapp_message_id.id,
                    "correlation_id": record.correlation_id,
                    "lease_token": token,
                    "lease_version": record.lease_version,
                    "kind": record.kind,
                    "payload_json": record.payload_json,
                    "attempt_count": record.attempt_count,
                    "transcription_circuit_open": bool(circuit_open),
                }
            )
        return {
            "jobs": leased,
            "transcription_circuit_open": bool(circuit_open),
        }

    def _service_record(self, job_id, correlation_id, lease_token):
        record = self.browse(int(job_id)).exists()
        if not record:
            raise UserError("Job not found.")
        if record.correlation_id != correlation_id:
            raise UserError("Correlation mismatch.")
        if record.lease_token != lease_token:
            raise UserError("Invalid lease token.")
        if record.state not in ("leased", "processing"):
            raise UserError(f"Job not in active lease state ({record.state}).")
        if record.lease_expires_at and record.lease_expires_at < fields.Datetime.now():
            raise UserError("Lease expired.")
        return record

    def service_start(self, job_id, correlation_id, lease_token):
        _require_media_service(self.env)
        record = self._service_record(job_id, correlation_id, lease_token)
        record.with_context(dev_wa_media_action=True).write(
            {
                "state": "processing",
                "processing_at": fields.Datetime.now(),
            }
        )
        return {"ok": True, "job_id": record.id}

    def service_complete(self, job_id, correlation_id, lease_token, result):
        """Store downloaded media bytes from worker result.

        result keys:
          - media_bytes_b64 (required on success)
          - mime_type, filename, duration_seconds
          - provider_meta (dict)
        """
        _require_media_service(self.env)
        record = self._service_record(job_id, correlation_id, lease_token)
        if not isinstance(result, dict):
            raise ValidationError("result must be a dict.")
        if record.kind in self.ENRICHMENT_KINDS:
            return self._service_complete_enrichment(record, result)
        b64 = result.get("media_bytes_b64") or ""
        if not b64:
            raise ValidationError("media_bytes_b64 required for successful complete.")
        try:
            raw = base64.b64decode(b64, validate=False)
        except Exception as exc:
            raise ValidationError(f"Invalid base64: {exc}") from exc

        # Snapshot inbox / work links for mutation guard (sudo: service may lack msg ACL)
        msg = record.whatsapp_message_id.sudo()
        inbox_before = getattr(msg, "inbox_state", None)

        meta = result.get("provider_meta") or {}
        store = self.env["dev.whatsapp.media"].sudo()._store_downloaded_bytes(
            record.media_id.sudo(),
            raw=raw,
            reported_mime=result.get("mime_type") or "",
            filename=result.get("filename") or "",
            duration_seconds=result.get("duration_seconds"),
            provider_meta=meta,
        )
        # Drop binary from stored provider response
        safe_meta = {
            k: v
            for k, v in (meta.items() if isinstance(meta, dict) else [])
            if k not in ("base64", "data", "media_bytes_b64", "apikey")
        }
        record.with_context(dev_wa_media_action=True).write(
            {
                "state": "succeeded",
                "completed_at": fields.Datetime.now(),
                "lease_token": False,
                "lease_expires_at": False,
                "provider_response_json": json.dumps(
                    {
                        "ok": True,
                        "store": {
                            k: store[k]
                            for k in store
                            if k != "provider_meta"
                        },
                        "provider_meta": safe_meta,
                    },
                    separators=(",", ":"),
                ),
                "last_error_code": False,
                "last_error_summary": False,
            }
        )
        msg.invalidate_recordset()
        inbox_after = getattr(msg, "inbox_state", None)
        if inbox_before != inbox_after:
            raise UserError("Safety violation: inbox_state mutated during media store.")
        enabled = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("devhub_whatsapp.media_enrichment_enabled", "False")
        )
        if str(enabled).strip().lower() in ("1", "true", "yes"):
            self.sudo()._enqueue_enrichment(record.media_id.sudo())
        return {"ok": True, **store}

    def _service_complete_enrichment(self, record, result):
        """Store an enrichment result from the worker.

        result keys:
          - enrichment (dict, required): kind-specific enrichment JSON
          - provider (str), model (str), prompt_version (str)
          - duration_ms (number), provider_meta (dict)
        """
        enrichment = result.get("enrichment")
        if not isinstance(enrichment, dict):
            raise ValidationError("enrichment dict required for enrichment complete.")
        for forbidden in ("media_bytes_b64", "base64", "data_b64"):
            if forbidden in enrichment or forbidden in result:
                raise ValidationError("Binary payloads are not allowed in enrichment.")

        msg = record.whatsapp_message_id.sudo()
        inbox_before = getattr(msg, "inbox_state", None)

        media = record.media_id.sudo()
        state = self.env["dev.whatsapp.media"].sudo()._store_enrichment_result(
            media,
            record.kind,
            enrichment,
            provider=result.get("provider") or "",
            model=result.get("model") or "",
            prompt_version=result.get("prompt_version") or "",
        )
        meta = result.get("provider_meta") or {}
        safe_meta = {
            k: v
            for k, v in (meta.items() if isinstance(meta, dict) else [])
            if k not in ("base64", "data", "media_bytes_b64", "apikey", "api_key")
        }
        record.with_context(dev_wa_media_action=True).write(
            {
                "state": "succeeded",
                "completed_at": fields.Datetime.now(),
                "lease_token": False,
                "lease_expires_at": False,
                "provider_response_json": json.dumps(
                    {
                        "ok": True,
                        "kind": record.kind,
                        "enrichment_state": state,
                        "duration_ms": result.get("duration_ms"),
                        "provider": result.get("provider") or "",
                        "model": result.get("model") or "",
                        "provider_meta": safe_meta,
                    },
                    separators=(",", ":"),
                ),
                "last_error_code": False,
                "last_error_summary": False,
            }
        )
        if record.kind in self.VIDEO_SUB_KINDS:
            self._maybe_enqueue_video_final(media)
        msg.invalidate_recordset()
        if inbox_before != getattr(msg, "inbox_state", None):
            raise UserError(
                "Safety violation: inbox_state mutated during enrichment store."
            )
        return {
            "ok": True,
            "job_id": record.id,
            "media_id": media.id,
            "enrichment_state": state,
        }

    def service_fail(
        self,
        job_id,
        correlation_id,
        lease_token,
        error_code=None,
        error_summary=None,
        provider_response=None,
        retryable=True,
    ):
        _require_media_service(self.env)
        record = self._service_record(job_id, correlation_id, lease_token)
        if record.kind in self.ENRICHMENT_KINDS:
            return self._service_fail_enrichment(
                record, error_code, error_summary, provider_response, retryable
            )
        code = classify_evolution_error(
            None, f"{error_code or ''} {error_summary or ''}"
        )
        if error_code in (
            "expired",
            "unavailable",
            "authentication_failed",
            "invalid_key",
            "unsupported",
            "corrupt",
            "file_too_large",
            "mime_rejected",
        ):
            code = error_code
        summary = (error_summary or error_code or "media_download_failed")[:500]
        safe_resp = ""
        if provider_response is not None:
            try:
                raw = (
                    provider_response
                    if isinstance(provider_response, str)
                    else json.dumps(provider_response)
                )
                # strip likely secrets
                safe_resp = raw.replace("apikey", "[redacted]")[:2000]
            except Exception:
                safe_resp = ""

        terminal = (not retryable) or code in (
            "expired",
            "unavailable",
            "authentication_failed",
            "invalid_key",
            "unsupported",
            "mime_rejected",
            "file_too_large",
            "corrupt",
        )
        now = fields.Datetime.now()
        exhausted = record.attempt_count >= record.max_attempts
        if terminal or exhausted:
            record.with_context(dev_wa_media_action=True).write(
                {
                    "state": "dead_letter",
                    "completed_at": now,
                    "lease_token": False,
                    "lease_expires_at": False,
                    "last_error_code": code,
                    "last_error_summary": summary,
                    "provider_response_json": safe_resp or False,
                }
            )
            record.media_id._mark_retrieval_failure(record.media_id, code, summary)
        else:
            backoff = min(900, 30 * (2 ** max(record.attempt_count - 1, 0)))
            record.with_context(dev_wa_media_action=True).write(
                {
                    "state": "retry",
                    "lease_owner_id": False,
                    "lease_consumer_ref": False,
                    "lease_token": False,
                    "lease_expires_at": False,
                    "next_attempt_at": now + timedelta(seconds=backoff),
                    "last_error_code": code,
                    "last_error_summary": summary,
                    "provider_response_json": safe_resp or False,
                }
            )
            record.media_id.write({"retrieval_state": "pending"})
        return {
            "ok": True,
            "job_id": record.id,
            "state": record.state,
            "error_code": code,
        }

    TERMINAL_ENRICHMENT_ERRORS = (
        "unsupported_media_type",
        "blocked_mime",
        "file_missing",
        "attachment_missing",
        "duration_exceeded",
        "corrupt_media",
    )

    def _service_fail_enrichment(
        self, record, error_code, error_summary, provider_response, retryable
    ):
        code = (error_code or "enrichment_failed")[:64]
        summary = (error_summary or code)[:500]
        safe_resp = ""
        if provider_response is not None:
            try:
                raw = (
                    provider_response
                    if isinstance(provider_response, str)
                    else json.dumps(provider_response)
                )
                safe_resp = raw.replace("apikey", "[redacted]")[:2000]
            except Exception:
                safe_resp = ""
        now = fields.Datetime.now()
        terminal = (not retryable) or code in self.TERMINAL_ENRICHMENT_ERRORS
        exhausted = record.attempt_count >= record.max_attempts
        if terminal or exhausted:
            record.with_context(dev_wa_media_action=True).write(
                {
                    "state": "dead_letter",
                    "completed_at": now,
                    "lease_token": False,
                    "lease_expires_at": False,
                    "last_error_code": code,
                    "last_error_summary": summary,
                    "provider_response_json": safe_resp or False,
                }
            )
            record.media_id._mark_enrichment_failure(code, summary)
            if record.kind in self.VIDEO_SUB_KINDS:
                self._maybe_enqueue_video_final(record.media_id)
        else:
            backoff = self._provider_backoff_seconds(
                record.attempt_count,
                provider_response
                if isinstance(provider_response, dict)
                else None,
            )
            record.with_context(dev_wa_media_action=True).write(
                {
                    "state": "retry",
                    "lease_owner_id": False,
                    "lease_consumer_ref": False,
                    "lease_token": False,
                    "lease_expires_at": False,
                    "next_attempt_at": now + timedelta(seconds=backoff),
                    "last_error_code": code,
                    "last_error_summary": summary,
                    "provider_response_json": safe_resp or False,
                }
            )
            record.media_id.write({"enrichment_state": "pending"})
            if code in self.PROVIDER_ERROR_CODES:
                # Re-evaluate circuit after recording the provider failure.
                self._transcription_circuit_open()
        return {
            "ok": True,
            "job_id": record.id,
            "state": record.state,
            "error_code": code,
        }
