# -*- coding: utf-8 -*-
"""Lease queue for WhatsApp AI triage jobs (n8n consumer)."""
from __future__ import annotations

from datetime import timedelta
import json
import logging
import uuid

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from .dev_whatsapp_analysis_utils import safe_json_dumps, validate_ai_response

_logger = logging.getLogger(__name__)


def _uuid(*_a):
    return str(uuid.uuid4())


def _require_analysis_service(env):
    if not env.is_superuser() and not env.user.has_group(
        "devhub_whatsapp.group_dev_hub_wa_analysis_service"
    ):
        raise AccessError(
            "This operation requires the Dev Hub WhatsApp Analysis Service role."
        )


def _lease_expiry(seconds):
    seconds = max(30, min(int(seconds or 300), 1800))
    return fields.Datetime.now() + timedelta(seconds=seconds)


class DevWhatsappAnalysisJob(models.Model):
    _name = "dev.whatsapp.analysis.job"
    _description = "WhatsApp AI Analysis Job"
    _order = "requested_at desc, id desc"

    analysis_id = fields.Many2one(
        "dev.whatsapp.analysis",
        required=True,
        ondelete="cascade",
        index=True,
        readonly=True,
    )
    kind = fields.Selection(
        [("wa_group_triage", "WhatsApp Group Triage")],
        required=True,
        default="wa_group_triage",
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
        related="analysis_id.correlation_id", store=True, index=True, readonly=True
    )
    payload_json = fields.Text(required=True, readonly=True)
    response_json = fields.Text(readonly=True)
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
        if not self.env.context.get("dev_wa_analysis_internal"):
            raise AccessError("Analysis jobs may be created only by guarded enqueue.")
        for values in vals_list:
            if values.get("state", "pending") != "pending":
                raise ValidationError("Jobs must start Pending.")
        return super().create(vals_list)

    def write(self, values):
        if not self.env.context.get("dev_wa_analysis_action"):
            raise AccessError("Analysis jobs change only through guarded callbacks.")
        return super().write(values)

    def unlink(self):
        raise AccessError("Analysis jobs cannot be deleted.")

    @api.model
    def service_lease(self, limit=5, lease_seconds=600, consumer_ref=None):
        _require_analysis_service(self.env)
        limit = max(1, min(int(limit or 5), 20))
        now = fields.Datetime.now()
        # Recover expired leases
        expired = self.search(
            [
                ("state", "in", ["leased", "processing"]),
                ("lease_expires_at", "<=", now),
            ],
            limit=50,
        )
        for record in expired:
            attempts = record.attempt_count
            if attempts >= record.max_attempts:
                record.with_context(dev_wa_analysis_action=True).write(
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
                record.analysis_id.write(
                    {
                        "state": "failed",
                        "error_code": "lease_expired",
                        "error_message": "Lease expired on final attempt.",
                    }
                )
            else:
                backoff = min(900, 30 * (2 ** max(attempts - 1, 0)))
                record.with_context(dev_wa_analysis_action=True).write(
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

        candidates = self.search(
            [
                ("state", "in", ["pending", "retry"]),
                ("next_attempt_at", "<=", now),
            ],
            order="next_attempt_at asc, id asc",
            limit=limit,
        )
        leased = []
        for record in candidates:
            # Phase 2I — soft-wait for media enrichment before Dify analysis.
            gate = record._media_softwait_gate(now)
            if gate == "wait":
                record.with_context(dev_wa_analysis_action=True).write(
                    {"next_attempt_at": now + timedelta(seconds=60)}
                )
                continue
            if gate == "refresh":
                try:
                    record.with_context(dev_wa_analysis_action=True).write(
                        {
                            "payload_json": safe_json_dumps(
                                record.analysis_id._job_payload()
                            )
                        }
                    )
                except Exception:
                    _logger.exception(
                        "Media payload refresh failed for analysis job %s", record.id
                    )
            token = _uuid()
            record.with_context(dev_wa_analysis_action=True).write(
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
            record.analysis_id.write(
                {"state": "running", "started_at": record.analysis_id.started_at or now}
            )
            leased.append(
                {
                    "job_id": record.id,
                    "analysis_id": record.analysis_id.id,
                    "correlation_id": record.correlation_id,
                    "lease_token": token,
                    "lease_version": record.lease_version,
                    "kind": record.kind,
                    "payload_json": record.payload_json,
                    "attempt_count": record.attempt_count,
                }
            )
        return {"jobs": leased}

    def _media_softwait_gate(self, now):
        """Soft-wait for media enrichment (Phase 2I).

        Returns:
          - "wait": downloaded media enrichment still running and within the
            configured soft-wait window — postpone leasing.
          - "refresh": media exists and is terminal (or window elapsed) —
            rebuild payload_json so enrichment is included.
          - "proceed": no media involved.
        """
        self.ensure_one()
        analysis = self.analysis_id
        msgs = analysis.batch_message_ids
        if not msgs:
            return "proceed"
        Media = self.env["dev.whatsapp.media"].sudo()
        medias = Media.search([("whatsapp_message_id", "in", msgs.ids)])
        if not medias:
            return "proceed"
        Job = self.env["dev.whatsapp.media.job"].sudo()
        pending = medias.browse()
        for media in medias:
            if media.retrieval_state != "downloaded":
                continue
            if media.enrichment_state in ("pending", "processing"):
                Job._enqueue_enrichment(media)
                if media.enrichment_state in ("pending", "processing"):
                    pending |= media
        if not pending:
            return "refresh"
        get_param = self.env["ir.config_parameter"].sudo().get_param
        has_video = any(m.media_type == "video" for m in pending)
        window = int(
            get_param(
                "devhub_whatsapp.media_softwait_video_sec"
                if has_video
                else "devhub_whatsapp.media_softwait_image_audio_sec",
                "900" if has_video else "300",
            )
        )
        age = (now - (self.requested_at or now)).total_seconds()
        if age < window:
            return "wait"
        return "refresh"

    def _service_record(self, job_id, correlation_id, lease_token):
        record = self.browse(int(job_id)).exists()
        if not record:
            raise UserError("Job not found.")
        if record.correlation_id != correlation_id:
            raise AccessError("Correlation id mismatch.")
        if record.lease_owner_id.id != self.env.user.id:
            raise AccessError("Lease belongs to another identity.")
        if not lease_token or record.lease_token != lease_token:
            raise AccessError("Lease token is stale or invalid.")
        if not record.lease_expires_at or record.lease_expires_at <= fields.Datetime.now():
            raise AccessError("Lease has expired.")
        return record

    @api.model
    def service_start(self, job_id, correlation_id, lease_token):
        _require_analysis_service(self.env)
        record = self._service_record(job_id, correlation_id, lease_token)
        if record.state != "leased":
            raise UserError("Only a leased job can start processing.")
        record.with_context(dev_wa_analysis_action=True).write(
            {"state": "processing", "processing_at": fields.Datetime.now()}
        )
        return {"ok": True, "job_id": record.id}

    @api.model
    def service_complete(self, job_id, correlation_id, lease_token, result):
        """result: {raw_response: str, provider_model?: str} — Odoo validates and applies."""
        _require_analysis_service(self.env)
        record = self._service_record(job_id, correlation_id, lease_token)
        if record.state not in ("leased", "processing"):
            raise UserError("Job is not active.")
        if not isinstance(result, dict):
            raise ValidationError("result must be an object.")
        raw = result.get("raw_response")
        if raw is None and result.get("raw_response_json"):
            raw = result.get("raw_response_json")
        if isinstance(raw, dict):
            raw = json.dumps(raw)
        # Service identity is ACL-gated; sensitive analysis fields are manager-group
        # restricted, so apply/validate under sudo after lease checks succeed.
        analysis = record.analysis_id.sudo()
        try:
            project_ids = []
            wi_ids = []
            if analysis.project_candidates_json:
                project_ids = [
                    c.get("project_id")
                    for c in json.loads(analysis.project_candidates_json or "[]")
                ]
            if analysis.work_item_candidates_json:
                wi_ids = [
                    c.get("work_item_id")
                    for c in json.loads(analysis.work_item_candidates_json or "[]")
                ]
            if not project_ids:
                # Rebuild candidates if missing
                analysis._job_payload()
                project_ids = [
                    c.get("project_id")
                    for c in json.loads(analysis.project_candidates_json or "[]")
                ]
                wi_ids = [
                    c.get("work_item_id")
                    for c in json.loads(analysis.work_item_candidates_json or "[]")
                ]
            validated = validate_ai_response(
                raw,
                analysis.batch_message_ids.ids,
                project_candidate_ids=project_ids,
                work_item_candidate_ids=wi_ids,
            )
            meta = {
                "provider": "dify_n8n",
                "is_demo_result": False,
                "dify_app_ref": result.get("dify_app_ref")
                or result.get("dify_application_id"),
                "dify_workflow_run_id": result.get("dify_workflow_run_id")
                or result.get("workflow_run_id"),
                "n8n_execution_id": result.get("n8n_execution_id"),
                "provider_latency_ms": result.get("provider_latency_ms") or 0,
                "token_usage": result.get("token_usage"),
            }
            analysis.with_context(wa_ai_provider_meta=meta)._apply_validated(
                validated, raw, provider_model=result.get("provider_model") or "dify"
            )
        except ValidationError as err:
            return self.service_fail(
                job_id,
                correlation_id,
                lease_token,
                error_code="invalid_schema",
                error_summary=str(err),
            )
        record.with_context(dev_wa_analysis_action=True).write(
            {
                "state": "succeeded",
                "completed_at": fields.Datetime.now(),
                "response_json": (raw or "")[:200000],
                "lease_owner_id": False,
                "lease_consumer_ref": False,
                "lease_token": False,
                "lease_expires_at": False,
                "last_error_code": False,
                "last_error_summary": False,
            }
        )
        return {"ok": True, "job_id": record.id, "analysis_id": analysis.id, "state": analysis.state}

    @api.model
    def service_fail(
        self,
        job_id,
        correlation_id,
        lease_token,
        error_code=None,
        error_summary=None,
    ):
        _require_analysis_service(self.env)
        record = self._service_record(job_id, correlation_id, lease_token)
        if record.state not in ("leased", "processing"):
            raise UserError("Only an active job can fail.")
        now = fields.Datetime.now()
        code = (error_code or "provider_error")[:64]
        summary = (error_summary or "Provider failure")[:500]
        if record.attempt_count >= record.max_attempts:
            record.with_context(dev_wa_analysis_action=True).write(
                {
                    "state": "dead_letter",
                    "completed_at": now,
                    "lease_owner_id": False,
                    "lease_consumer_ref": False,
                    "lease_token": False,
                    "lease_expires_at": False,
                    "last_error_code": code,
                    "last_error_summary": summary,
                }
            )
            record.analysis_id.write(
                {
                    "state": "failed",
                    "error_code": code,
                    "error_message": summary,
                    "completed_at": now,
                }
            )
        else:
            backoff = min(900, 30 * (2 ** max(record.attempt_count - 1, 0)))
            record.with_context(dev_wa_analysis_action=True).write(
                {
                    "state": "retry",
                    "lease_owner_id": False,
                    "lease_consumer_ref": False,
                    "lease_token": False,
                    "lease_expires_at": False,
                    "next_attempt_at": now + timedelta(seconds=backoff),
                    "last_error_code": code,
                    "last_error_summary": summary,
                }
            )
            record.analysis_id.write(
                {
                    "state": "pending",
                    "error_code": code,
                    "error_message": summary,
                    "retry_count": record.analysis_id.retry_count + 1,
                }
            )
        return {"ok": True, "job_id": record.id, "state": record.state}
