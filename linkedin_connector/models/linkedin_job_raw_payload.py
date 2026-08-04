# -*- coding: utf-8 -*-
"""Sanitized raw fetch archive with retention policy."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class LinkedinJobRawPayload(models.Model):
    _name = "linkedin.job.raw.payload"
    _description = "Job Source Raw Payload Archive"
    _order = "fetched_at desc, id desc"

    connector_id = fields.Many2one(
        "linkedin.job.source.connector", required=True, ondelete="cascade", index=True
    )
    fetched_at = fields.Datetime(required=True, default=fields.Datetime.now, index=True)
    http_status = fields.Integer()
    environment = fields.Selection(
        [("test", "TEST"), ("prod", "Production")], index=True
    )
    is_error = fields.Boolean(default=False, index=True)
    request_meta_json = fields.Text(
        help="Sanitized request metadata only (no secrets)."
    )
    response_hash = fields.Char(index=True)
    payload_text = fields.Text(
        help="Sanitized payload body when retention policy allows."
    )
    retention_until = fields.Datetime(index=True)
    job_ids = fields.Many2many(
        "linkedin.job",
        "linkedin_job_raw_payload_job_rel",
        "payload_id",
        "job_id",
        string="Linked jobs",
    )

    @api.model
    def _archive_fetch(self, connector, result, sanitized):
        env_name = connector.environment or "test"
        is_error = bool((result.http_status or 200) >= 400)
        store_full = False
        if env_name == "test" and connector.raw_archive_enabled:
            store_full = True
        elif is_error and connector.raw_archive_enabled:
            store_full = True
        # Production success: metadata + hash only
        blob = ""
        try:
            blob = json.dumps(sanitized, ensure_ascii=False, default=str) if sanitized is not None else ""
        except (TypeError, ValueError):
            blob = str(sanitized)[:50000] if sanitized is not None else ""
        digest = hashlib.sha256((blob or "").encode("utf-8")).hexdigest() if blob else ""
        retention_days = 30
        retention_until = fields.Datetime.now() + timedelta(days=retention_days)
        meta = {
            "adapter_key": connector.adapter_key,
            "code": connector.code,
            "http_status": result.http_status,
            "job_count": getattr(result, "count", 0),
            "truncated": bool(getattr(result, "truncated", False)),
        }
        vals = {
            "connector_id": connector.id,
            "fetched_at": fields.Datetime.now(),
            "http_status": result.http_status or 0,
            "environment": env_name,
            "is_error": is_error,
            "request_meta_json": json.dumps(meta),
            "response_hash": digest,
            "payload_text": (blob[:200000] if store_full else False),
            "retention_until": retention_until if (store_full or is_error) else False,
        }
        return self.create(vals)

    @api.model
    def _cron_cleanup(self):
        now = fields.Datetime.now()
        old = self.search(
            [
                "|",
                ("retention_until", "!=", False),
                ("retention_until", "<=", now),
                ("retention_until", "<=", now),
            ]
        )
        # Also purge prod success rows older than 7 days with no retention
        prod_old = self.search(
            [
                ("environment", "=", "prod"),
                ("is_error", "=", False),
                ("payload_text", "!=", False),
                ("fetched_at", "<=", now - timedelta(days=7)),
            ]
        )
        to_clear = old | prod_old
        count = len(to_clear)
        to_clear.unlink()
        _logger.info("linkedin.job.raw.payload cleanup removed %s rows", count)
        return count
