# -*- coding: utf-8 -*-
"""Remotive public remote-jobs API adapter."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from ..base import BaseJobSourceAdapter, FetchResult
from ..http_util import safe_get

REMOTIVE_URL = "https://remotive.com/api/remote-jobs"


class RemotiveAdapter(BaseJobSourceAdapter):
    adapter_key = "remotive"
    display_name = "Remotive"

    def fetch_jobs(self, checkpoint: Optional[Mapping[str, Any]] = None) -> FetchResult:
        checkpoint = dict(checkpoint or {})
        keywords = self._cfg("keywords") or checkpoint.get("keywords") or "odoo"
        # Prefer single strong token for Remotive search API
        if isinstance(keywords, str) and " " in keywords:
            search = "odoo"
        else:
            search = keywords or "odoo"
        limit = int(self._cfg("max_jobs_per_run") or checkpoint.get("limit") or 50)
        resp = safe_get(REMOTIVE_URL, params={"search": search, "limit": limit})
        data = resp.json() if resp.content else {}
        jobs = data.get("jobs") or []
        if not isinstance(jobs, list):
            jobs = []
        # Post-filter: require odoo in title/description
        import re

        odoo_re = re.compile(r"\bodoo\b", re.I)
        jobs = [
            j
            for j in jobs
            if isinstance(j, dict)
            and odoo_re.search(
                "%s %s" % (j.get("title") or "", (j.get("description") or "")[:2000])
            )
        ]
        return FetchResult(
            jobs=jobs,
            checkpoint={"keywords": search, "limit": limit},
            http_status=resp.status_code,
            raw_payload={"job-count": data.get("job-count")},
        )

    def normalize_job(self, raw: Mapping[str, Any]) -> dict[str, Any]:
        loc_raw = dict(raw)
        loc_raw["location"] = raw.get("candidate_required_location") or "Remote"
        loc_raw["remote"] = True
        return self._base_normalize(
            loc_raw,
            title=str(raw.get("title") or ""),
            company=str(raw.get("company_name") or ""),
            description=str(raw.get("description") or ""),
            external_id=str(raw.get("id") or ""),
            apply_url=str(raw.get("url") or ""),
            employment_type=str(raw.get("job_type") or ""),
            listed_at=str(raw.get("publication_date") or ""),
            source_url=str(raw.get("url") or ""),
        )
