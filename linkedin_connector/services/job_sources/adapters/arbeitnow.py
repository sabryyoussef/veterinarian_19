# -*- coding: utf-8 -*-
"""Arbeitnow public job-board API adapter."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from ..base import BaseJobSourceAdapter, FetchResult
from ..http_util import safe_get

ARBEITNOW_URL = "https://www.arbeitnow.com/api/job-board-api"
_TITLE_HINTS = __import__("re").compile(
    r"\b(odoo|erp|python|integration|implementation|consultant|developer)\b",
    __import__("re").I,
)
_ODOO_RE = __import__("re").compile(r"\bodoo\b", __import__("re").I)


class ArbeitnowAdapter(BaseJobSourceAdapter):
    adapter_key = "arbeitnow"
    display_name = "Arbeitnow"

    def fetch_jobs(self, checkpoint: Optional[Mapping[str, Any]] = None) -> FetchResult:
        checkpoint = dict(checkpoint or {})
        page = int(checkpoint.get("page") or 1)
        params = {"page": page}
        resp = safe_get(ARBEITNOW_URL, params=params)
        data = resp.json() if resp.content else {}
        jobs = data.get("data") or []
        if not isinstance(jobs, list):
            jobs = []
        filtered = []
        for item in jobs:
            if not isinstance(item, dict):
                continue
            blob = " ".join(
                [
                    str(item.get("title") or ""),
                    str(item.get("company_name") or ""),
                    str(item.get("description") or "")[:3000],
                    " ".join(item.get("tags") or []),
                ]
            )
            # Prefer Odoo-central roles; allow ERP+Python as weak keep for review
            if _ODOO_RE.search(blob) or (
                _TITLE_HINTS.search(str(item.get("title") or ""))
                and __import__("re").search(r"\b(python|erp)\b", blob, __import__("re").I)
            ):
                filtered.append(item)
        return FetchResult(
            jobs=filtered,
            checkpoint={"page": page + 1, "keywords": self._cfg("keywords") or ""},
            http_status=resp.status_code,
            raw_payload={"links": data.get("links"), "filtered_from": len(jobs)},
            next_cursor=str(page + 1),
        )

    def normalize_job(self, raw: Mapping[str, Any]) -> dict[str, Any]:
        loc_raw = dict(raw)
        loc_raw["location"] = raw.get("location") or "Remote"
        loc_raw["remote"] = bool(raw.get("remote"))
        return self._base_normalize(
            loc_raw,
            title=str(raw.get("title") or ""),
            company=str(raw.get("company_name") or ""),
            description=str(raw.get("description") or ""),
            external_id=str(raw.get("slug") or raw.get("url") or ""),
            apply_url=str(raw.get("url") or ""),
            employment_type=",".join(raw.get("job_types") or [])
            if isinstance(raw.get("job_types"), list)
            else str(raw.get("job_types") or ""),
            source_url=str(raw.get("url") or ""),
        )
