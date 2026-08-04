# -*- coding: utf-8 -*-
"""Email-alert adapter — structured JSON body only; disabled by default."""

from __future__ import annotations

import json
import logging
from typing import Any, Mapping, Optional

from ..base import AdapterError, BaseJobSourceAdapter, FetchResult

_logger = logging.getLogger(__name__)


class EmailAlertAdapter(BaseJobSourceAdapter):
    """Parse allowlisted email-alert payloads that are already JSON-structured.

    Does not connect to IMAP. Conceptually disabled unless ``enabled=True`` in config
    and a JSON body / jobs list is provided via checkpoint.
    """

    adapter_key = "email_alert"
    display_name = "Email Alert"

    def fetch_jobs(self, checkpoint: Optional[Mapping[str, Any]] = None) -> FetchResult:
        checkpoint = dict(checkpoint or {})
        enabled = bool(self._cfg("enabled") or checkpoint.get("enabled"))
        if not enabled:
            _logger.info("email_alert: disabled by default — skipping fetch")
            return FetchResult(
                jobs=[],
                http_status=0,
                meta={"skipped": "disabled_by_default"},
            )

        body = checkpoint.get("body") or self._cfg("body")
        jobs: list[Any] = []
        if isinstance(body, str):
            try:
                parsed = json.loads(body)
            except json.JSONDecodeError as exc:
                raise AdapterError("email_alert_invalid_json") from exc
            if isinstance(parsed, dict) and "jobs" in parsed:
                jobs = parsed.get("jobs") or []
            elif isinstance(parsed, list):
                jobs = parsed
            elif isinstance(parsed, dict):
                jobs = [parsed]
            else:
                raise AdapterError("email_alert_unsupported_json")
        elif isinstance(body, dict):
            jobs = body.get("jobs") or [body]
        elif checkpoint.get("jobs"):
            jobs = checkpoint.get("jobs") or []
        else:
            return FetchResult(jobs=[], http_status=0, meta={"skipped": "no_body"})

        if not isinstance(jobs, list):
            raise AdapterError("email_alert_jobs_not_list")
        return FetchResult(
            jobs=[j for j in jobs if isinstance(j, dict)],
            checkpoint={},
            http_status=200,
            meta={"mode": "structured_json"},
        )

    def normalize_job(self, raw: Mapping[str, Any]) -> dict[str, Any]:
        return self._base_normalize(
            dict(raw),
            title=str(raw.get("title") or ""),
            company=str(raw.get("company") or ""),
            description=str(raw.get("description") or ""),
            external_id=str(raw.get("external_id") or raw.get("id") or ""),
            apply_url=str(raw.get("apply_url") or raw.get("url") or ""),
            source_url=str(raw.get("apply_url") or raw.get("url") or ""),
        )
