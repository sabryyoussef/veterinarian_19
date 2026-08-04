# -*- coding: utf-8 -*-
"""Greenhouse Job Board API adapter."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from ..base import BaseJobSourceAdapter, FetchResult
from ..http_util import safe_get


class GreenhouseAdapter(BaseJobSourceAdapter):
    adapter_key = "greenhouse"
    display_name = "Greenhouse"

    def fetch_jobs(self, checkpoint: Optional[Mapping[str, Any]] = None) -> FetchResult:
        token = (self._cfg("board_token") or self._cfg("site") or "").strip()
        if not token:
            return FetchResult(jobs=[], http_status=0, meta={"skipped": "board_token_missing"})
        url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
        resp = safe_get(url, params={"content": "true"})
        data = resp.json() if resp.content else {}
        jobs = data.get("jobs") or []
        if not isinstance(jobs, list):
            jobs = []
        return FetchResult(
            jobs=[j for j in jobs if isinstance(j, dict)],
            checkpoint={"board_token": token},
            http_status=resp.status_code,
            meta={"board_token": token},
        )

    def normalize_job(self, raw: Mapping[str, Any]) -> dict[str, Any]:
        loc = ""
        if isinstance(raw.get("location"), dict):
            loc = raw["location"].get("name") or ""
        loc_raw = dict(raw)
        loc_raw["location"] = loc
        company = str(raw.get("company_name") or self._cfg("board_token") or "")
        return self._base_normalize(
            loc_raw,
            title=str(raw.get("title") or ""),
            company=company,
            description=str(raw.get("content") or ""),
            external_id=str(raw.get("id") or ""),
            apply_url=str(raw.get("absolute_url") or ""),
            listed_at=str(raw.get("updated_at") or ""),
            source_url=str(raw.get("absolute_url") or ""),
        )
