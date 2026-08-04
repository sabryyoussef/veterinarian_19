# -*- coding: utf-8 -*-
"""Canonical URL helpers for partner careers probing / ATS dedupe."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

_TRACKING_PARAMS = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "gclid",
        "fbclid",
        "mc_cid",
        "mc_eid",
    }
)


def normalize_website(url: str) -> str:
    """Normalize partner homepage / careers URL for storage and uniqueness."""
    raw = (url or "").strip()
    if not raw:
        return ""
    if not raw.lower().startswith(("http://", "https://")):
        raw = "https://" + raw
    try:
        parsed = urlparse(raw)
    except Exception:
        return ""
    scheme = (parsed.scheme or "https").lower()
    if scheme not in ("http", "https"):
        return ""
    host = (parsed.hostname or "").lower()
    if not host:
        return ""
    if host.startswith("www."):
        host = host[4:]
    port = parsed.port
    netloc = host
    if port and not ((scheme == "https" and port == 443) or (scheme == "http" and port == 80)):
        netloc = f"{host}:{port}"
    path = parsed.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    query_pairs = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if k.lower() not in _TRACKING_PARAMS
    ]
    query = urlencode(query_pairs, doseq=True)
    # Prefer https in stored form; probe may still try http on failure.
    scheme = "https"
    return urlunparse((scheme, netloc, path or "/", "", query, ""))


def website_fingerprint(url: str) -> str:
    return normalize_website(url)


def normalize_board_token(token: str) -> str:
    return (token or "").strip().lower()
