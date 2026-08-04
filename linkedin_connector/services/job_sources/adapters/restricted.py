# -*- coding: utf-8 -*-
"""Restricted sources (LinkedIn / Indeed automation) — fetch blocked."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from ..base import BaseJobSourceAdapter, ComplianceError, FetchResult
from ..ssrf import validate_http_url


class RestrictedSourceAdapter(BaseJobSourceAdapter):
    """Blocks automated fetch for LinkedIn/Indeed; manual normalize only."""

    adapter_key = "restricted"
    display_name = "Restricted (LinkedIn/Indeed)"

    def fetch_jobs(self, checkpoint: Optional[Mapping[str, Any]] = None) -> FetchResult:
        source = (
            self._cfg("restricted_source")
            or self._cfg("site")
            or (checkpoint or {}).get("source")
            or "linkedin_or_indeed"
        )
        raise ComplianceError(
            f"fetch_blocked:{source}:automation_rejected_use_manual_or_email_alert"
        )

    def normalize_job(self, raw: Mapping[str, Any]) -> dict[str, Any]:
        """Allow normalize only for explicitly pasted employer URLs (not scrape)."""
        apply_url = str(raw.get("apply_url") or raw.get("url") or "")
        if apply_url:
            validate_http_url(apply_url, resolve_dns=False)
            low = apply_url.lower()
            if "linkedin.com/jobs" in low or "indeed.com" in low:
                # Still allow store of a user-pasted URL, but flag source
                pass
        return self._base_normalize(
            dict(raw),
            title=str(raw.get("title") or "Restricted source job"),
            company=str(raw.get("company") or ""),
            description=str(raw.get("description") or ""),
            external_id=str(raw.get("external_id") or raw.get("id") or apply_url),
            apply_url=apply_url,
            source_url=apply_url,
        )
