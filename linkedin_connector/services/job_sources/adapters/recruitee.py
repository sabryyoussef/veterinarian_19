# -*- coding: utf-8 -*-
"""Recruitee public offers API adapter."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from ..base import BaseJobSourceAdapter, FetchResult
from ..http_util import safe_get


class RecruiteeAdapter(BaseJobSourceAdapter):
    adapter_key = "recruitee"
    display_name = "Recruitee"

    def fetch_jobs(self, checkpoint: Optional[Mapping[str, Any]] = None) -> FetchResult:
        company = (
            self._cfg("company_slug")
            or self._cfg("site")
            or self._cfg("board_token")
            or self._cfg("account")
            or ""
        ).strip()
        if not company:
            return FetchResult(jobs=[], http_status=0, meta={"skipped": "company_slug_missing"})
        url = f"https://{company}.recruitee.com/api/offers"
        resp = safe_get(url)
        data = resp.json() if resp.content else {}
        offers = data.get("offers") or []
        if not isinstance(offers, list):
            offers = []
        return FetchResult(
            jobs=[j for j in offers if isinstance(j, dict)],
            checkpoint={"company_slug": company},
            http_status=resp.status_code,
            meta={"company_slug": company},
        )

    def normalize_job(self, raw: Mapping[str, Any]) -> dict[str, Any]:
        company = str(
            self._cfg("company_slug")
            or self._cfg("site")
            or raw.get("company_name")
            or ""
        )
        loc = raw.get("location") or ""
        if isinstance(loc, dict):
            loc = loc.get("city") or loc.get("name") or ""
        # Careers URL on offer
        apply_url = str(raw.get("careers_url") or raw.get("url") or "")
        if not apply_url and raw.get("slug"):
            apply_url = f"https://{company}.recruitee.com/o/{raw.get('slug')}"
        loc_raw = dict(raw)
        loc_raw["location"] = loc or str(raw.get("remote") and "Remote" or "")
        loc_raw["remote"] = bool(raw.get("remote"))
        return self._base_normalize(
            loc_raw,
            title=str(raw.get("title") or ""),
            company=company,
            description=str(raw.get("description") or raw.get("requirements") or ""),
            external_id=str(raw.get("id") or raw.get("slug") or ""),
            apply_url=apply_url,
            employment_type=str(raw.get("employment_type") or ""),
            listed_at=str(raw.get("published_at") or ""),
            source_url=apply_url,
        )
