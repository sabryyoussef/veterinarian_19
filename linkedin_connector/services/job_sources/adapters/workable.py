# -*- coding: utf-8 -*-
"""Workable public widget / feed adapter."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any, Mapping, Optional

from ..base import AdapterError, BaseJobSourceAdapter, FetchResult
from ..http_util import safe_get
from ..ssrf import validate_http_url


class WorkableAdapter(BaseJobSourceAdapter):
    adapter_key = "workable"
    display_name = "Workable"

    def fetch_jobs(self, checkpoint: Optional[Mapping[str, Any]] = None) -> FetchResult:
        feed_url = (self._cfg("feed_url") or self._cfg("base_url") or "").strip()
        account = (self._cfg("account") or self._cfg("board_token") or self._cfg("site") or "").strip()

        if feed_url:
            validate_http_url(feed_url, resolve_dns=False)
            resp = safe_get(feed_url)
            try:
                root = ET.fromstring(resp.content)
            except ET.ParseError as exc:
                raise AdapterError("workable_xml_parse_error") from exc
            jobs = []
            for job in root.findall(".//job") + root.findall(".//item"):
                title = (job.findtext("title") or "").strip()
                loc = (job.findtext("location") or job.findtext("city") or "").strip()
                link = (job.findtext("url") or job.findtext("link") or "").strip()
                desc = (job.findtext("description") or "").strip()
                jid = (job.findtext("shortcode") or job.findtext("guid") or link or title)[:120]
                jobs.append(
                    {
                        "id": jid,
                        "title": title,
                        "location": loc,
                        "url": link,
                        "description": desc,
                        "shortcode": job.findtext("shortcode") or "",
                    }
                )
            return FetchResult(
                jobs=jobs,
                checkpoint={"feed_url": feed_url[:200]},
                http_status=resp.status_code,
                meta={"mode": "xml"},
            )

        if not account:
            return FetchResult(jobs=[], http_status=0, meta={"skipped": "account_missing"})
        url = f"https://apply.workable.com/api/v1/widget/accounts/{account}"
        resp = safe_get(url)
        data = resp.json() if resp.content else {}
        jobs = data.get("jobs") or []
        if not isinstance(jobs, list):
            jobs = []
        return FetchResult(
            jobs=[j for j in jobs if isinstance(j, dict)],
            checkpoint={"account": account},
            http_status=resp.status_code,
            meta={"mode": "widget", "account": account},
        )

    def normalize_job(self, raw: Mapping[str, Any]) -> dict[str, Any]:
        account = str(self._cfg("account") or self._cfg("board_token") or self._cfg("site") or "")
        loc = raw.get("city") or raw.get("location") or ""
        if isinstance(loc, dict):
            loc = loc.get("location_str") or loc.get("city") or ""
        shortcode = raw.get("shortcode") or ""
        apply_url = raw.get("url") or ""
        if not apply_url and account and shortcode:
            apply_url = f"https://apply.workable.com/{account}/j/{shortcode}/"
        loc_raw = dict(raw)
        loc_raw["location"] = loc
        return self._base_normalize(
            loc_raw,
            title=str(raw.get("title") or ""),
            company=account,
            description=str(raw.get("description") or ""),
            external_id=str(raw.get("id") or shortcode or ""),
            apply_url=str(apply_url),
            source_url=str(apply_url),
        )
