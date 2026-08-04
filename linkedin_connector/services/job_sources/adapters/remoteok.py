# -*- coding: utf-8 -*-
"""RemoteOK public JSON feed adapter."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from ..base import BaseJobSourceAdapter, FetchResult
from ..http_util import safe_get

REMOTEOK_URL = "https://remoteok.com/api"


class RemoteOkAdapter(BaseJobSourceAdapter):
    adapter_key = "remoteok"
    display_name = "RemoteOK"

    def fetch_jobs(self, checkpoint: Optional[Mapping[str, Any]] = None) -> FetchResult:
        checkpoint = dict(checkpoint or {})
        tag = (self._cfg("tag") or checkpoint.get("tag") or "python").strip().lower()
        resp = safe_get(REMOTEOK_URL, params={"tag": tag})
        data = resp.json() if resp.content else []
        if not isinstance(data, list):
            data = []
        jobs = []
        for item in data:
            if not isinstance(item, dict):
                continue
            # First element is often metadata without position
            if not item.get("position") and not item.get("title"):
                continue
            jobs.append(item)
        keywords = (self._cfg("keywords") or checkpoint.get("keywords") or "").lower().split()
        if keywords:
            filtered = []
            for item in jobs:
                blob = " ".join(
                    [
                        str(item.get("position") or item.get("title") or ""),
                        " ".join(item.get("tags") or []),
                        str(item.get("description") or "")[:2000],
                    ]
                ).lower()
                if any(k in blob for k in keywords if k):
                    filtered.append(item)
            jobs = filtered
        return FetchResult(
            jobs=jobs,
            checkpoint={"tag": tag, "keywords": self._cfg("keywords") or ""},
            http_status=resp.status_code,
        )

    def normalize_job(self, raw: Mapping[str, Any]) -> dict[str, Any]:
        loc_raw = dict(raw)
        loc_raw["location"] = raw.get("location") or "Remote"
        loc_raw["remote"] = True
        return self._base_normalize(
            loc_raw,
            title=str(raw.get("position") or raw.get("title") or ""),
            company=str(raw.get("company") or ""),
            description=str(raw.get("description") or ""),
            external_id=str(raw.get("id") or ""),
            apply_url=str(raw.get("url") or raw.get("apply_url") or ""),
            source_url=str(raw.get("url") or ""),
        )
