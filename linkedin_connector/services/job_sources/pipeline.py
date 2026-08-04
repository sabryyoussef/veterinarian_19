# -*- coding: utf-8 -*-
"""Normalize → dedupe → filter → score → lifecycle helpers (env-callable)."""

from __future__ import annotations

import logging
import re
from typing import Any, Mapping, MutableMapping, Optional, Sequence
from urllib.parse import urlparse

from .base import (
    REMOTE_COUNTRY,
    REMOTE_REGION,
    REMOTE_WORLD,
    SCORE_CATEGORIES,
    TRI_NO,
    TRI_YES,
    collapse_whitespace,
    description_fingerprint,
    empty_score_breakdown,
    hash_description,
)

_logger = logging.getLogger(__name__)

LIFECYCLE_DISCOVERED = "discovered"
LIFECYCLE_QUALIFIED = "qualified"
LIFECYCLE_REJECTED = "rejected"
LIFECYCLE_DUPLICATE = "duplicate"
LIFECYCLE_APPLICATION_READY = "application_ready"
LIFECYCLE_NEEDS_REVIEW = "needs_review"

_JUNIOR_RE = re.compile(
    r"\b(junior|intern|internship|trainee|entry[- ]level|graduate\s+programme)\b",
    re.I,
)
_ODOO_RE = re.compile(r"\bodo+o\b", re.I)
_SENIOR_RE = re.compile(r"\b(senior|lead|principal|architect|staff)\b", re.I)
_STACK_RE = re.compile(r"\b(python|postgresql|postgres|xml|rpc|rest|docker|linux)\b", re.I)
_UNRELATED_RE = re.compile(
    r"\b(java\s+only|net\s+only|\.net\s+only|sap\s+only|salesforce\s+only|"
    r"oracle\s+ebs|dynamics\s+365\s+only)\b",
    re.I,
)


def compute_description_fingerprint(text: str) -> str:
    return hash_description(text)


def canonical_apply_key(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url.strip())
    return f"{parsed.netloc}{parsed.path}".rstrip("/").lower()


def identity_keys(job: Mapping[str, Any]) -> dict[str, str]:
    company = collapse_whitespace(str(job.get("company") or "")).lower()
    title = collapse_whitespace(str(job.get("title") or "")).lower()
    country = collapse_whitespace(str(job.get("country") or "")).lower()
    city = collapse_whitespace(str(job.get("city") or "")).lower()
    fp = job.get("description_fingerprint") or description_fingerprint(str(job.get("description") or ""))
    return {
        "source_uid": str(job.get("source_uid") or ""),
        "external": f"{job.get('adapter_key') or ''}:{job.get('external_id') or ''}",
        "apply": canonical_apply_key(str(job.get("apply_url") or "")),
        "company_title_geo": f"{company}|{title}|{country}|{city}",
        "description_fingerprint": fp,
    }


def deterministic_dedupe(
    jobs: Sequence[Mapping[str, Any]],
    *,
    existing_keys: Optional[Mapping[str, str]] = None,
) -> list[dict[str, Any]]:
    """Mark duplicates deterministically; keep first (highest trust assumed pre-sorted).

    ``existing_keys`` maps identity key → master source_uid for DB-aware dedupe.
    """
    existing_keys = dict(existing_keys or {})
    seen: dict[str, str] = {}
    out: list[dict[str, Any]] = []

    for raw in jobs:
        job = dict(raw)
        keys = identity_keys(job)
        master_uid = None
        match_via = None
        for level in (
            "source_uid",
            "external",
            "apply",
            "company_title_geo",
            "description_fingerprint",
        ):
            val = keys.get(level) or ""
            if not val or val in {":", "|", "||"}:
                continue
            # skip weak geo key when company+title empty
            if level == "company_title_geo" and val.startswith("||"):
                continue
            if level == "description_fingerprint" and not job.get("description"):
                continue
            if val in existing_keys:
                master_uid = existing_keys[val]
                match_via = level
                break
            if val in seen:
                master_uid = seen[val]
                match_via = level
                break

        if master_uid and master_uid != keys.get("source_uid"):
            job["is_duplicate"] = True
            job["duplicate_of_uid"] = master_uid
            job["dedupe_match_via"] = match_via
            job["lifecycle_state"] = LIFECYCLE_DUPLICATE
        else:
            job["is_duplicate"] = False
            job["duplicate_of_uid"] = ""
            job["dedupe_match_via"] = ""
            uid = keys.get("source_uid") or keys.get("apply") or keys.get("external")
            if uid:
                for level, val in keys.items():
                    if val and val not in {":", "|", "||"}:
                        seen[val] = uid
                        existing_keys.setdefault(val, uid)
        out.append(job)
    return out


def _default_filter_rules() -> list[dict[str, Any]]:
    return [
        {
            "code": "missing_title",
            "reason_label": "Missing job title",
            "check": lambda j, b: not (j.get("title") or "").strip(),
        },
        {
            "code": "missing_apply_url",
            "reason_label": "Missing application URL",
            "check": lambda j, b: not (j.get("apply_url") or "").startswith("http"),
        },
        {
            "code": "junior_only",
            "reason_label": "Junior / intern role",
            "check": lambda j, b: bool(_JUNIOR_RE.search(j.get("title") or "")),
        },
        {
            "code": "unrelated_stack",
            "reason_label": "Non-Odoo stack primary",
            "check": lambda j, b: bool(_UNRELATED_RE.search(b)) and not _ODOO_RE.search(b),
        },
        {
            "code": "auth_required_no_sponsorship",
            "reason_label": "Work auth required without sponsorship",
            "check": lambda j, b: (
                j.get("work_auth_required") == TRI_YES and j.get("sponsorship") == TRI_NO
            ),
        },
    ]


def apply_filter_rules(
    job: Mapping[str, Any],
    *,
    env: Any = None,
    rules: Optional[Sequence[Mapping[str, Any]]] = None,
) -> dict[str, Any]:
    """Apply hard filters. Returns job copy with rejection fields if blocked."""
    out = dict(job)
    if out.get("is_duplicate"):
        return out

    blob = " ".join(
        [
            str(out.get("title") or ""),
            str(out.get("company") or ""),
            str(out.get("location") or ""),
            str(out.get("description") or "")[:8000],
        ]
    )
    active_rules = list(rules) if rules is not None else None
    if active_rules is None and env is not None:
        active_rules = _load_odoo_filter_rules(env)
    if active_rules is None:
        active_rules = _default_filter_rules()

    rejections: list[dict[str, str]] = []
    for rule in active_rules:
        code = str(rule.get("code") or "")
        label = str(rule.get("reason_label") or code)
        check = rule.get("check")
        matched = False
        if callable(check):
            try:
                matched = bool(check(out, blob))
            except Exception:
                _logger.debug("filter rule %s failed", code, exc_info=True)
        elif rule.get("pattern"):
            matched = bool(re.search(str(rule["pattern"]), blob, re.I))
            if rule.get("rule_type") == "hard_reject" and not matched:
                continue
            if rule.get("rule_type") == "hard_reject" and matched:
                matched = True
            elif rule.get("rule_type") != "hard_reject":
                continue
        if matched:
            rejections.append({"reason_code": code, "reason_label": label})
            if rule.get("stop_further_matching"):
                break

    if rejections:
        out["lifecycle_state"] = LIFECYCLE_REJECTED
        out["rejection_reasons"] = rejections
        out["discovery_blocker"] = rejections[0]["reason_code"]
    else:
        out.setdefault("lifecycle_state", LIFECYCLE_DISCOVERED)
        out["rejection_reasons"] = []
        out["discovery_blocker"] = ""
    return out


def _load_odoo_filter_rules(env: Any) -> Optional[list[dict[str, Any]]]:
    try:
        Model = env["linkedin.job.filter.rule"]
    except KeyError:
        return None
    rows = Model.sudo().search([("active", "=", True)], order="sequence, id")
    out = []
    for row in rows:
        pattern = getattr(row, "pattern", "") or ""
        code = row.code
        # Structural codes without pattern use built-in checks via defaults merge
        if not pattern:
            continue
        out.append(
            {
                "code": code,
                "reason_label": getattr(row, "reason_label", "") or code,
                "pattern": pattern,
                "rule_type": "hard_reject",
                "stop_further_matching": False,
                "require_explicit": bool(getattr(row, "require_explicit", True)),
            }
        )
    # Always include structural defaults (unknown data must not reject)
    return (_default_filter_rules() + out) if out else None


def _clamp(score: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, score))


def score_normalized_job(
    job: Mapping[str, Any],
    *,
    env: Any = None,
    trust_level: float = 50.0,
) -> dict[str, Any]:
    """Compute 0–100 score with category breakdown."""
    out = dict(job)
    breakdown = empty_score_breakdown()
    title = str(out.get("title") or "")
    blob = " ".join([title, str(out.get("description") or "")[:12000], str(out.get("location") or "")])

    # role_fit
    if _ODOO_RE.search(title):
        breakdown["role_fit"] += 35
    elif _ODOO_RE.search(blob):
        breakdown["role_fit"] += 20
    if _SENIOR_RE.search(title) or _SENIOR_RE.search(blob):
        breakdown["role_fit"] += 20
    if _JUNIOR_RE.search(title):
        breakdown["role_fit"] -= 40

    # technical_fit
    if _STACK_RE.search(blob):
        breakdown["technical_fit"] += 15
    if re.search(r"\b(integration|api|xml-rpc|json-rpc|odoo\.sh)\b", blob, re.I):
        breakdown["technical_fit"] += 10
    if _UNRELATED_RE.search(blob) and not _ODOO_RE.search(blob):
        breakdown["technical_fit"] -= 30

    # location_fit
    loc = str(out.get("location") or "").lower()
    if re.search(r"\b(egypt|cairo|uae|dubai|abu\s*dhabi)\b", loc, re.I) or re.search(
        r"\b(egypt|cairo|uae|dubai)\b", blob, re.I
    ):
        breakdown["location_fit"] += 15
    elif re.search(r"\b(europe|eu\b|germany|netherlands|belgium|uk)\b", blob, re.I):
        breakdown["location_fit"] += 8

    # remote_fit
    policy = out.get("remote_policy") or ""
    if policy == REMOTE_WORLD:
        breakdown["remote_fit"] += 15
    elif policy in {REMOTE_REGION, REMOTE_COUNTRY} or out.get("remote"):
        breakdown["remote_fit"] += 10

    # authorization_fit
    if out.get("sponsorship") == TRI_YES:
        breakdown["authorization_fit"] += 12
    if out.get("relocation") == TRI_YES:
        breakdown["authorization_fit"] += 8
    if out.get("work_auth_required") == TRI_YES and out.get("sponsorship") == TRI_NO:
        breakdown["authorization_fit"] -= 35

    # salary_fit (neutral if unknown; light boost if present and not tiny)
    smin = out.get("salary_min")
    if isinstance(smin, (int, float)) and smin >= 1000:
        breakdown["salary_fit"] += 8
    elif smin is None:
        breakdown["salary_fit"] += 0

    # source_quality from trust
    breakdown["source_quality"] = _clamp(float(trust_level) * 0.15, 0, 15)

    # Optional Odoo score rules
    if env is not None:
        _apply_odoo_score_rules(env, out, blob, breakdown)

    raw_total = sum(breakdown.values())
    # Map typical raw range (~-50..120) into 0–100
    normalized = _clamp(round(raw_total, 2), 0, 100)
    # If raw exceeded 100 before clamp, keep category dict as-is (informational)
    out["score"] = normalized
    out["score_raw"] = round(raw_total, 2)
    out["score_breakdown"] = {k: round(float(breakdown.get(k, 0.0)), 2) for k in SCORE_CATEGORIES}
    return out


def _apply_odoo_score_rules(
    env: Any,
    job: Mapping[str, Any],
    blob: str,
    breakdown: MutableMapping[str, float],
) -> None:
    try:
        Model = env["linkedin.job.score.rule"]
    except KeyError:
        return
    rows = Model.sudo().search([("active", "=", True)], order="sequence, id")
    seen_mutex: set[str] = set()
    for row in rows:
        mutex = getattr(row, "mutex_group", "") or ""
        if mutex and mutex in seen_mutex:
            continue
        pattern = getattr(row, "pattern", "") or ""
        if pattern and not re.search(pattern, blob, re.I):
            continue
        points = float(getattr(row, "points", 0) or 0)
        category = getattr(row, "category", "") or "role_fit"
        if category not in breakdown:
            category = "role_fit"
        rule_type = getattr(row, "rule_type", "bonus") or "bonus"
        if rule_type == "penalty":
            points = -abs(points)
        breakdown[category] = float(breakdown.get(category, 0.0)) + points
        if mutex:
            seen_mutex.add(mutex)


def set_lifecycle(job: Mapping[str, Any], *, score_threshold: float = 50.0) -> dict[str, Any]:
    out = dict(job)
    if out.get("is_duplicate"):
        out["lifecycle_state"] = LIFECYCLE_DUPLICATE
        return out
    if out.get("lifecycle_state") == LIFECYCLE_REJECTED or out.get("rejection_reasons"):
        out["lifecycle_state"] = LIFECYCLE_REJECTED
        return out
    score = float(out.get("score") or 0.0)
    blob = " ".join(
        [
            str(out.get("title") or ""),
            str(out.get("description") or "")[:4000],
        ]
    )
    odoo_hit = bool(_ODOO_RE.search(blob))
    apply_ok = (out.get("apply_url") or "").startswith("http")
    # Score alone never hard-blocks; qualification requires Odoo relevance + score.
    if apply_ok and odoo_hit and score >= score_threshold:
        out["lifecycle_state"] = LIFECYCLE_QUALIFIED
    elif apply_ok and odoo_hit:
        out["lifecycle_state"] = LIFECYCLE_DISCOVERED
    elif apply_ok:
        out["lifecycle_state"] = "needs_review"
        out.setdefault("discovery_blocker", "odoo_relevance_unknown")
    else:
        out["lifecycle_state"] = LIFECYCLE_DISCOVERED
    return out


def process_normalized_jobs(
    env: Any,
    jobs: Sequence[Mapping[str, Any]],
    *,
    existing_keys: Optional[Mapping[str, str]] = None,
    trust_level: float = 50.0,
    score_threshold: float = 50.0,
) -> list[dict[str, Any]]:
    """Full pipeline for a batch of normalized job dicts (no model writes)."""
    deduped = deterministic_dedupe(jobs, existing_keys=existing_keys)
    results: list[dict[str, Any]] = []
    for job in deduped:
        filtered = apply_filter_rules(job, env=env)
        if filtered.get("is_duplicate") or filtered.get("lifecycle_state") == LIFECYCLE_REJECTED:
            results.append(set_lifecycle(filtered, score_threshold=score_threshold))
            continue
        scored = score_normalized_job(filtered, env=env, trust_level=trust_level)
        results.append(set_lifecycle(scored, score_threshold=score_threshold))
    return results
