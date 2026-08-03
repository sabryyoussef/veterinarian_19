"""Fail-closed authorization checks for gated unattended submit."""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from dataclasses import dataclass
from typing import Any, Optional

# Adapters that completed offline fixture coverage. Live auto-submit additionally
# requires a controlled live draft before first Production use (enforced by Odoo/n8n).
APPROVED_SUBMIT_ADAPTERS = frozenset(
    {
        "odoo_careers",
        "greenhouse_like",
        "lever_like",
        "workable_like",
        "ashby_like",
    }
)

# BeBee remains draft-only (login walls on live aggregators).
DRAFT_ONLY_ADAPTERS = frozenset({"bebee_like"})


@dataclass
class SubmitGateResult:
    ok: bool
    code: str
    message: str
    human_required: bool = False


def _env_true(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes")


def submit_env_enabled() -> bool:
    return _env_true("PERSONAL_JOB_APPLY_SUBMIT_ENABLED")


def verify_one_time_token(
    *,
    token: str,
    expected_attempt_id: str,
    token_store: dict[str, Any],
) -> SubmitGateResult:
    """Validate and (on success path later) consume a one-time submit token.

    token_store shape:
      {
        "token": "...",
        "attempt_id": "...",
        "expires_at": unix_ts,
        "consumed": false,
        "live_submit_enabled": true,
        "approved_adapter": "greenhouse_like",
        "score": 65,
        "captcha_cleared": true,
        "login_cleared": true,
        "otp_cleared": true,
        "sensitive_docs_cleared": true,
        "profile_complete": true,
        "duplicate_cleared": true,
        "within_caps": true,
      }
    """
    if not token or not token_store:
        return SubmitGateResult(False, "token_missing", "One-time submit token missing")
    if token_store.get("consumed"):
        return SubmitGateResult(False, "token_consumed", "Submit token already consumed")
    try:
        exp = float(token_store.get("expires_at") or 0)
    except (TypeError, ValueError):
        return SubmitGateResult(False, "token_invalid", "Submit token expiry invalid")
    if exp and time.time() > exp:
        return SubmitGateResult(False, "token_expired", "Submit token expired")
    stored = str(token_store.get("token") or "")
    if not stored or not hmac.compare_digest(stored, token):
        return SubmitGateResult(False, "token_mismatch", "Submit token mismatch")
    if str(token_store.get("attempt_id") or "") != str(expected_attempt_id):
        return SubmitGateResult(False, "token_attempt_mismatch", "Token attempt_id mismatch")
    return SubmitGateResult(True, "ok", "token_ok")


def evaluate_submit_authorization(
    *,
    auth: dict[str, Any],
    adapter_used: Optional[str],
    draft_metadata: Optional[dict[str, Any]] = None,
) -> SubmitGateResult:
    """Fail-closed policy gate for unattended click-submit."""
    if not submit_env_enabled():
        return SubmitGateResult(False, "submit_disabled", "PERSONAL_JOB_APPLY_SUBMIT_ENABLED not set")

    if not auth.get("live_submit_enabled"):
        return SubmitGateResult(False, "live_submit_disabled", "live_submit_enabled must be true")

    adapter = (adapter_used or auth.get("approved_adapter") or "").strip()
    if adapter in DRAFT_ONLY_ADAPTERS:
        return SubmitGateResult(
            False,
            "adapter_draft_only",
            f"Adapter {adapter} is draft-only",
            human_required=True,
        )
    if adapter not in APPROVED_SUBMIT_ADAPTERS:
        return SubmitGateResult(
            False,
            "adapter_not_approved",
            f"Adapter {adapter or 'unknown'} is not approved for auto-submit",
            human_required=True,
        )

    # Score is informational only (policy floor is 0). Never block submit on score.
    _ = auth.get("score")

    bool_gates = [
        ("captcha_cleared", "captcha"),
        ("login_cleared", "login_wall"),
        ("otp_cleared", "otp"),
        ("sensitive_docs_cleared", "sensitive_docs"),
        ("profile_complete", "profile_incomplete"),
        ("duplicate_cleared", "duplicate"),
        ("within_caps", "caps_exceeded"),
    ]
    for key, code in bool_gates:
        if auth.get(key) is not True:
            human = code in {"captcha", "login_wall", "otp", "sensitive_docs"}
            return SubmitGateResult(
                False,
                code,
                f"Authorization gate failed: {key}",
                human_required=human,
            )

    # Cross-check draft preflight metadata when present (fail closed on conflict).
    meta = draft_metadata or {}
    turnstile = meta.get("turnstile") or {}
    if turnstile.get("verify_human_wall") or turnstile.get("turnstile_present"):
        # turnstile_present alone on Odoo careers may be widget without wall; treat
        # interactive wall as hard stop. Presence without cleared flag already failed above.
        if turnstile.get("verify_human_wall") or not auth.get("captcha_cleared"):
            return SubmitGateResult(
                False,
                "captcha",
                "CAPTCHA/Turnstile detected in draft metadata",
                human_required=True,
            )

    return SubmitGateResult(True, "ok", "authorization_ok")


def token_fingerprint(token: str) -> str:
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()[:16]
