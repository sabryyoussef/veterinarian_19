# -*- coding: utf-8 -*-
"""Sanitize payloads before archival / logging."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_SENSITIVE_KEY_RE = re.compile(
    r"(auth|token|password|secret|api_key|authorization)",
    re.I,
)
_SENSITIVE_QUERY_KEYS = frozenset(
    {
        "auth",
        "token",
        "password",
        "secret",
        "api_key",
        "apikey",
        "access_token",
        "authorization",
        "key",
        "app_key",
        "app_id",
    }
)


def _redact_url(url: str) -> str:
    try:
        parts = urlsplit(url)
    except ValueError:
        return "[REDACTED_URL]"
    if not parts.query:
        return url
    pairs = []
    for k, v in parse_qsl(parts.query, keep_blank_values=True):
        if k.lower() in _SENSITIVE_QUERY_KEYS or _SENSITIVE_KEY_RE.search(k):
            pairs.append((k, "REDACTED"))
        else:
            pairs.append((k, v))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(pairs), parts.fragment))


def sanitize_payload_for_storage(payload: Any) -> Any:
    """Deep-copy-ish sanitize: drop sensitive keys; redact secrets in query strings."""
    if isinstance(payload, dict):
        out = {}
        for key, value in payload.items():
            key_s = str(key)
            if _SENSITIVE_KEY_RE.search(key_s):
                continue
            out[key] = sanitize_payload_for_storage(value)
        return out
    if isinstance(payload, list):
        return [sanitize_payload_for_storage(item) for item in payload]
    if isinstance(payload, tuple):
        return tuple(sanitize_payload_for_storage(item) for item in payload)
    if isinstance(payload, str):
        if payload.startswith("http://") or payload.startswith("https://"):
            return _redact_url(payload)
        return payload
    return payload
