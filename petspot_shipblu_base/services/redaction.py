# -*- coding: utf-8 -*-
"""Sanitize secrets and PII before logging ShipBlu traffic."""

from __future__ import annotations

import json
import re
from typing import Any

_SECRET_KEYS = {
    "authorization",
    "api_key",
    "apikey",
    "api-key",
    "token",
    "password",
    "secret",
    "x-api-key",
}
_PHONE_RE = re.compile(r"(01[0125]\d{8}|\+201[0125]\d{8})")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def _scrub_value(key: str, value: Any) -> Any:
    if key and key.lower().replace("_", "").replace("-", "") in {
        k.replace("_", "").replace("-", "") for k in _SECRET_KEYS
    }:
        return "***REDACTED***"
    if isinstance(value, dict):
        return {k: _scrub_value(k, v) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub_value(key, v) for v in value]
    if isinstance(value, str):
        if key and key.lower() in {"phone", "phonenumber", "mobile", "email", "full_name", "firstname", "lastname"}:
            if "@" in value:
                return "***@***"
            if _PHONE_RE.search(value) or value.isdigit():
                return "***PHONE***"
            if len(value) > 2:
                return value[:1] + "***"
        text = _PHONE_RE.sub("***PHONE***", value)
        text = _EMAIL_RE.sub("***@***", text)
        return text
    return value


def redact_payload(payload: Any) -> Any:
    if payload is None:
        return None
    if isinstance(payload, (bytes, bytearray)):
        try:
            payload = payload.decode("utf-8", errors="replace")
        except Exception:
            return "<binary>"
    if isinstance(payload, str):
        try:
            return redact_payload(json.loads(payload))
        except Exception:
            text = _PHONE_RE.sub("***PHONE***", payload)
            text = _EMAIL_RE.sub("***@***", text)
            text = re.sub(r"(?i)(authorization|api[_-]?key)\s*[:=]\s*\S+", r"\1=***REDACTED***", text)
            return text[:8000]
    if isinstance(payload, dict):
        return {k: _scrub_value(k, v) for k, v in payload.items()}
    if isinstance(payload, list):
        return [redact_payload(v) for v in payload]
    return payload


def redact_headers(headers: dict | None) -> dict:
    headers = headers or {}
    return {k: _scrub_value(k, v) for k, v in headers.items()}
