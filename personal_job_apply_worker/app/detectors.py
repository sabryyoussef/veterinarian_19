"""Stop-reason detectors for offline dry-run pages."""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlparse

from app.models import StopReason

LINKEDIN_RE = re.compile(r"linkedin\.com", re.IGNORECASE)

CAPTCHA_SELECTORS = [
    "[data-testid='captcha']",
    "#captcha",
    ".g-recaptcha",
    "iframe[src*='recaptcha']",
    "iframe[src*='hcaptcha']",
    "[class*='captcha' i]",
    "text=/verify you are human/i",
]

OTP_SELECTORS = [
    "[data-testid='otp']",
    "#otp",
    "input[name*='otp' i]",
    "input[autocomplete='one-time-code']",
    "text=/enter (the )?code/i",
    "text=/one[- ]time (pass)?code/i",
]

LOGIN_WALL_SELECTORS = [
    "[data-testid='login-wall']",
    "form[action*='login' i]",
    "input[type='password']",
    "text=/sign in to continue/i",
    "text=/log in to apply/i",
]

CONSENT_SELECTORS = [
    "[data-testid='consent']",
    "#cookie-consent",
    "text=/accept (all )?cookies/i",
    "text=/privacy consent/i",
]

# Custom / unknown questions that adapters do not know how to fill.
UNKNOWN_QUESTION_SELECTORS = [
    "[data-testid='unknown-question']",
    "[data-unknown-question='true']",
    "label[data-custom-question]",
]


def is_linkedin_url(url: str) -> bool:
    if not url:
        return False
    if LINKEDIN_RE.search(url):
        return True
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return False
    return "linkedin.com" in host or host.endswith(".linkedin.com")


def detect_stop_reason_from_html(html: str) -> Optional[StopReason]:
    """Cheap HTML heuristics used before/without Playwright."""
    lower = (html or "").lower()
    if "data-testid=\"captcha\"" in lower or "g-recaptcha" in lower or "hcaptcha" in lower:
        return StopReason.captcha
    if "data-testid=\"otp\"" in lower or "one-time" in lower or 'autocomplete="one-time-code"' in lower:
        return StopReason.otp
    if "data-testid=\"login-wall\"" in lower or "sign in to continue" in lower:
        return StopReason.login_wall
    if "data-testid=\"consent\"" in lower or "accept all cookies" in lower:
        return StopReason.consent
    if "data-testid=\"unknown-question\"" in lower or "data-unknown-question" in lower:
        return StopReason.unknown_question
    return None


async def detect_stop_reason_on_page(page) -> Optional[StopReason]:
    """Inspect the live Playwright page for stop conditions."""
    checks = [
        (StopReason.captcha, CAPTCHA_SELECTORS),
        (StopReason.otp, OTP_SELECTORS),
        (StopReason.login_wall, LOGIN_WALL_SELECTORS),
        (StopReason.consent, CONSENT_SELECTORS),
        (StopReason.unknown_question, UNKNOWN_QUESTION_SELECTORS),
    ]
    for reason, selectors in checks:
        for sel in selectors:
            try:
                loc = page.locator(sel)
                if await loc.count() > 0 and await loc.first.is_visible():
                    return reason
            except Exception:
                continue
    return None
