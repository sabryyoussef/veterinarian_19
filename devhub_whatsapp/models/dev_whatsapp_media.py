# -*- coding: utf-8 -*-
"""Stored WhatsApp media assets retrieved from Evolution (Phase 1)."""
from __future__ import annotations

import base64
import json

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from .dev_whatsapp_media_utils import (
    classify_evolution_error,
    idempotency_key,
    key_json_dumps,
    media_type_from_message,
    mime_family_ok,
    reconstruct_evolution_key,
    safe_filename,
    sha256_hex,
    size_limit_for,
    sniff_mime,
)


class DevWhatsappMedia(models.Model):
    _name = "dev.whatsapp.media"
    _description = "WhatsApp Media Asset"
    _order = "id desc"

    whatsapp_message_id = fields.Many2one(
        "whatsapp.message",
        required=True,
        ondelete="cascade",
        index=True,
    )
    attachment_id = fields.Many2one("ir.attachment", ondelete="set null", index=True)
    thumbnail_attachment_id = fields.Many2one(
        "ir.attachment", ondelete="set null", index=True
    )
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )

    source_provider = fields.Selection(
        [("evolution", "Evolution"), ("chatwoot", "Chatwoot"), ("other", "Other")],
        default="evolution",
        required=True,
        index=True,
    )
    source_media_id = fields.Char(required=True, index=True)
    source_instance = fields.Char(index=True)
    source_key_json = fields.Text()
    media_asset_index = fields.Integer(default=0, required=True)
    media_type = fields.Selection(
        [
            ("image", "Image"),
            ("audio", "Audio"),
            ("video", "Video"),
            ("document", "Document"),
            ("sticker", "Sticker"),
            ("unknown", "Unknown"),
        ],
        required=True,
        default="unknown",
        index=True,
    )
    mime_type = fields.Char()
    filename = fields.Char()
    file_size = fields.Integer()
    duration_seconds = fields.Float()
    checksum = fields.Char(index=True)

    retrieval_state = fields.Selection(
        [
            ("pending", "Pending"),
            ("downloading", "Downloading"),
            ("downloaded", "Downloaded"),
            ("unavailable", "Unavailable"),
            ("expired", "Expired"),
            ("failed", "Failed"),
        ],
        default="pending",
        required=True,
        index=True,
    )
    retrieval_attempts = fields.Integer(default=0)
    retrieved_at = fields.Datetime()
    retrieval_error_code = fields.Char()
    retrieval_error_message = fields.Char()

    # ---- Phase-2 enrichment lifecycle ----
    enrichment_state = fields.Selection(
        [
            ("pending", "Pending"),
            ("processing", "Processing"),
            ("succeeded", "Succeeded"),
            ("partial", "Partial"),
            ("failed", "Failed"),
            ("manual_review", "Manual Review"),
            ("skipped", "Skipped"),
        ],
        default="pending",
        required=True,
        index=True,
    )
    enrichment_provider = fields.Char()
    enrichment_model = fields.Char()
    enrichment_prompt_version = fields.Char()
    enrichment_started_at = fields.Datetime()
    enrichment_completed_at = fields.Datetime()
    enrichment_attempts = fields.Integer(default=0)
    enrichment_error_code = fields.Char()
    enrichment_error_message = fields.Char()
    enrichment_confidence = fields.Float()
    raw_enrichment_json = fields.Text(
        help="Provider output as received. Never overwritten by reviewer corrections."
    )
    validated_enrichment_json = fields.Text()
    technical_terms_json = fields.Text()
    project_hints_json = fields.Text()
    work_item_hints_json = fields.Text()
    needs_manual_review = fields.Boolean(default=False)
    is_historical_review = fields.Boolean(default=False, index=True)

    # ---- Image enrichment ----
    image_description = fields.Text()
    image_extracted_text = fields.Text()
    image_visible_error = fields.Text()
    image_ui_context = fields.Char()
    image_ocr_language = fields.Selection(
        [("ar", "Arabic"), ("en", "English"), ("mixed", "Mixed"), ("unknown", "Unknown")]
    )
    image_ocr_confidence = fields.Float()
    corrected_image_description = fields.Text()
    corrected_image_text = fields.Text()

    # ---- Audio enrichment ----
    audio_transcript = fields.Text()
    audio_language = fields.Selection(
        [("ar", "Arabic"), ("en", "English"), ("mixed", "Mixed"), ("unknown", "Unknown")]
    )
    audio_duration_seconds = fields.Float()
    audio_segments_json = fields.Text()
    audio_unclear_segments_json = fields.Text()
    audio_confidence = fields.Float()
    corrected_audio_transcript = fields.Text()

    # ---- Video enrichment ----
    video_transcript = fields.Text()
    video_language = fields.Selection(
        [("ar", "Arabic"), ("en", "English"), ("mixed", "Mixed"), ("unknown", "Unknown")]
    )
    video_duration_seconds = fields.Float()
    video_keyframes_json = fields.Text()
    video_timeline_json = fields.Text()
    video_visible_errors_json = fields.Text()
    video_reproduction_steps_json = fields.Text()
    video_confidence = fields.Float()
    corrected_video_transcript = fields.Text()
    corrected_video_timeline_json = fields.Text()

    # ---- Reviewer media questionnaire (non-mutating) ----
    review_image_description_ok = fields.Selection(
        [("yes", "Yes"), ("partial", "Partially"), ("no", "No")],
        string="Image description correct?",
    )
    review_image_text_ok = fields.Selection(
        [("yes", "Yes"), ("partial", "Partially"), ("no", "No")],
        string="Extracted text correct?",
    )
    review_image_related = fields.Selection(
        [("yes", "Yes"), ("no", "No"), ("unclear", "Unclear")],
        string="Image related to the request?",
    )
    review_image_error_visible = fields.Selection(
        [("yes", "Yes"), ("no", "No")],
        string="Important error visible?",
    )
    review_image_sufficient = fields.Selection(
        [("yes", "Sufficient"), ("needs_context", "Needs explanation")],
        string="Image sufficient?",
    )
    review_audio_transcript_ok = fields.Selection(
        [("yes", "Yes"), ("partial", "Partially"), ("no", "No")],
        string="Transcript correct?",
    )
    review_audio_unclear_words = fields.Selection(
        [("yes", "Yes"), ("no", "No")],
        string="Unclear words present?",
    )
    review_audio_summary_ok = fields.Selection(
        [("yes", "Yes"), ("partial", "Partially"), ("no", "No")],
        string="Summary reflects speaker request?",
    )
    review_audio_needs_listen = fields.Selection(
        [("yes", "Yes"), ("no", "No")],
        string="Manual listening required?",
    )
    review_audio_terms_ok = fields.Selection(
        [("yes", "Yes"), ("partial", "Partially"), ("no", "No")],
        string="Technical terms correct?",
    )
    review_video_transcript_ok = fields.Selection(
        [("yes", "Yes"), ("partial", "Partially"), ("no", "No")],
        string="Video transcript correct?",
    )
    review_video_timeline_ok = fields.Selection(
        [("yes", "Yes"), ("partial", "Partially"), ("no", "No")],
        string="Timeline correct?",
    )
    review_video_screen_ok = fields.Selection(
        [("yes", "Yes"), ("partial", "Partially"), ("no", "No")],
        string="On-screen content understood?",
    )
    review_video_steps_ok = fields.Selection(
        [("yes", "Yes"), ("partial", "Partially"), ("no", "No"), ("none", "No steps")],
        string="Reproduction steps correct?",
    )
    review_video_multiple_issues = fields.Selection(
        [("yes", "Yes"), ("no", "No")],
        string="Multiple issues in the video?",
    )
    review_video_missed_moment = fields.Char(
        string="Missing important timestamp (mm:ss)"
    )
    media_usefulness_score = fields.Selection(
        [("1", "1"), ("2", "2"), ("3", "3"), ("4", "4"), ("5", "5")],
        string="Media usefulness (1–5)",
    )
    media_final_status = fields.Selection(
        [
            ("accepted", "Accepted"),
            ("corrected", "Corrected"),
            ("insufficient", "Insufficient"),
            ("unavailable", "Unavailable"),
        ],
        string="Media final status",
    )
    media_reprocess_requested = fields.Boolean(default=False)
    media_reviewer_notes = fields.Text()
    media_review_completed_by = fields.Many2one("res.users", readonly=True)
    media_review_completed_at = fields.Datetime(readonly=True)

    identity_key = fields.Char(
        compute="_compute_identity_key",
        store=True,
        index=True,
    )

    _identity_uniq = models.Constraint(
        "unique(source_provider, source_instance, source_media_id, media_asset_index)",
        "Media identity must be unique per provider/instance/media id/asset index.",
    )

    @api.depends(
        "source_provider", "source_instance", "source_media_id", "media_asset_index"
    )
    def _compute_identity_key(self):
        for rec in self:
            rec.identity_key = idempotency_key(
                rec.source_provider,
                rec.source_instance or "",
                rec.source_media_id or "",
                rec.media_asset_index,
            )

    @api.model
    def _ensure_for_message(self, message, *, is_historical_review=False):
        """Create or return pending media row for a Hub message (idempotent)."""
        message.ensure_one()
        evo_id = (message.evolution_message_id or "").strip()
        if not evo_id:
            raise UserError("Message has no evolution_message_id; cannot retrieve media.")
        instance = (message.instance_reference or "sabry min").strip()
        media_type = media_type_from_message(message)
        key = reconstruct_evolution_key(message)
        existing = self.search(
            [
                ("source_provider", "=", "evolution"),
                ("source_instance", "=", instance),
                ("source_media_id", "=", evo_id),
                ("media_asset_index", "=", 0),
            ],
            limit=1,
        )
        if existing:
            vals = {}
            if is_historical_review and not existing.is_historical_review:
                vals["is_historical_review"] = True
            if vals:
                existing.write(vals)
            return existing
        return self.create(
            {
                "whatsapp_message_id": message.id,
                "source_provider": "evolution",
                "source_media_id": evo_id,
                "source_instance": instance,
                "source_key_json": key_json_dumps(key),
                "media_asset_index": 0,
                "media_type": media_type,
                "retrieval_state": "pending",
                "enrichment_state": "pending",
                "is_historical_review": bool(is_historical_review),
                "company_id": self.env.company.id,
            }
        )

    def action_open_attachment(self):
        self.ensure_one()
        if not self.attachment_id:
            raise UserError("No attachment stored for this media record.")
        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/{self.attachment_id.id}?download=true",
            "target": "new",
        }

    def action_queue_download(self):
        Job = self.env["dev.whatsapp.media.job"]
        for rec in self:
            Job._enqueue_download(rec)
        return True

    def action_retry_download(self):
        for rec in self:
            if rec.retrieval_state == "downloaded" and rec.attachment_id:
                continue
            rec.write(
                {
                    "retrieval_state": "pending",
                    "retrieval_error_code": False,
                    "retrieval_error_message": False,
                }
            )
            self.env["dev.whatsapp.media.job"]._enqueue_download(rec, force=True)
        return True

    @api.model
    def _store_downloaded_bytes(
        self,
        media,
        *,
        raw: bytes,
        reported_mime: str = "",
        filename: str = "",
        duration_seconds=None,
        provider_meta=None,
    ):
        """Validate bytes, create/reuse attachment, mark downloaded."""
        media.ensure_one()
        if not raw:
            raise ValidationError("Empty media payload.")
        media_type = media.media_type or "unknown"
        sniffed = sniff_mime(raw)
        reported = (reported_mime or sniffed or "").split(";")[0].strip()
        if not mime_family_ok(media_type, sniffed, reported):
            raise ValidationError(
                f"MIME rejected: sniffed={sniffed} reported={reported} type={media_type}"
            )
        limit = size_limit_for(
            media_type,
            self.env["ir.config_parameter"].sudo().get_param,
        )
        if len(raw) > limit:
            raise ValidationError(f"File too large: {len(raw)} > {limit}")
        checksum = sha256_hex(raw)
        fname = safe_filename(filename, sniffed or reported, media_type)
        mime = sniffed if sniffed != "application/octet-stream" else (reported or sniffed)

        Attachment = self.env["ir.attachment"].sudo()
        # Reuse attachment bytes by our SHA-256 (Odoo attachment.checksum is MD5).
        reuse_media = self.search(
            [
                ("checksum", "=", checksum),
                ("attachment_id", "!=", False),
                ("id", "!=", media.id),
            ],
            limit=1,
        )
        if reuse_media and reuse_media.attachment_id:
            att = reuse_media.attachment_id
            reuse = True
        else:
            reuse = False
            att = Attachment.create(
                {
                    "name": fname,
                    "type": "binary",
                    "datas": base64.b64encode(raw),
                    "res_model": "whatsapp.message",
                    "res_id": media.whatsapp_message_id.id,
                    "mimetype": mime,
                    "public": False,
                    "description": f"dev.whatsapp.media:{media.id}",
                }
            )

        vals = {
            "attachment_id": att.id,
            "mime_type": mime,
            "filename": fname,
            "file_size": len(raw),
            "checksum": checksum,
            "retrieval_state": "downloaded",
            "retrieved_at": fields.Datetime.now(),
            "retrieval_error_code": False,
            "retrieval_error_message": False,
            "enrichment_state": "pending",
        }
        if duration_seconds is not None:
            vals["duration_seconds"] = float(duration_seconds)
        media.write(vals)
        return {
            "media_id": media.id,
            "attachment_id": att.id,
            "checksum": checksum,
            "file_size": len(raw),
            "mime_type": mime,
            "filename": fname,
            "reused_attachment": bool(reuse),
            "provider_meta": provider_meta or {},
        }

    # ------------------------------------------------------------------
    # Phase 2 — enrichment storage and services
    # ------------------------------------------------------------------

    @staticmethod
    def _norm_lang(value):
        value = (value or "").strip().lower()
        if value in ("ar", "arabic", "ara"):
            return "ar"
        if value in ("en", "english", "eng"):
            return "en"
        if value == "mixed":
            return "mixed"
        return "unknown"

    def _mark_enrichment_failure(self, error_code: str, error_message: str):
        self.ensure_one()
        self.write(
            {
                "enrichment_state": "failed",
                "enrichment_error_code": (error_code or "failed")[:64],
                "enrichment_error_message": (error_message or "")[:500],
                "enrichment_completed_at": fields.Datetime.now(),
                "needs_manual_review": True,
            }
        )

    def _get_video_partials(self):
        self.ensure_one()
        try:
            raw = json.loads(self.raw_enrichment_json or "{}")
        except (TypeError, ValueError):
            raw = {}
        return raw if isinstance(raw, dict) else {}

    @api.model
    def _store_enrichment_result(
        self, media, kind, enrichment, *, provider="", model="", prompt_version=""
    ):
        """Persist a worker enrichment result. Returns the enrichment state set.

        Raw provider output is stored append-only; reviewer corrections live in
        separate corrected_* fields and are never touched here.
        """
        media.ensure_one()
        now = fields.Datetime.now()
        wanted_state = enrichment.get("enrichment_state")
        if wanted_state not in ("succeeded", "partial", "manual_review"):
            wanted_state = "partial" if enrichment.get("partial") else "succeeded"
        needs_review = bool(enrichment.get("needs_manual_review"))
        confidence = float(enrichment.get("confidence") or 0.0)

        vals = {
            "enrichment_provider": provider or media.enrichment_provider,
            "enrichment_model": model or media.enrichment_model,
            "enrichment_prompt_version": prompt_version
            or media.enrichment_prompt_version,
            "enrichment_error_code": False,
            "enrichment_error_message": False,
        }
        if enrichment.get("technical_terms"):
            vals["technical_terms_json"] = json.dumps(
                enrichment["technical_terms"], ensure_ascii=False
            )
        if enrichment.get("project_hints"):
            vals["project_hints_json"] = json.dumps(
                enrichment["project_hints"], ensure_ascii=False
            )
        if enrichment.get("work_item_hints"):
            vals["work_item_hints_json"] = json.dumps(
                enrichment["work_item_hints"], ensure_ascii=False
            )

        terminal = True
        if kind == "image_ocr":
            vals.update(
                {
                    "image_description": enrichment.get("description") or "",
                    "image_extracted_text": enrichment.get("extracted_text") or "",
                    "image_visible_error": enrichment.get("visible_error") or "",
                    "image_ui_context": (enrichment.get("ui_context") or "")[:256],
                    "image_ocr_language": self._norm_lang(
                        enrichment.get("ocr_language")
                    ),
                    "image_ocr_confidence": confidence,
                    "raw_enrichment_json": json.dumps(
                        enrichment, ensure_ascii=False, separators=(",", ":")
                    ),
                }
            )
        elif kind == "audio_transcription":
            vals.update(
                {
                    "audio_transcript": enrichment.get("transcript") or "",
                    "audio_language": self._norm_lang(enrichment.get("language")),
                    "audio_duration_seconds": float(
                        enrichment.get("duration_seconds") or 0.0
                    ),
                    "audio_segments_json": json.dumps(
                        enrichment.get("segments") or [], ensure_ascii=False
                    ),
                    "audio_unclear_segments_json": json.dumps(
                        enrichment.get("unclear_segments") or [], ensure_ascii=False
                    ),
                    "audio_confidence": confidence,
                    "raw_enrichment_json": json.dumps(
                        enrichment, ensure_ascii=False, separators=(",", ":")
                    ),
                }
            )
        elif kind == "video_audio_extraction":
            terminal = False
            partials = media._get_video_partials()
            partials["audio"] = enrichment
            vals.update(
                {
                    "video_transcript": enrichment.get("transcript") or "",
                    "video_language": self._norm_lang(enrichment.get("language")),
                    "video_duration_seconds": float(
                        enrichment.get("duration_seconds") or 0.0
                    ),
                    "raw_enrichment_json": json.dumps(
                        partials, ensure_ascii=False, separators=(",", ":")
                    ),
                }
            )
        elif kind == "video_keyframe_extraction":
            terminal = False
            partials = media._get_video_partials()
            partials["keyframes"] = enrichment
            vals.update(
                {
                    "video_keyframes_json": json.dumps(
                        enrichment.get("keyframes") or [], ensure_ascii=False
                    ),
                    "raw_enrichment_json": json.dumps(
                        partials, ensure_ascii=False, separators=(",", ":")
                    ),
                }
            )
        elif kind == "video_enrichment":
            partials = media._get_video_partials()
            partials["final"] = enrichment
            vals.update(
                {
                    "video_timeline_json": json.dumps(
                        enrichment.get("timeline") or [], ensure_ascii=False
                    ),
                    "video_visible_errors_json": json.dumps(
                        enrichment.get("visible_errors") or [], ensure_ascii=False
                    ),
                    "video_reproduction_steps_json": json.dumps(
                        enrichment.get("reproduction_steps") or [], ensure_ascii=False
                    ),
                    "video_confidence": confidence,
                    "raw_enrichment_json": json.dumps(
                        partials, ensure_ascii=False, separators=(",", ":")
                    ),
                }
            )
            if enrichment.get("transcript"):
                vals["video_transcript"] = enrichment["transcript"]
            if enrichment.get("language"):
                vals["video_language"] = self._norm_lang(enrichment.get("language"))
        else:
            raise ValidationError(f"Unknown enrichment kind: {kind}")

        if terminal:
            state = "manual_review" if wanted_state == "manual_review" else wanted_state
            vals.update(
                {
                    "enrichment_state": state,
                    "enrichment_completed_at": now,
                    "enrichment_confidence": confidence
                    or media.enrichment_confidence,
                    "needs_manual_review": needs_review,
                    "validated_enrichment_json": json.dumps(
                        enrichment, ensure_ascii=False, separators=(",", ":")
                    ),
                }
            )
        else:
            state = "processing"
            if needs_review:
                vals["needs_manual_review"] = True
        media.write(vals)
        return state if terminal else "processing"

    @api.model
    def service_fetch_bytes(self, media_id):
        """Return attachment bytes (base64) for the media worker only."""
        if not self.env.is_superuser() and not self.env.user.has_group(
            "devhub_whatsapp.group_dev_hub_wa_media_service"
        ):
            raise AccessError("Media byte fetch requires the media service role.")
        media = self.browse(int(media_id)).exists()
        if not media:
            raise UserError("Media not found.")
        att = media.sudo().attachment_id
        if not att or media.retrieval_state != "downloaded":
            raise UserError("Media has no downloaded attachment.")
        return {
            "media_id": media.id,
            "media_type": media.media_type,
            "mime_type": media.mime_type,
            "filename": media.filename,
            "file_size": media.file_size,
            "duration_seconds": media.duration_seconds,
            "data_b64": (att.datas or b"").decode()
            if isinstance(att.datas, bytes)
            else (att.datas or ""),
        }

    @api.model
    def _enrichment_payload(self, media):
        """Textual enrichment for the Dify payload — never binary."""
        mt = media.media_type
        if mt == "image":
            return {
                "source": "image_ocr",
                "description": (media.corrected_image_description
                                or media.image_description or "")[:1000],
                "extracted_text": (media.corrected_image_text
                                   or media.image_extracted_text or "")[:4000],
                "visible_error": (media.image_visible_error or "")[:1000],
                "ui_context": media.image_ui_context or "",
                "ocr_language": media.image_ocr_language or "unknown",
                "confidence": media.image_ocr_confidence,
                "needs_manual_review": media.needs_manual_review,
            }
        if mt == "audio":
            return {
                "source": "audio_transcript",
                "transcript": (media.corrected_audio_transcript
                               or media.audio_transcript or "")[:6000],
                "language": media.audio_language or "unknown",
                "duration_seconds": media.audio_duration_seconds,
                "unclear_segments": json.loads(
                    media.audio_unclear_segments_json or "[]"
                ),
                "confidence": media.audio_confidence,
                "needs_manual_review": media.needs_manual_review,
            }
        if mt == "video":
            try:
                timeline = json.loads(
                    media.corrected_video_timeline_json
                    or media.video_timeline_json
                    or "[]"
                )
            except (TypeError, ValueError):
                timeline = []
            try:
                visible_errors = json.loads(media.video_visible_errors_json or "[]")
            except (TypeError, ValueError):
                visible_errors = []
            return {
                "source": "video_audio_transcript_and_frame_ocr",
                "transcript": (media.corrected_video_transcript
                               or media.video_transcript or "")[:6000],
                "language": media.video_language or "unknown",
                "duration_seconds": media.video_duration_seconds,
                "timeline": timeline[:20],
                "visible_errors": visible_errors[:10],
                "confidence": media.video_confidence,
                "needs_manual_review": media.needs_manual_review,
            }
        return {}

    @api.model
    def message_media_payload(self, message):
        """media_status + media_items for one Hub message (textual only)."""
        medias = self.sudo().search(
            [("whatsapp_message_id", "=", message.id)], order="id asc"
        )
        if not medias:
            has_media = bool(
                getattr(message, "has_media", False)
                or (getattr(message, "media_kind", "none") or "none") != "none"
            )
            if not has_media:
                return {"media_status": "none", "media_items": []}
            return {
                "media_status": "not_retrieved",
                "media_error": "media_not_downloaded",
                "needs_manual_review": True,
                "media_items": [],
            }
        items = []
        states = set()
        error = ""
        for media in medias:
            if media.retrieval_state in ("expired", "unavailable", "failed"):
                states.add("expired" if media.retrieval_state == "expired" else "failed")
                error = media.retrieval_error_code or media.retrieval_state
                continue
            if media.retrieval_state != "downloaded":
                states.add("pending")
                continue
            est = media.enrichment_state
            if est in ("succeeded", "partial", "manual_review"):
                states.add("partial" if est != "succeeded" else "succeeded")
                items.append(
                    {
                        "media_id": media.id,
                        "media_type": media.media_type,
                        "mime_type": media.mime_type or "",
                        "filename": media.filename or "",
                        "enrichment_state": est,
                        "enrichment": self._enrichment_payload(media),
                    }
                )
            elif est in ("failed", "skipped"):
                states.add("failed")
                error = media.enrichment_error_code or "enrichment_failed"
                items.append(
                    {
                        "media_id": media.id,
                        "media_type": media.media_type,
                        "mime_type": media.mime_type or "",
                        "filename": media.filename or "",
                        "enrichment_state": est,
                        "enrichment": {},
                    }
                )
            else:
                states.add("pending")

        if states == {"succeeded"}:
            status = "succeeded"
        elif "pending" in states:
            status = "pending"
        elif "partial" in states or ("succeeded" in states and "failed" in states):
            status = "partial"
        elif states == {"expired"}:
            status = "expired"
        else:
            status = "failed"
        out = {"media_status": status, "media_items": items}
        if status in ("expired", "failed", "partial", "pending") and error:
            out["media_error"] = error
        if status in ("expired", "failed"):
            out["needs_manual_review"] = True
        return out

    def action_queue_enrichment(self):
        Job = self.env["dev.whatsapp.media.job"]
        for rec in self:
            Job._enqueue_enrichment(rec, force=True)
        return True

    def action_save_media_review(self):
        """Persist reviewer media questionnaire — never mutates inbox/WIs."""
        for rec in self:
            if not rec.media_final_status or not rec.media_usefulness_score:
                raise UserError(
                    "Set Media final status and Media usefulness before saving."
                )
            rec.write(
                {
                    "media_review_completed_by": self.env.user.id,
                    "media_review_completed_at": fields.Datetime.now(),
                }
            )
            if rec.media_reprocess_requested:
                self.env["dev.whatsapp.media.job"]._enqueue_enrichment(
                    rec, force=True
                )
        return True

    @api.model
    def _mark_retrieval_failure(self, media, error_code: str, error_message: str):
        media.ensure_one()
        code = (error_code or "failed")[:64]
        state = {
            "expired": "expired",
            "unavailable": "unavailable",
            "authentication_failed": "failed",
            "invalid_key": "failed",
            "unsupported": "failed",
            "corrupt": "failed",
            "file_too_large": "failed",
            "mime_rejected": "failed",
        }.get(code, "failed")
        media.write(
            {
                "retrieval_state": state,
                "retrieval_error_code": code,
                "retrieval_error_message": (error_message or "")[:500],
                "enrichment_state": "skipped",
                "needs_manual_review": True,
            }
        )


class WhatsappMessageMediaActions(models.Model):
    _inherit = "whatsapp.message"

    media_asset_ids = fields.One2many(
        "dev.whatsapp.media", "whatsapp_message_id", string="Media Assets"
    )
    media_asset_count = fields.Integer(compute="_compute_media_asset_count")

    def _compute_media_asset_count(self):
        Media = self.env["dev.whatsapp.media"]
        for rec in self:
            rec.media_asset_count = Media.search_count(
                [("whatsapp_message_id", "=", rec.id)]
            )

    def action_queue_media_download(self):
        Media = self.env["dev.whatsapp.media"]
        Job = self.env["dev.whatsapp.media.job"]
        for msg in self:
            if not msg.has_media and (msg.media_kind or "none") == "none":
                raise UserError("Message has no media_kind.")
            media = Media._ensure_for_message(msg, is_historical_review=False)
            Job._enqueue_download(media)
        return True

    def action_retry_media_download(self):
        for msg in self:
            media = self.env["dev.whatsapp.media"]._ensure_for_message(msg)
            media.action_retry_download()
        return True
