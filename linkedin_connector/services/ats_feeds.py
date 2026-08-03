# -*- coding: utf-8 -*-
"""Public ATS job-board feed clients (read-only, no auth bypass)."""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from typing import Any, Optional
from urllib.parse import urljoin

import requests

_logger = logging.getLogger(__name__)

USER_AGENT = "PetSpotDirectATSDiscovery/1.0 (+personal job hunt; respectful)"
TIMEOUT = 25
TITLE_HINTS = re.compile(
    r"\b(odoo|erp|python|integration|implementation|consultant|developer|engineer)\b",
    re.I,
)


def _session():
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json, text/xml, */*"})
    return s


def fetch_greenhouse_jobs(board_token: str) -> tuple[int, list[dict[str, Any]]]:
    """GET https://boards-api.greenhouse.io/v1/boards/{token}/jobs"""
    token = (board_token or "").strip()
    if not token:
        return 0, []
    url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
    r = _session().get(url, params={"content": "true"}, timeout=TIMEOUT)
    if r.status_code != 200:
        return r.status_code, []
    data = r.json() if r.content else {}
    out = []
    for job in data.get("jobs") or []:
        title = job.get("title") or ""
        if not TITLE_HINTS.search(title) and not TITLE_HINTS.search(
            (job.get("content") or "")[:2000]
        ):
            continue
        loc = ""
        if isinstance(job.get("location"), dict):
            loc = job["location"].get("name") or ""
        abs_url = job.get("absolute_url") or ""
        out.append(
            {
                "external_id": str(job.get("id") or ""),
                "title": title,
                "company": job.get("company_name") or token,
                "location": loc,
                "apply_url": abs_url,
                "description": job.get("content") or "",
                "remote": "remote" in (loc or "").lower(),
                "ats": "greenhouse",
                "source": f"greenhouse:{token}",
            }
        )
    return 200, out


def fetch_lever_jobs(site: str) -> tuple[int, list[dict[str, Any]]]:
    """GET https://api.lever.co/v0/postings/{site}?mode=json"""
    site = (site or "").strip()
    if not site:
        return 0, []
    url = f"https://api.lever.co/v0/postings/{site}"
    r = _session().get(url, params={"mode": "json"}, timeout=TIMEOUT)
    if r.status_code != 200:
        return r.status_code, []
    data = r.json() if r.content else []
    if not isinstance(data, list):
        return r.status_code, []
    out = []
    for job in data:
        title = job.get("text") or job.get("title") or ""
        desc = ""
        lists = job.get("lists") or []
        if isinstance(lists, list):
            for block in lists:
                desc += " " + (block.get("text") or "")
        desc += " " + (job.get("descriptionPlain") or job.get("description") or "")
        if not TITLE_HINTS.search(title) and not TITLE_HINTS.search(desc[:3000]):
            continue
        cats = job.get("categories") or {}
        loc = cats.get("location") or ""
        apply_url = job.get("hostedUrl") or job.get("applyUrl") or ""
        out.append(
            {
                "external_id": str(job.get("id") or ""),
                "title": title,
                "company": site,
                "location": loc,
                "apply_url": apply_url,
                "description": desc[:20000],
                "remote": "remote" in (loc or "").lower()
                or "remote" in (cats.get("commitment") or "").lower(),
                "ats": "lever",
                "source": f"lever:{site}",
            }
        )
    return 200, out


def fetch_ashby_jobs(board: str) -> tuple[int, list[dict[str, Any]]]:
    """GET https://api.ashbyhq.com/posting-api/job-board/{board}"""
    board = (board or "").strip()
    if not board:
        return 0, []
    url = f"https://api.ashbyhq.com/posting-api/job-board/{board}"
    r = _session().get(url, timeout=TIMEOUT)
    if r.status_code != 200:
        return r.status_code, []
    data = r.json() if r.content else {}
    jobs = data.get("jobs") or data.get("jobPostings") or []
    out = []
    for job in jobs:
        title = job.get("title") or ""
        desc = job.get("descriptionPlain") or job.get("descriptionHtml") or ""
        if not TITLE_HINTS.search(title) and not TITLE_HINTS.search(desc[:3000]):
            continue
        loc = job.get("location") or ""
        if isinstance(loc, dict):
            loc = loc.get("name") or ""
        apply_url = job.get("jobUrl") or job.get("applyUrl") or ""
        out.append(
            {
                "external_id": str(job.get("id") or job.get("jobId") or ""),
                "title": title,
                "company": board,
                "location": loc,
                "apply_url": apply_url,
                "description": desc[:20000],
                "remote": bool(job.get("isRemote")) or "remote" in (loc or "").lower(),
                "ats": "ashby",
                "source": f"ashby:{board}",
            }
        )
    return 200, out


def fetch_workable_widget(account: str) -> tuple[int, list[dict[str, Any]]]:
    """GET https://apply.workable.com/api/v1/widget/accounts/{account}"""
    account = (account or "").strip()
    if not account:
        return 0, []
    url = f"https://apply.workable.com/api/v1/widget/accounts/{account}"
    r = _session().get(url, timeout=TIMEOUT)
    if r.status_code != 200:
        return r.status_code, []
    data = r.json() if r.content else {}
    jobs = data.get("jobs") or []
    out = []
    for job in jobs:
        title = job.get("title") or ""
        if not TITLE_HINTS.search(title):
            continue
        loc = job.get("city") or job.get("location") or ""
        if isinstance(loc, dict):
            loc = loc.get("location_str") or loc.get("city") or ""
        shortcode = job.get("shortcode") or ""
        apply_url = job.get("url") or (
            f"https://apply.workable.com/{account}/j/{shortcode}/" if shortcode else ""
        )
        out.append(
            {
                "external_id": str(job.get("id") or shortcode or ""),
                "title": title,
                "company": account,
                "location": loc,
                "apply_url": apply_url,
                "description": job.get("description") or "",
                "remote": "remote" in (loc or "").lower(),
                "ats": "workable",
                "source": f"workable:{account}",
            }
        )
    return 200, out


def fetch_workable_xml(feed_url: str) -> tuple[int, list[dict[str, Any]]]:
    """GET employer Workable public XML feed."""
    feed_url = (feed_url or "").strip()
    if not feed_url.startswith("http"):
        return 0, []
    r = _session().get(feed_url, timeout=TIMEOUT)
    if r.status_code != 200:
        return r.status_code, []
    try:
        root = ET.fromstring(r.content)
    except ET.ParseError:
        return r.status_code, []
    out = []
    for job in root.findall(".//job") + root.findall(".//item"):
        title = (job.findtext("title") or "").strip()
        if not TITLE_HINTS.search(title):
            continue
        loc = (job.findtext("location") or job.findtext("city") or "").strip()
        link = (job.findtext("url") or job.findtext("link") or "").strip()
        desc = (job.findtext("description") or "").strip()
        jid = (job.findtext("shortcode") or job.findtext("guid") or link or title)[:120]
        out.append(
            {
                "external_id": jid,
                "title": title,
                "company": "",
                "location": loc,
                "apply_url": link,
                "description": desc[:20000],
                "remote": "remote" in loc.lower(),
                "ats": "workable",
                "source": f"workable_xml:{feed_url[:80]}",
            }
        )
    return 200, out


def fetch_company_career_links(jobs_index_url: str) -> tuple[int, list[dict[str, Any]]]:
    """Best-effort public career index scrape for /jobs/apply/ links (Odoo website pattern)."""
    jobs_index_url = (jobs_index_url or "").strip()
    if not jobs_index_url.startswith("http"):
        return 0, []
    r = _session().get(jobs_index_url, timeout=TIMEOUT)
    if r.status_code != 200:
        return r.status_code, []
    html = r.text or ""
    # Prefer apply links
    apply_paths = sorted(set(re.findall(r'href="([^"]*jobs/apply/[^"]+)"', html, flags=re.I)))
    detail_paths = sorted(set(re.findall(r'href="([^"]*jobs/(?:detail/)?[^"]+)"', html, flags=re.I)))
    out = []
    base = jobs_index_url
    for path in apply_paths[:40]:
        url = urljoin(base, path)
        slug = path.rstrip("/").split("/")[-1]
        title = slug.replace("-", " ").title()
        out.append(
            {
                "external_id": slug,
                "title": title,
                "company": "",
                "location": "",
                "apply_url": url,
                "description": "",
                "remote": False,
                "ats": "company_ats",
                "source": f"company_index:{jobs_index_url[:80]}",
                "needs_detail_fetch": True,
            }
        )
    if not out:
        for path in detail_paths[:40]:
            if "apply" in path.lower():
                continue
            url = urljoin(base, path)
            slug = path.rstrip("/").split("/")[-1]
            out.append(
                {
                    "external_id": slug,
                    "title": slug.replace("-", " ").title(),
                    "company": "",
                    "location": "",
                    "apply_url": urljoin(base, path.replace("/detail/", "/apply/") if "/detail/" in path else path),
                    "description": "",
                    "remote": False,
                    "ats": "company_ats",
                    "source": f"company_index:{jobs_index_url[:80]}",
                    "needs_detail_fetch": True,
                }
            )
    return 200, out


def fetch_job_detail(url: str) -> Optional[dict[str, Any]]:
    """Fetch public job/apply page metadata (no form fill, no CV)."""
    if not url or not url.startswith("http"):
        return None
    try:
        r = _session().get(url, timeout=TIMEOUT)
    except requests.RequestException as exc:
        _logger.info("detail fetch failed %s: %s", url[:80], exc)
        return None
    if r.status_code != 200:
        return {"http_status": r.status_code, "html": ""}
    html = r.text or ""
    title_m = re.search(r"<title>([^<]+)</title>", html, flags=re.I)
    title = (title_m.group(1) if title_m else "").split("|")[0].strip()
    text = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>|<[^>]+>", " ", html, flags=re.I)
    text = re.sub(r"\s+", " ", text)
    return {
        "http_status": 200,
        "title": title,
        "description": text[:25000],
        "html": html,
        "final_url": str(r.url),
    }
