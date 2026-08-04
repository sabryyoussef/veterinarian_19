# -*- coding: utf-8 -*-
"""JSearch (RapidAPI search-v2) adapter — stubs cleanly when key missing."""

from __future__ import annotations

import logging
import os
from typing import Any, Mapping, Optional

from ..base import BaseJobSourceAdapter, FetchResult
from ..http_util import safe_get

_logger = logging.getLogger(__name__)

JSEARCH_HOST = "jsearch.p.rapidapi.com"
JSEARCH_URL = f"https://{JSEARCH_HOST}/search-v2"


class JsearchAdapter(BaseJobSourceAdapter):
    adapter_key = "jsearch"
    display_name = "JSearch"

    def _api_key(self) -> str:
        for env_name in ("LINKEDIN_JSEARCH_RAPIDAPI_KEY", "JSEARCH_RAPIDAPI_KEY"):
            val = (os.environ.get(env_name) or "").strip()
            if val:
                return val
        return (
            self._cfg("api_key")
            or self._icp("linkedin_connector.jsearch_rapidapi_key")
            or ""
        ).strip()

    def fetch_jobs(self, checkpoint: Optional[Mapping[str, Any]] = None) -> FetchResult:
        checkpoint = dict(checkpoint or {})
        api_key = self._api_key()
        query = self._cfg("keywords") or checkpoint.get("query") or "odoo developer"
        page = int(checkpoint.get("page") or 1)
        country = self._cfg("country") or checkpoint.get("country") or ""
        remote = bool(self._cfg("remote") or checkpoint.get("remote"))

        if not api_key:
            _logger.info("jsearch: RapidAPI key missing — returning empty structure")
            return FetchResult(
                jobs=[],
                checkpoint={"page": page, "query": query},
                http_status=0,
                meta={"skipped": "api_key_missing", "endpoint": JSEARCH_URL},
                raw_payload={"data": []},
            )

        params = {
            "query": query,
            "page": str(page),
            "num_pages": "1",
            "date_posted": self._cfg("date_posted") or checkpoint.get("date_posted") or "week",
        }
        if country:
            params["country"] = country
        if remote:
            params["remote_jobs_only"] = "true"

        headers = {
            "X-RapidAPI-Key": api_key,
            "X-RapidAPI-Host": JSEARCH_HOST,
        }
        resp = safe_get(JSEARCH_URL, params=params, headers=headers, timeout=60)
        data = resp.json() if resp.content else {}
        payload = data.get("data", [])
        if isinstance(payload, dict):
            jobs = payload.get("jobs") or payload.get("data") or []
        else:
            jobs = payload or []
        if not isinstance(jobs, list):
            jobs = []
        return FetchResult(
            jobs=[j for j in jobs if isinstance(j, dict)],
            checkpoint={"page": page + 1, "query": query, "country": country, "remote": remote},
            http_status=resp.status_code,
            raw_payload={"count": len(jobs)},
            next_cursor=str(page + 1),
        )

    def normalize_job(self, raw: Mapping[str, Any]) -> dict[str, Any]:
        loc_parts = [raw.get("job_city") or "", raw.get("job_country") or ""]
        loc = raw.get("job_location") or ", ".join(x for x in loc_parts if x)
        loc_raw = dict(raw)
        loc_raw["location"] = loc
        loc_raw["city"] = raw.get("job_city") or ""
        loc_raw["country"] = raw.get("job_country") or ""
        loc_raw["remote"] = bool(raw.get("job_is_remote"))
        apply_url = (
            raw.get("job_apply_link") or raw.get("job_google_link") or raw.get("apply_url") or ""
        )
        return self._base_normalize(
            loc_raw,
            title=str(raw.get("job_title") or ""),
            company=str(raw.get("employer_name") or ""),
            description=str(raw.get("job_description") or ""),
            external_id=str(raw.get("job_id") or ""),
            apply_url=str(apply_url),
            employment_type=str(raw.get("job_employment_type") or ""),
            listed_at=str(raw.get("job_posted_at_datetime_utc") or ""),
            source_url=str(apply_url),
        )
