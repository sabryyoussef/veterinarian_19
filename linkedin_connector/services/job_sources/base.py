# -*- coding: utf-8 -*-
"""Base job-source adapter contract and shared types."""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Mapping, MutableMapping, Optional, Sequence
from urllib.parse import urlparse

_logger = logging.getLogger(__name__)

# Tri-state flags for sponsorship / relocation / work authorization
TRI_YES = "yes"
TRI_NO = "no"
TRI_UNKNOWN = "unknown"
TRI_STATES = frozenset({TRI_YES, TRI_NO, TRI_UNKNOWN})

# Remote policy string enums
REMOTE_WORLD = "remote_world"
REMOTE_REGION = "remote_region"
REMOTE_COUNTRY = "remote_country"
HYBRID = "hybrid"
ONSITE = "onsite"
REMOTE_UNKNOWN = "unknown"
REMOTE_POLICIES = frozenset(
    {REMOTE_WORLD, REMOTE_REGION, REMOTE_COUNTRY, HYBRID, ONSITE, REMOTE_UNKNOWN}
)

SCORE_CATEGORIES = (
    "role_fit",
    "technical_fit",
    "location_fit",
    "remote_fit",
    "authorization_fit",
    "salary_fit",
    "source_quality",
)

_SPONSOR_YES_RE = re.compile(
    r"\b(visa\s+sponsorship|sponsor(ship)?\s+(available|provided|offered)|"
    r"will\s+sponsor|relocation\s+(assistance|package|support)|we\s+sponsor)\b",
    re.I,
)
_SPONSOR_NO_RE = re.compile(
    r"\b(no\s+visa\s+sponsorship|without\s+sponsorship|must\s+(already\s+)?have\s+"
    r"(work\s+)?authorization|right\s+to\s+work|eu\s+citizenship\s+required|"
    r"candidates\s+must\s+be\s+(eligible|authorized))\b",
    re.I,
)
_REMOTE_WORLD_RE = re.compile(
    r"\b(remote\s+(worldwide|world|global|anywhere)|work\s+from\s+anywhere)\b", re.I
)
_REMOTE_RE = re.compile(r"\b(remote|work\s+from\s+home|wfh)\b", re.I)
_HYBRID_RE = re.compile(r"\bhybrid\b", re.I)
_ONSITE_RE = re.compile(r"\b(on[- ]?site|in[- ]office|office[- ]based)\b", re.I)
_SALARY_RE = re.compile(
    r"(?P<cur>\$|€|£|usd|eur|gbp|aed|egp)?\s*(?P<low>\d[\d,]*(?:\.\d+)?)\s*"
    r"(?:-|–|to)\s*(?P<high>\d[\d,]*(?:\.\d+)?)\s*(?P<per>k|m)?(?:\s*(?P<period>/?\s*(?:year|yr|month|mo|annum|annually)))?",
    re.I,
)


class AdapterError(Exception):
    """Recoverable adapter failure (HTTP, schema, config)."""


class ComplianceError(AdapterError):
    """Source is blocked by compliance policy (e.g. LinkedIn/Indeed scrape)."""


class RateLimitError(AdapterError):
    """HTTP 429 or upstream rate limit / transient 5xx."""


@dataclass
class FetchResult:
    """Outcome of a single adapter fetch round."""

    jobs: list[dict[str, Any]] = field(default_factory=list)
    checkpoint: Optional[dict[str, Any]] = None
    http_status: Optional[int] = None
    raw_payload: Any = None
    next_cursor: Optional[str] = None
    truncated: bool = False
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def count(self) -> int:
        return len(self.jobs)


def empty_score_breakdown() -> dict[str, float]:
    return {k: 0.0 for k in SCORE_CATEGORIES}


def normalize_tri_state(value: Any) -> str:
    if value is True or (isinstance(value, str) and value.strip().lower() in {"yes", "true", "1", "y"}):
        return TRI_YES
    if value is False or (isinstance(value, str) and value.strip().lower() in {"no", "false", "0", "n"}):
        return TRI_NO
    if isinstance(value, str) and value.strip().lower() in TRI_STATES:
        return value.strip().lower()
    return TRI_UNKNOWN


def collapse_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def hash_description(text: str) -> str:
    """SHA-256 of whitespace-collapsed lowercase description text."""
    normalized = collapse_whitespace(text).lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


# Public alias used by pipeline / tests
description_fingerprint = hash_description


def NormalizedJobDict(
    *,
    title: str = "",
    company: str = "",
    location: str = "",
    country: str = "",
    city: str = "",
    description: str = "",
    apply_url: str = "",
    source_uid: str = "",
    external_id: str = "",
    source_url: str = "",
    adapter_key: str = "",
    remote_policy: str = REMOTE_UNKNOWN,
    remote: bool = False,
    salary_min: Optional[float] = None,
    salary_max: Optional[float] = None,
    salary_currency: str = "",
    salary_period: str = "",
    sponsorship: str = TRI_UNKNOWN,
    relocation: str = TRI_UNKNOWN,
    work_auth_required: str = TRI_UNKNOWN,
    employment_type: str = "",
    listed_at: str = "",
    description_fingerprint: str = "",
    raw_keys: Optional[Sequence[str]] = None,
    extra: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Build a normalized job dict with stable keys for pipeline / models."""
    desc = description or ""
    fp = description_fingerprint or (hash_description(desc) if desc else "")
    out: dict[str, Any] = {
        "title": (title or "")[:500],
        "company": (company or "")[:300],
        "location": (location or "")[:300],
        "country": (country or "")[:80],
        "city": (city or "")[:120],
        "description": desc,
        "apply_url": (apply_url or "").strip(),
        "source_uid": (source_uid or "").strip(),
        "external_id": str(external_id or "").strip(),
        "source_url": (source_url or "").strip(),
        "adapter_key": adapter_key or "",
        "remote_policy": remote_policy if remote_policy in REMOTE_POLICIES else REMOTE_UNKNOWN,
        "remote": bool(remote) or remote_policy in {REMOTE_WORLD, REMOTE_REGION, REMOTE_COUNTRY},
        "salary_min": salary_min,
        "salary_max": salary_max,
        "salary_currency": salary_currency or "",
        "salary_period": salary_period or "",
        "sponsorship": normalize_tri_state(sponsorship),
        "relocation": normalize_tri_state(relocation),
        "work_auth_required": normalize_tri_state(work_auth_required),
        "employment_type": (employment_type or "")[:80],
        "listed_at": listed_at or "",
        "description_fingerprint": fp,
        "raw_keys": list(raw_keys or []),
    }
    if extra:
        out["extra"] = dict(extra)
    return out


def infer_remote_policy(location: str = "", description: str = "", remote_flag: Any = None) -> str:
    blob = f"{location or ''} {description or ''}"
    if _REMOTE_WORLD_RE.search(blob):
        return REMOTE_WORLD
    if remote_flag is True or _REMOTE_RE.search(blob):
        if re.search(r"\b(emea|europe|eu\b|americas|apac)\b", blob, re.I):
            return REMOTE_REGION
        if re.search(r"\b(remote\s+(in|within|from)\s+\w+|only\s+in\s+\w+)\b", blob, re.I):
            return REMOTE_COUNTRY
        return REMOTE_WORLD if "anywhere" in blob.lower() else REMOTE_COUNTRY
    if _HYBRID_RE.search(blob):
        return HYBRID
    if _ONSITE_RE.search(blob):
        return ONSITE
    return REMOTE_UNKNOWN


def infer_sponsorship(description: str = "", title: str = "") -> dict[str, str]:
    blob = f"{title or ''} {description or ''}"
    if _SPONSOR_NO_RE.search(blob):
        sponsorship = TRI_NO
        work_auth = TRI_YES
    elif _SPONSOR_YES_RE.search(blob):
        sponsorship = TRI_YES
        work_auth = TRI_UNKNOWN
    else:
        sponsorship = TRI_UNKNOWN
        work_auth = TRI_UNKNOWN
    relocation = TRI_YES if re.search(r"\brelocati", blob, re.I) else TRI_UNKNOWN
    if _SPONSOR_NO_RE.search(blob) and "relocati" in blob.lower() and "no relocati" in blob.lower():
        relocation = TRI_NO
    return {
        "sponsorship": sponsorship,
        "relocation": relocation,
        "work_auth_required": work_auth,
    }


def parse_salary_text(text: str) -> dict[str, Any]:
    m = _SALARY_RE.search(text or "")
    if not m:
        return {
            "salary_min": None,
            "salary_max": None,
            "salary_currency": "",
            "salary_period": "",
        }
    cur = (m.group("cur") or "").strip().upper().replace("$", "USD").replace("€", "EUR").replace("£", "GBP")
    low = float(m.group("low").replace(",", ""))
    high = float(m.group("high").replace(",", ""))
    if (m.group("per") or "").lower() == "k":
        low *= 1000
        high *= 1000
    period = (m.group("period") or "").lower()
    if "month" in period or period in {"/mo", "mo"}:
        salary_period = "month"
    else:
        salary_period = "year"
    return {
        "salary_min": low,
        "salary_max": high,
        "salary_currency": cur,
        "salary_period": salary_period,
    }


class BaseJobSourceAdapter:
    """Abstract adapter; subclasses set ``adapter_key`` and implement fetch/normalize."""

    adapter_key: str = ""
    display_name: str = ""

    def __init__(self, connector: Any = None, env: Any = None, config: Optional[Mapping[str, Any]] = None):
        self.connector = connector
        self.env = env
        self.config: MutableMapping[str, Any] = dict(config or {})
        if connector is not None:
            for attr in (
                "api_key",
                "app_id",
                "app_key",
                "board_token",
                "site",
                "account",
                "company_id",
                "company_slug",
                "base_url",
                "keywords",
                "location",
                "country",
                "max_jobs_per_run",
                "cursor_json",
            ):
                if attr not in self.config and hasattr(connector, attr):
                    val = getattr(connector, attr)
                    if val not in (None, False, ""):
                        self.config[attr] = val
            if hasattr(connector, "code") and "connector_code" not in self.config:
                self.config["connector_code"] = connector.code

    def _cfg(self, key: str, default: Any = None) -> Any:
        return self.config.get(key, default)

    def _icp(self, param: str, default: str = "") -> str:
        if not self.env:
            return default
        try:
            return (
                self.env["ir.config_parameter"].sudo().get_param(param, default) or default
            ).strip()
        except Exception:
            _logger.debug("icp read failed for %s", param, exc_info=True)
            return default

    def fetch_jobs(self, checkpoint: Optional[Mapping[str, Any]] = None) -> FetchResult:
        raise NotImplementedError

    def normalize_job(self, raw: Mapping[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def build_source_uid(self, raw: Mapping[str, Any]) -> str:
        ext = (
            raw.get("external_id")
            or raw.get("id")
            or raw.get("job_id")
            or raw.get("slug")
            or ""
        )
        url = self.extract_application_url(raw)
        if url:
            parsed = urlparse(url)
            path_key = f"{parsed.netloc}{parsed.path}".rstrip("/").lower()
        else:
            path_key = ""
        base = f"{self.adapter_key}:{ext}:{path_key}"
        return hashlib.sha256(base.encode("utf-8")).hexdigest()[:40]

    def extract_application_url(self, raw: Mapping[str, Any]) -> str:
        for key in (
            "apply_url",
            "application_url",
            "absolute_url",
            "url",
            "link",
            "hostedUrl",
            "applyUrl",
            "jobUrl",
            "job_apply_link",
        ):
            val = raw.get(key)
            if isinstance(val, str) and val.startswith("http"):
                return val.strip()
        return ""

    def parse_location(self, raw: Mapping[str, Any]) -> dict[str, str]:
        loc = raw.get("location")
        if isinstance(loc, dict):
            name = loc.get("name") or loc.get("location_str") or loc.get("city") or ""
            country = loc.get("country") or ""
            city = loc.get("city") or ""
            return {"location": str(name), "country": str(country), "city": str(city)}
        location = str(loc or raw.get("candidate_required_location") or raw.get("job_location") or "")
        country = str(raw.get("country") or raw.get("job_country") or "")
        city = str(raw.get("city") or raw.get("job_city") or "")
        return {"location": location, "country": country, "city": city}

    def parse_salary(self, raw: Mapping[str, Any]) -> dict[str, Any]:
        if raw.get("salary_min") is not None or raw.get("salary_max") is not None:
            return {
                "salary_min": raw.get("salary_min"),
                "salary_max": raw.get("salary_max"),
                "salary_currency": raw.get("salary_currency") or "",
                "salary_period": raw.get("salary_period") or "",
            }
        for key in ("salary", "salary_text", "compensation", "description"):
            val = raw.get(key)
            if isinstance(val, str) and val.strip():
                parsed = parse_salary_text(val)
                if parsed["salary_min"] is not None:
                    return parsed
        return {
            "salary_min": None,
            "salary_max": None,
            "salary_currency": "",
            "salary_period": "",
        }

    def parse_remote_policy(self, raw: Mapping[str, Any]) -> str:
        loc = self.parse_location(raw)
        desc = str(raw.get("description") or raw.get("content") or "")
        return infer_remote_policy(
            location=loc.get("location") or "",
            description=desc,
            remote_flag=raw.get("remote") if "remote" in raw else raw.get("job_is_remote"),
        )

    def parse_sponsorship(self, raw: Mapping[str, Any]) -> dict[str, str]:
        title = str(raw.get("title") or raw.get("position") or raw.get("text") or "")
        desc = str(
            raw.get("description")
            or raw.get("content")
            or raw.get("descriptionPlain")
            or raw.get("snippet")
            or ""
        )
        return infer_sponsorship(description=desc, title=title)

    def _base_normalize(
        self,
        raw: Mapping[str, Any],
        *,
        title: str = "",
        company: str = "",
        description: str = "",
        external_id: str = "",
        apply_url: str = "",
        employment_type: str = "",
        listed_at: str = "",
        source_url: str = "",
    ) -> dict[str, Any]:
        loc = self.parse_location(raw)
        salary = self.parse_salary(raw)
        sponsor = self.parse_sponsorship(raw)
        remote_policy = self.parse_remote_policy(raw)
        apply = apply_url or self.extract_application_url(raw)
        uid_raw = dict(raw)
        uid_raw["external_id"] = external_id or uid_raw.get("external_id") or uid_raw.get("id")
        if apply:
            uid_raw["apply_url"] = apply
        return NormalizedJobDict(
            title=title,
            company=company,
            location=loc.get("location") or "",
            country=loc.get("country") or "",
            city=loc.get("city") or "",
            description=description,
            apply_url=apply,
            source_uid=self.build_source_uid(uid_raw),
            external_id=str(external_id or ""),
            source_url=source_url or apply,
            adapter_key=self.adapter_key,
            remote_policy=remote_policy,
            remote=remote_policy in {REMOTE_WORLD, REMOTE_REGION, REMOTE_COUNTRY},
            salary_min=salary.get("salary_min"),
            salary_max=salary.get("salary_max"),
            salary_currency=salary.get("salary_currency") or "",
            salary_period=salary.get("salary_period") or "",
            sponsorship=sponsor["sponsorship"],
            relocation=sponsor["relocation"],
            work_auth_required=sponsor["work_auth_required"],
            employment_type=employment_type,
            listed_at=listed_at,
            description_fingerprint=hash_description(description),
            raw_keys=sorted(str(k) for k in raw.keys()),
        )
