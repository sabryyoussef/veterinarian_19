# -*- coding: utf-8 -*-
"""Ashby job-board API adapter."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from ..base import BaseJobSourceAdapter, FetchResult
from ..http_util import safe_get


class AshbyAdapter(BaseJobSourceAdapter):
    adapter_key = "ashby"
    display_name = "Ashby"

    def fetch_jobs(self, checkpoint: Optional[Mapping[str, Any]] = None) -> FetchResult:
        board = (self._cfg("board_token") or self._cfg("site") or "").strip()
        if not board:
            return FetchResult(jobs=[], http_status=0, meta={"skipped": "board_missing"})
        url = f"https://api.ashbyhq.com/posting-api/job-board/{board}"
        resp = safe_get(url)
        data = resp.json() if resp.content else {}
        jobs = data.get("jobs") or data.get("jobPostings") or []
        if not isinstance(jobs, list):
            jobs = []
        return FetchResult(
            jobs=[j for j in jobs if isinstance(j, dict)],
            checkpoint={"board": board},
            http_status=resp.status_code,
            meta={"board": board},
        )

    def normalize_job(self, raw: Mapping[str, Any]) -> dict[str, Any]:
        loc = raw.get("location") or ""
        if isinstance(loc, dict):
            loc = loc.get("name") or ""
        loc_raw = dict(raw)
        loc_raw["location"] = loc
        loc_raw["remote"] = bool(raw.get("isRemote"))
        apply_url = str(raw.get("jobUrl") or raw.get("applyUrl") or "")
        return self._base_normalize(
            loc_raw,
            title=str(raw.get("title") or ""),
            company=str(self._cfg("board_token") or self._cfg("site") or ""),
            description=str(raw.get("descriptionPlain") or raw.get("descriptionHtml") or ""),
            external_id=str(raw.get("id") or raw.get("jobId") or ""),
            apply_url=apply_url,
            source_url=apply_url,
        )
