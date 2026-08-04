# -*- coding: utf-8 -*-
"""Lever postings API adapter."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from ..base import BaseJobSourceAdapter, FetchResult
from ..http_util import safe_get


class LeverAdapter(BaseJobSourceAdapter):
    adapter_key = "lever"
    display_name = "Lever"

    def fetch_jobs(self, checkpoint: Optional[Mapping[str, Any]] = None) -> FetchResult:
        site = (self._cfg("site") or self._cfg("board_token") or "").strip()
        if not site:
            return FetchResult(jobs=[], http_status=0, meta={"skipped": "site_missing"})
        url = f"https://api.lever.co/v0/postings/{site}"
        resp = safe_get(url, params={"mode": "json"})
        data = resp.json() if resp.content else []
        if not isinstance(data, list):
            data = []
        return FetchResult(
            jobs=[j for j in data if isinstance(j, dict)],
            checkpoint={"site": site},
            http_status=resp.status_code,
            meta={"site": site},
        )

    def normalize_job(self, raw: Mapping[str, Any]) -> dict[str, Any]:
        title = str(raw.get("text") or raw.get("title") or "")
        desc_parts = []
        for block in raw.get("lists") or []:
            if isinstance(block, dict):
                desc_parts.append(block.get("text") or "")
        desc_parts.append(str(raw.get("descriptionPlain") or raw.get("description") or ""))
        description = " ".join(desc_parts)
        cats = raw.get("categories") or {}
        loc = cats.get("location") if isinstance(cats, dict) else ""
        loc_raw = dict(raw)
        loc_raw["location"] = loc or ""
        apply_url = str(raw.get("hostedUrl") or raw.get("applyUrl") or "")
        return self._base_normalize(
            loc_raw,
            title=title,
            company=str(self._cfg("site") or ""),
            description=description[:20000],
            external_id=str(raw.get("id") or ""),
            apply_url=apply_url,
            employment_type=str((cats or {}).get("commitment") or "")
            if isinstance(cats, dict)
            else "",
            listed_at=str(raw.get("createdAt") or ""),
            source_url=apply_url,
        )
