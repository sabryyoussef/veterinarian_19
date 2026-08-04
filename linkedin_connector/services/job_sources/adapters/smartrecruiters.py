# -*- coding: utf-8 -*-
"""SmartRecruiters public postings API adapter."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from ..base import BaseJobSourceAdapter, FetchResult
from ..http_util import safe_get


class SmartRecruitersAdapter(BaseJobSourceAdapter):
    adapter_key = "smartrecruiters"
    display_name = "SmartRecruiters"

    def fetch_jobs(self, checkpoint: Optional[Mapping[str, Any]] = None) -> FetchResult:
        checkpoint = dict(checkpoint or {})
        company_id = (
            self._cfg("company_id")
            or self._cfg("board_token")
            or self._cfg("site")
            or checkpoint.get("company_id")
            or ""
        ).strip()
        if not company_id:
            return FetchResult(jobs=[], http_status=0, meta={"skipped": "company_id_missing"})
        offset = int(checkpoint.get("offset") or 0)
        limit = int(self._cfg("max_jobs_per_run") or 100)
        url = f"https://api.smartrecruiters.com/v1/companies/{company_id}/postings"
        resp = safe_get(url, params={"offset": offset, "limit": limit})
        data = resp.json() if resp.content else {}
        jobs = data.get("content") or data.get("postings") or []
        if not isinstance(jobs, list):
            jobs = []
        next_offset = offset + len(jobs)
        return FetchResult(
            jobs=[j for j in jobs if isinstance(j, dict)],
            checkpoint={"company_id": company_id, "offset": next_offset},
            http_status=resp.status_code,
            next_cursor=str(next_offset),
            truncated=bool(data.get("totalFound") and next_offset < int(data.get("totalFound") or 0)),
            meta={"company_id": company_id, "totalFound": data.get("totalFound")},
        )

    def normalize_job(self, raw: Mapping[str, Any]) -> dict[str, Any]:
        loc = ""
        location_obj = raw.get("location")
        if isinstance(location_obj, dict):
            parts = [
                location_obj.get("city") or "",
                location_obj.get("region") or "",
                location_obj.get("country") or "",
            ]
            loc = ", ".join(p for p in parts if p)
        company = ""
        company_obj = raw.get("company")
        if isinstance(company_obj, dict):
            company = str(company_obj.get("name") or "")
        apply_url = str(raw.get("applyUrl") or raw.get("ref") or raw.get("url") or "")
        # SmartRecruiters often exposes uuid + releasedDate
        if not apply_url and raw.get("id"):
            company_id = self._cfg("company_id") or self._cfg("board_token") or ""
            apply_url = (
                f"https://jobs.smartrecruiters.com/{company_id}/{raw.get('id')}"
                if company_id
                else ""
            )
        loc_raw = dict(raw)
        loc_raw["location"] = loc
        if isinstance(location_obj, dict):
            loc_raw["city"] = location_obj.get("city") or ""
            loc_raw["country"] = location_obj.get("country") or ""
        description = str(raw.get("description") or "")
        job_ad = raw.get("jobAd")
        if not description and isinstance(job_ad, dict):
            sections = job_ad.get("sections") or {}
            if isinstance(sections, dict):
                parts = []
                for section in sections.values():
                    if isinstance(section, dict):
                        parts.append(str(section.get("text") or section.get("description") or ""))
                description = "\n".join(p for p in parts if p)
        emp = raw.get("typeOfEmployment")
        if isinstance(emp, dict):
            employment_type = str(emp.get("label") or "")
        else:
            employment_type = str(emp or "")
        return self._base_normalize(
            loc_raw,
            title=str(raw.get("name") or raw.get("title") or ""),
            company=company or str(self._cfg("company_id") or ""),
            description=description,
            external_id=str(raw.get("id") or raw.get("uuid") or ""),
            apply_url=apply_url,
            listed_at=str(raw.get("releasedDate") or ""),
            employment_type=employment_type,
            source_url=apply_url,
        )
