# -*- coding: utf-8 -*-
"""Classify job apply URLs into platform buckets (read-only heuristics)."""

from urllib.parse import urlparse

PLATFORM_SELECTION = [
    ("linkedin", "LinkedIn"),
    ("indeed", "Indeed"),
    ("bebee", "BeBee"),
    ("greenhouse", "Greenhouse"),
    ("lever", "Lever"),
    ("workday", "Workday"),
    ("company_ats", "Company ATS"),
    ("email", "Email"),
    ("aggregator", "Aggregator"),
    ("unknown", "Unknown"),
]


def classify_apply_url(url):
    raw = (url or "").strip()
    if not raw:
        return "unknown"
    lower = raw.lower()
    if lower.startswith("mailto:"):
        return "email"
    try:
        host = (urlparse(raw).netloc or "").lower()
    except Exception:
        return "unknown"
    path = ""
    try:
        path = (urlparse(raw).path or "").lower()
    except Exception:
        path = ""

    if "linkedin.com" in host:
        return "linkedin"
    if "indeed." in host:
        return "indeed"
    if "bebee." in host:
        return "bebee"
    if "greenhouse.io" in host or "boards.greenhouse" in host:
        return "greenhouse"
    if "lever.co" in host or "jobs.lever" in host:
        return "lever"
    if "myworkdayjobs.com" in host or "workday" in host:
        return "workday"
    if any(
        tok in host
        for tok in (
            "jobrapido.",
            "glassdoor.",
            "himalayas.",
            "bayt.",
            "wuzzuf.",
            "akhtaboot.",
            "simplyhired.",
            "ziprecruiter.",
        )
    ):
        return "aggregator"
    if any(
        tok in host
        for tok in (
            "ashbyhq.com",
            "smartrecruiters.com",
            "bamboohr.com",
            "workable.com",
            "recruitee.com",
            "personio.",
            "teamtailor.com",
        )
    ):
        return "company_ats"
    # Generic company career pages
    if host and not any(
        tok in host
        for tok in ("google.", "facebook.", "twitter.", "youtube.")
    ):
        if any(x in path for x in ("/careers", "/jobs", "/job/", "/apply")):
            return "company_ats"
    return "unknown"
