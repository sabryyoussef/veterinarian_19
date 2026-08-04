# -*- coding: utf-8 -*-
"""Manual URL paste adapter — normalize user-supplied job dicts only."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from ..base import AdapterError, BaseJobSourceAdapter, FetchResult
from ..ssrf import validate_http_url


class ManualUrlAdapter(BaseJobSourceAdapter):
    adapter_key = "manual"
    display_name = "Manual URL"

    def fetch_jobs(self, checkpoint: Optional[Mapping[str, Any]] = None) -> FetchResult:
        """Manual source does not pull remotely; optional jobs list via config/checkpoint."""
        checkpoint = dict(checkpoint or {})
        jobs = self._cfg("jobs") or checkpoint.get("jobs") or []
        if isinstance(jobs, dict):
            jobs = [jobs]
        if not isinstance(jobs, list):
            raise AdapterError("manual_jobs_must_be_list")
        cleaned = []
        for item in jobs:
            if not isinstance(item, dict):
                continue
            url = item.get("apply_url") or item.get("url") or ""
            if url:
                validate_http_url(str(url), resolve_dns=False)
            cleaned.append(item)
        return FetchResult(
            jobs=cleaned,
            checkpoint={},
            http_status=200,
            meta={"mode": "manual"},
        )

    def normalize_job(self, raw: Mapping[str, Any]) -> dict[str, Any]:
        apply_url = str(raw.get("apply_url") or raw.get("url") or "")
        if apply_url:
            validate_http_url(apply_url, resolve_dns=False)
        loc_raw = dict(raw)
        return self._base_normalize(
            loc_raw,
            title=str(raw.get("title") or "Manual job"),
            company=str(raw.get("company") or ""),
            description=str(raw.get("description") or ""),
            external_id=str(raw.get("external_id") or raw.get("id") or apply_url),
            apply_url=apply_url,
            employment_type=str(raw.get("employment_type") or ""),
            source_url=apply_url,
        )
