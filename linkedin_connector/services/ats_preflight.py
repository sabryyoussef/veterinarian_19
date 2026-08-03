# -*- coding: utf-8 -*-
"""Eligibility + lightweight form preflight (no CV / no personal data)."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from odoo.addons.linkedin_connector.services.ats_feeds import fetch_job_detail
from odoo.addons.linkedin_connector.services.platform_classifier import classify_apply_url

SUPPORTED_AUTO_ATS = frozenset({"greenhouse", "lever", "ashby", "workable", "company_ats", "odoo_careers"})

_SPONSOR_RE = re.compile(
    r"\b(visa|sponsorship|sponsor|relocation|relocate|work permit|immigration)\b", re.I
)
_EGYPT_RE = re.compile(
    r"\b(egypt|cairo|giza|alexandria|eg\b)\b|مصر|القاهرة|الجيزة|الإسكندرية|الاسكندرية",
    re.I,
)
_UAE_RE = re.compile(
    r"\b(uae|dubai|abu\s*dhabi|sharjah|united arab emirates)\b|"
    r"الإمارات|الامارات|دبي|أبو\s*ظبي|ابو\s*ظبي|الشارقة",
    re.I,
)
_GULF_RE = re.compile(
    r"\b(saudi|riyadh|jeddah|qatar|doha|kuwait|bahrain|oman|muscat|manama)\b", re.I
)
_EU_RE = re.compile(
    r"\b(belgium|france|germany|netherlands|spain|italy|europe|eu\b|uk\b|united kingdom)\b",
    re.I,
)
_REMOTE_RE = re.compile(r"\b(remote|work from home|wfh|anywhere)\b", re.I)
_JUNIOR_ONLY_RE = re.compile(
    r"\b(junior|intern|internship|entry[- ]level|0\s*[-–]\s*1\s+years?|max(?:imum)?\s*1\s+year)\b",
    re.I,
)
_AUTH_NO_SPONSOR_RE = re.compile(
    r"(must (already )?have|requires?).{0,40}(work authorization|right to work|eu citizenship|local nationality)|"
    r"no visa sponsorship|without sponsorship|candidates must be (eligible|authorized)",
    re.I,
)
# Require an actual challenge widget — ignore Odoo session keys like recaptcha_public_key.
_CAPTCHA_RE = re.compile(
    r"cf-turnstile|"
    r"class=[\"'][^\"']*g-recaptcha|"
    r"g-recaptcha-response|"
    r"\bh-captcha\b|hcaptcha-box|h-captcha-response|"
    r"iframe[^>]+(?:recaptcha|hcaptcha|challenges\.cloudflare|turnstile)|"
    r"data-sitekey=[\"'][^\"']+[\"'][^>]*(?:g-recaptcha|cf-turnstile|h-captcha)|"
    r"(?:g-recaptcha|cf-turnstile|h-captcha)[^>]*data-sitekey",
    re.I,
)
_LOGIN_RE = re.compile(
    r"type=[\"']password[\"']|sign in to (continue|apply)|log in to apply|create an account",
    re.I,
)
_OTP_RE = re.compile(r"one[- ]time|otp|verification code", re.I)
_SENSITIVE_RE = re.compile(
    r"passport|national\s*id|ssn|social security|bank account|iban|biometric|credit card|payment",
    re.I,
)
_RELEVANT_RE = re.compile(
    r"\b(odoo|python|erp|postgresql|owl|integration|consultant|implementation)\b", re.I
)


def location_allowed(location: str, description: str, remote: bool) -> tuple[bool, str]:
    blob = f"{location or ''} {description or ''}"
    if _EGYPT_RE.search(blob) or _UAE_RE.search(blob):
        return True, "egypt_or_uae"
    if remote or _REMOTE_RE.search(blob):
        return True, "remote"
    if _GULF_RE.search(blob):
        if _SPONSOR_RE.search(blob):
            return True, "gulf_with_sponsorship"
        return False, "gulf_without_sponsorship"
    if _EU_RE.search(blob):
        if _SPONSOR_RE.search(blob):
            return True, "eu_with_sponsorship"
        return False, "eu_without_sponsorship"
    # Unknown / empty location — allow only if remote flagged
    if not (location or "").strip():
        return False, "location_unknown"
    return False, "location_out_of_policy"


def classify_preflight(
    *,
    title: str,
    location: str,
    description: str,
    apply_url: str,
    remote: bool,
    score: float,
    ats_hint: str = "",
) -> dict[str, Any]:
    """Return discovery classification without submitting or sending PII."""
    platform = ats_hint or classify_apply_url(apply_url)
    if platform in ("ashby",) or "ashbyhq" in (apply_url or "").lower():
        platform = "ashby"
    if platform in ("workable",) or "workable.com" in (apply_url or "").lower():
        platform = "workable"
    if "odoo.com" in (apply_url or "").lower() or "open-inside.com" in (apply_url or "").lower():
        platform = "company_ats"

    result = {
        "discovery_class": "ineligible",
        "blocker": "",
        "platform": platform,
        "preflight": {},
        "http_status": None,
        # Score is informational only — never blocks classification.
        "score": float(score or 0.0),
        "role_relevant": bool(_RELEVANT_RE.search(f"{title} {description}")),
        "junior_title": bool(_JUNIOR_ONLY_RE.search(title or "")),
    }

    if platform in ("linkedin", "indeed", "bebee", "aggregator", "email"):
        result["discovery_class"] = "ineligible"
        result["blocker"] = f"blocked_platform:{platform}"
        return result

    ok_loc, loc_reason = location_allowed(location, description, remote)
    if not ok_loc:
        result["blocker"] = loc_reason
        return result

    if _AUTH_NO_SPONSOR_RE.search(description or ""):
        result["blocker"] = "requires_existing_authorization_no_sponsor"
        return result

    if platform not in SUPPORTED_AUTO_ATS and platform not in (
        "greenhouse",
        "lever",
        "company_ats",
    ):
        result["discovery_class"] = "unsupported_ats"
        result["blocker"] = f"unsupported_ats:{platform}"
        return result

    # Non-submitting form preflight
    detail = fetch_job_detail(apply_url)
    if not detail:
        result["discovery_class"] = "human_required"
        result["blocker"] = "preflight_fetch_failed"
        return result
    result["http_status"] = detail.get("http_status")
    html = detail.get("html") or ""
    if detail.get("http_status") != 200:
        result["discovery_class"] = "human_required"
        result["blocker"] = f"http_{detail.get('http_status')}"
        return result

    # Enrich description/title from page when thin
    if detail.get("description") and len(description or "") < 200:
        description = detail["description"]
        ok_loc, loc_reason = location_allowed(location, description, remote)
        if not ok_loc:
            result["blocker"] = loc_reason
            return result

    pre = {
        "captcha": bool(_CAPTCHA_RE.search(html)),
        "login": bool(_LOGIN_RE.search(html)),
        "otp": bool(_OTP_RE.search(html)),
        "sensitive_docs": bool(_SENSITIVE_RE.search(html)),
        "has_form": bool(re.search(r"<form[\s>]|name=[\"']partner_name|name=[\"']email", html, re.I)),
        "final_url": detail.get("final_url"),
    }
    result["preflight"] = pre

    if pre["captcha"]:
        result["discovery_class"] = "human_required"
        result["blocker"] = "captcha_or_turnstile"
        return result
    if pre["login"]:
        result["discovery_class"] = "human_required"
        result["blocker"] = "login_wall"
        return result
    if pre["otp"]:
        result["discovery_class"] = "human_required"
        result["blocker"] = "otp"
        return result
    if pre["sensitive_docs"]:
        result["discovery_class"] = "human_required"
        result["blocker"] = "sensitive_document_request"
        return result
    if not pre["has_form"]:
        result["discovery_class"] = "human_required"
        result["blocker"] = "no_accessible_form"
        return result

    # Host drift to LinkedIn etc.
    host = (urlparse(pre.get("final_url") or apply_url).netloc or "").lower()
    if "linkedin.com" in host or "indeed." in host or "bebee." in host:
        result["discovery_class"] = "ineligible"
        result["blocker"] = f"redirect_blocked_host:{host}"
        return result

    result["discovery_class"] = "safe_canary_candidate"
    result["blocker"] = ""
    return result
