# -*- coding: utf-8 -*-
"""Adzuna jobs API adapter."""

from __future__ import annotations

import logging
from typing import Any, Mapping, Optional

from ..base import AdapterError, BaseJobSourceAdapter, FetchResult
from ..http_util import safe_get

_logger = logging.getLogger(__name__)


class AdzunaAdapter(BaseJobSourceAdapter):
    adapter_key = "adzuna"
    display_name = "Adzuna"

    def _creds(self) -> tuple[str, str]:
        app_id = (
            self._cfg("app_id")
            or self._icp("linkedin_connector.adzuna_app_id")
            or ""
        ).strip()
        app_key = (
            self._cfg("app_key")
            or self._icp("linkedin_connector.adzuna_app_key")
            or ""
        ).strip()
        return app_id, app_key

    def fetch_jobs(self, checkpoint: Optional[Mapping[str, Any]] = None) -> FetchResult:
        checkpoint = dict(checkpoint or {})
        app_id, app_key = self._creds()
        country = (self._cfg("country") or checkpoint.get("country") or "gb").lower()
        page = int(checkpoint.get("page") or 1)
        what = self._cfg("keywords") or checkpoint.get("keywords") or "odoo"
        where = self._cfg("location") or checkpoint.get("location") or ""

        if not app_id or not app_key:
            _logger.info("adzuna: credentials missing — returning empty fetch")
            return FetchResult(
                jobs=[],
                checkpoint={"page": page, "country": country, "keywords": what},
                http_status=0,
                meta={"skipped": "credentials_missing"},
            )

        url = f"https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"
        params = {
            "app_id": app_id,
            "app_key": app_key,
            "results_per_page": int(self._cfg("max_jobs_per_run") or 20),
            "what": what,
        }
        if where:
            params["where"] = where
        resp = safe_get(url, params=params)
        data = resp.json() if resp.content else {}
        results = data.get("results") or []
        if not isinstance(results, list):
            raise AdapterError("adzuna_invalid_payload")
        return FetchResult(
            jobs=[j for j in results if isinstance(j, dict)],
            checkpoint={"page": page + 1, "country": country, "keywords": what, "location": where},
            http_status=resp.status_code,
            raw_payload={"count": data.get("count"), "results_len": len(results)},
            next_cursor=str(page + 1),
            meta={"count": data.get("count")},
        )

    def normalize_job(self, raw: Mapping[str, Any]) -> dict[str, Any]:
        title = str(raw.get("title") or "")
        company = ""
        company_obj = raw.get("company")
        if isinstance(company_obj, dict):
            company = str(company_obj.get("display_name") or "")
        else:
            company = str(company_obj or "")
        loc = raw.get("location")
        loc_raw = dict(raw)
        if isinstance(loc, dict):
            loc_raw["location"] = loc.get("display_name") or ""
            areas = loc.get("area") or []
            if isinstance(areas, list) and areas:
                loc_raw["country"] = str(areas[0])
                loc_raw["city"] = str(areas[-1]) if len(areas) > 1 else ""
        description = str(raw.get("description") or "")
        salary = {}
        if raw.get("salary_min") is not None:
            salary["salary_min"] = raw.get("salary_min")
        if raw.get("salary_max") is not None:
            salary["salary_max"] = raw.get("salary_max")
        loc_raw.update(salary)
        return self._base_normalize(
            loc_raw,
            title=title,
            company=company,
            description=description,
            external_id=str(raw.get("id") or ""),
            apply_url=str(raw.get("redirect_url") or raw.get("url") or ""),
            listed_at=str(raw.get("created") or ""),
            source_url=str(raw.get("redirect_url") or ""),
        )
