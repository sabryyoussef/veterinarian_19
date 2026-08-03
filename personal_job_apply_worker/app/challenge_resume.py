# -*- coding: utf-8 -*-
"""One-time human-challenge resume tokens (CAPTCHA/OTP handoff)."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

TOKEN_DIR = Path(
    os.environ.get(
        "JOB_APPLY_CHALLENGE_TOKEN_DIR",
        "/home/sabry/private/job_orchestrator/challenge_tokens",
    )
)


@dataclass
class ChallengeToken:
    token: str
    attempt_id: str
    application_id: int
    job_id: int
    apply_url: str
    expires_at: float
    consumed: bool = False
    challenge_type: str = "captcha"

    def to_dict(self) -> dict[str, Any]:
        return {
            "token": self.token,
            "attempt_id": self.attempt_id,
            "application_id": self.application_id,
            "job_id": self.job_id,
            "apply_url": self.apply_url,
            "expires_at": self.expires_at,
            "consumed": self.consumed,
            "challenge_type": self.challenge_type,
            "fingerprint": hashlib.sha256(self.token.encode()).hexdigest()[:16],
        }


def _ensure_dir() -> Path:
    TOKEN_DIR.mkdir(parents=True, mode=0o700, exist_ok=True)
    try:
        os.chmod(TOKEN_DIR, 0o700)
    except OSError:
        pass
    return TOKEN_DIR


def _path_for(attempt_id: str) -> Path:
    import re

    safe = re.sub(r"[^A-Za-z0-9._-]", "_", attempt_id)[:80]
    return _ensure_dir() / f"{safe}.json"


def issue_challenge_token(
    *,
    attempt_id: str,
    application_id: int,
    job_id: int,
    apply_url: str,
    ttl_seconds: int = 1800,
    challenge_type: str = "captcha",
) -> ChallengeToken:
    tok = ChallengeToken(
        token=secrets.token_urlsafe(32),
        attempt_id=attempt_id,
        application_id=int(application_id),
        job_id=int(job_id),
        apply_url=apply_url or "",
        expires_at=time.time() + max(60, int(ttl_seconds)),
        consumed=False,
        challenge_type=challenge_type,
    )
    path = _path_for(attempt_id)
    path.write_text(json.dumps(tok.to_dict()), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return tok


def load_challenge_token(attempt_id: str) -> Optional[dict[str, Any]]:
    path = _path_for(attempt_id)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def verify_and_consume_challenge_token(
    *,
    attempt_id: str,
    token: str,
    expected_application_id: Optional[int] = None,
) -> tuple[bool, str, Optional[dict[str, Any]]]:
    data = load_challenge_token(attempt_id)
    if not data:
        return False, "token_missing", None
    if data.get("consumed"):
        return False, "token_consumed", data
    try:
        exp = float(data.get("expires_at") or 0)
    except (TypeError, ValueError):
        return False, "token_invalid", data
    if exp and time.time() > exp:
        return False, "token_expired", data
    stored = str(data.get("token") or "")
    if not stored or not hmac.compare_digest(stored, token or ""):
        return False, "token_mismatch", data
    if expected_application_id is not None and int(data.get("application_id") or 0) != int(
        expected_application_id
    ):
        return False, "application_mismatch", data
    data["consumed"] = True
    path = _path_for(attempt_id)
    path.write_text(json.dumps(data), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return True, "ok", data
