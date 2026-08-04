# -*- coding: utf-8 -*-
"""Read-only homepage / careers probe for Odoo partner websites.

HTTP only — callers must not hold long Odoo DB transactions while calling these
functions. Thread pools may use this module with plain Python data only.
"""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

import requests

from odoo.addons.linkedin_connector.services.url_normalize import normalize_website

_logger = logging.getLogger(__name__)

USER_AGENT = "PetSpotPartnerCareersProbe/1.0 (+personal job hunt; respectful)"
DEFAULT_CONNECT_TIMEOUT = 3.0
DEFAULT_READ_TIMEOUT = 7.0
MAX_BODY_BYTES = 2 * 1024 * 1024

CAREER_PATHS = (
    "/jobs",
    "/careers",
    "/career",
    "/jobs/",
    "/careers/",
    "/en/jobs",
    "/en/careers",
    "/en_US/jobs",
    "/en_US/careers",
    "/job-openings",
    "/vacancies",
)

_ATS_PATTERNS = (
    ("greenhouse", re.compile(r"boards(?:-api)?\.greenhouse\.io/([^/\s\"'?]+)", re.I)),
    ("greenhouse", re.compile(r"greenhouse\.io/embed/job_board/js\?for=([a-z0-9_-]+)", re.I)),
    ("lever", re.compile(r"(?:api|jobs)\.lever\.co/([a-z0-9_-]+)", re.I)),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/([a-z0-9_-]+)", re.I)),
    ("workable", re.compile(r"apply\.workable\.com/([a-z0-9_-]+)", re.I)),
    ("workable", re.compile(r"([a-z0-9_-]+)\.workable\.com", re.I)),
)

_JOB_LINK_RE = re.compile(
    r'href=["\']([^"\']*(?:/jobs/(?:apply/|detail/)?|/careers/|/career/)[^"\']*)["\']',
    re.I,
)


def _timeouts(connect: float, read: float) -> tuple[float, float]:
    return (max(2.0, min(20.0, float(connect))), max(2.0, min(20.0, float(read))))


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
    )
    return s


def _get(
    url: str,
    *,
    connect: float = DEFAULT_CONNECT_TIMEOUT,
    read: float = DEFAULT_READ_TIMEOUT,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "ok": False,
        "url": url,
        "final_url": url,
        "http_status": 0,
        "error_code": "",
        "error_message": "",
        "html": "",
        "content_length": 0,
    }
    try:
        r = _session().get(
            url,
            timeout=_timeouts(connect, read),
            allow_redirects=True,
            stream=True,
        )
        chunks = []
        size = 0
        for chunk in r.iter_content(chunk_size=65536):
            if not chunk:
                continue
            size += len(chunk)
            if size > MAX_BODY_BYTES:
                out["error_code"] = "body_too_large"
                out["http_status"] = r.status_code
                out["final_url"] = str(r.url)
                return out
            chunks.append(chunk)
        html = b"".join(chunks).decode(r.encoding or "utf-8", errors="replace")
        out["http_status"] = r.status_code
        out["final_url"] = str(r.url)
        out["content_length"] = size
        out["html"] = html
        out["ok"] = r.status_code == 200
        if r.status_code == 429:
            out["error_code"] = "rate_limited"
            out["error_message"] = (r.headers.get("Retry-After") or "")[:64]
        elif r.status_code >= 500:
            out["error_code"] = "http_5xx"
        elif r.status_code >= 400:
            out["error_code"] = f"http_{r.status_code}"
    except requests.exceptions.Timeout:
        out["error_code"] = "timeout"
        out["error_message"] = "timeout"
    except requests.exceptions.SSLError as exc:
        out["error_code"] = "ssl_error"
        out["error_message"] = str(exc)[:240]
    except requests.exceptions.ConnectionError as exc:
        msg = str(exc).lower()
        out["error_code"] = "dns_error" if "name or service not known" in msg or "getaddrinfo" in msg else "connection_error"
        out["error_message"] = str(exc)[:240]
    except Exception as exc:  # noqa: BLE001
        out["error_code"] = "request_error"
        out["error_message"] = str(exc)[:240]
    return out


def _detect_ats(html: str, base_url: str) -> Optional[tuple[str, str]]:
    blob = f"{html or ''} {base_url or ''}"
    for ats_type, pattern in _ATS_PATTERNS:
        m = pattern.search(blob)
        if not m:
            continue
        token = (m.group(1) or "").strip()
        if not token or token.lower() in ("www", "api", "jobs", "boards", "embed"):
            continue
        return ats_type, token
    return None


def _has_job_links(html: str) -> bool:
    if not html:
        return False
    if _JOB_LINK_RE.search(html):
        return True
    # Odoo website jobs listing markers
    if re.search(r"/jobs/apply/|/jobs/detail/", html, re.I):
        return True
    if re.search(r"\b(open positions|job openings|we are hiring|current openings)\b", html, re.I):
        return True
    return False


def probe_partner_website(
    website: str,
    *,
    connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
    read_timeout: float = DEFAULT_READ_TIMEOUT,
) -> dict[str, Any]:
    """Probe one partner website. Returns a plain dict (no ORM)."""
    base = normalize_website(website)
    result: dict[str, Any] = {
        "outcome": "error",
        "error_code": "invalid_website",
        "error_message": "",
        "http_status": 0,
        "ats_type": "",
        "board_token": "",
        "careers_url": "",
        "careers_url_normalized": "",
        "content_length": 0,
        "detected_pattern": "",
        "website_normalized": base,
    }
    if not base:
        return result

    home = _get(base, connect=connect_timeout, read=read_timeout)
    result["http_status"] = home.get("http_status") or 0
    result["content_length"] = home.get("content_length") or 0
    if home.get("error_code") and not home.get("ok"):
        result["outcome"] = "retry"
        result["error_code"] = home["error_code"]
        result["error_message"] = (home.get("error_message") or "")[:500]
        if home.get("http_status") in (404, 410):
            result["outcome"] = "miss"
        return result

    html = home.get("html") or ""
    ats = _detect_ats(html, home.get("final_url") or base)
    if ats:
        result["outcome"] = "hit"
        result["ats_type"] = ats[0]
        result["board_token"] = ats[1]
        result["detected_pattern"] = f"ats:{ats[0]}"
        result["error_code"] = ""
        return result

    # Homepage itself looks like a careers index
    if _has_job_links(html) and re.search(r"/jobs|/careers", home.get("final_url") or base, re.I):
        careers = normalize_website(home.get("final_url") or base)
        result["outcome"] = "hit"
        result["ats_type"] = "company_ats"
        result["careers_url"] = careers
        result["careers_url_normalized"] = careers
        result["board_token"] = careers
        result["detected_pattern"] = "homepage_careers"
        result["error_code"] = ""
        return result

    parsed = urlparse(base)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    for path in CAREER_PATHS:
        candidate = urljoin(origin + "/", path.lstrip("/"))
        page = _get(candidate, connect=connect_timeout, read=read_timeout)
        if not page.get("ok"):
            continue
        page_html = page.get("html") or ""
        ats2 = _detect_ats(page_html, page.get("final_url") or candidate)
        if ats2:
            result["outcome"] = "hit"
            result["ats_type"] = ats2[0]
            result["board_token"] = ats2[1]
            result["http_status"] = page.get("http_status") or 200
            result["content_length"] = page.get("content_length") or 0
            result["detected_pattern"] = f"path_ats:{path}:{ats2[0]}"
            result["error_code"] = ""
            return result
        if _has_job_links(page_html):
            careers = normalize_website(page.get("final_url") or candidate)
            result["outcome"] = "hit"
            result["ats_type"] = "company_ats"
            result["careers_url"] = careers
            result["careers_url_normalized"] = careers
            result["board_token"] = careers
            result["http_status"] = page.get("http_status") or 200
            result["content_length"] = page.get("content_length") or 0
            result["detected_pattern"] = f"path_careers:{path}"
            result["error_code"] = ""
            return result

    result["outcome"] = "miss"
    result["error_code"] = "no_careers"
    result["error_message"] = "homepage_ok_no_careers_or_ats"
    return result


def probe_many(
    websites: list[str],
    *,
    concurrency: int = 4,
    connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
    read_timeout: float = DEFAULT_READ_TIMEOUT,
) -> list[dict[str, Any]]:
    """Probe multiple websites. concurrency clamped 1–10. Returns list aligned to input order."""
    conc = max(1, min(10, int(concurrency or 1)))
    if conc == 1 or len(websites) <= 1:
        return [
            probe_partner_website(
                w, connect_timeout=connect_timeout, read_timeout=read_timeout
            )
            for w in websites
        ]
    results: list[Optional[dict[str, Any]]] = [None] * len(websites)
    with ThreadPoolExecutor(max_workers=conc) as pool:
        futs = {
            pool.submit(
                probe_partner_website,
                w,
                connect_timeout=connect_timeout,
                read_timeout=read_timeout,
            ): idx
            for idx, w in enumerate(websites)
        }
        for fut in as_completed(futs):
            idx = futs[fut]
            try:
                results[idx] = fut.result()
            except Exception as exc:  # noqa: BLE001
                results[idx] = {
                    "outcome": "retry",
                    "error_code": "thread_error",
                    "error_message": str(exc)[:240],
                    "http_status": 0,
                    "ats_type": "",
                    "board_token": "",
                    "careers_url": "",
                    "careers_url_normalized": "",
                    "content_length": 0,
                    "detected_pattern": "",
                    "website_normalized": normalize_website(websites[idx]),
                }
    return [r or {"outcome": "error", "error_code": "missing"} for r in results]
