# -*- coding: utf-8 -*-
"""Jooble search API adapter (POST /api/{key})."""

from __future__ import annotations

import logging
from typing import Any, Mapping, Optional

from ..base import AdapterError, BaseJobSourceAdapter, FetchResult
from ..http_util import safe_post

_logger = logging.getLogger(__name__)

JOOBLE_API_BASE = "https://jooble.org/api"


class JoobleAdapter(BaseJobSourceAdapter):
    adapter_key = "jooble"
    display_name = "Jooble"

    def _api_key(self) -> str:
        key = (self._cfg("api_key") or self._icp("linkedin_connector.jooble_api_key") or "").strip()
        return key

    def fetch_jobs(self, checkpoint: Optional[Mapping[str, Any]] = None) -> FetchResult:
        checkpoint = dict(checkpoint or {})
        api_key = self._api_key()
        keywords = self._cfg("keywords") or checkpoint.get("keywords") or "odoo"
        location = self._cfg("location") or checkpoint.get("location") or ""
        page = int(checkpoint.get("page") or 1)
        body = {"keywords": keywords, "location": location, "page": page}

        if not api_key:
            # Mock-friendly: return empty with meta so tests can inject payload
            _logger.info("jooble: api key missing — returning empty fetch")
            return FetchResult(
                jobs=[],
                checkpoint={"page": page, "keywords": keywords},
                http_status=0,
                meta={"skipped": "api_key_missing", "request_body": body},
            )

        url = f"{JOOBLE_API_BASE}/{api_key}"
        resp = safe_post(url, json=body)
        data = resp.json() if resp.content else {}
        jobs = data.get("jobs") or []
        if not isinstance(jobs, list):
            raise AdapterError("jooble_invalid_payload")
        return FetchResult(
            jobs=[j for j in jobs if isinstance(j, dict)],
            checkpoint={"page": page + 1, "keywords": keywords, "location": location},
            http_status=resp.status_code,
            raw_payload=data,
            next_cursor=str(page + 1),
            meta={"totalCount": data.get("totalCount")},
        )

    def normalize_job(self, raw: Mapping[str, Any]) -> dict[str, Any]:
        title = str(raw.get("title") or "")
        company = str(raw.get("company") or "")
        description = str(raw.get("snippet") or raw.get("description") or "")
        external_id = str(raw.get("id") or "")
        apply_url = self.extract_application_url(raw)
        # Jooble uses "link"
        if not apply_url and raw.get("link"):
            apply_url = str(raw.get("link"))
        loc_raw = dict(raw)
        loc_raw["description"] = description
        if raw.get("location") and "location" not in loc_raw:
            loc_raw["location"] = raw.get("location")
        return self._base_normalize(
            loc_raw,
            title=title,
            company=company,
            description=description,
            external_id=external_id,
            apply_url=apply_url,
            listed_at=str(raw.get("updated") or ""),
            source_url=apply_url,
        )

    def extract_application_url(self, raw: Mapping[str, Any]) -> str:
        for key in ("link", "url", "apply_url"):
            val = raw.get(key)
            if isinstance(val, str) and val.startswith("http"):
                return val.strip()
        return super().extract_application_url(raw)
