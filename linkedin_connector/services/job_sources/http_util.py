# -*- coding: utf-8 -*-
"""Safe HTTP helpers for job-source adapters."""

from __future__ import annotations

import logging
import re
from typing import Any, Mapping, MutableMapping, Optional

import requests

from .base import AdapterError, RateLimitError
from .ssrf import SSRFError, validate_http_url

_logger = logging.getLogger(__name__)

USER_AGENT = "PetSpotJobSource/1.0"
DEFAULT_TIMEOUT = 25

_SECRET_RE = re.compile(
    r"(?i)(authorization|api[_-]?key|access[_-]?token|token|password|secret|app[_-]?key)"
    r"([\"'=\s:]+)([^\s\"'&,}{]+)"
)


def strip_secrets(text: str) -> str:
    if not text:
        return ""
    return _SECRET_RE.sub(r"\1\2[REDACTED]", str(text))


def _headers(extra: Optional[Mapping[str, str]] = None) -> dict[str, str]:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json, text/xml, */*",
    }
    if extra:
        headers.update({k: v for k, v in extra.items() if v is not None})
    return headers


def _raise_for_status(resp: requests.Response) -> None:
    code = resp.status_code
    if code == 429 or code >= 500:
        raise RateLimitError(f"http_{code}")
    if code >= 400:
        body = strip_secrets((resp.text or "")[:300])
        raise AdapterError(f"http_{code}:{body}")


def safe_get(
    url: str,
    *,
    params: Optional[Mapping[str, Any]] = None,
    headers: Optional[Mapping[str, str]] = None,
    timeout: float = DEFAULT_TIMEOUT,
    validate_url: bool = True,
    session: Optional[requests.Session] = None,
) -> requests.Response:
    if validate_url:
        validate_http_url(url, resolve_dns=False)
    try:
        client = session or requests
        resp = client.get(url, params=params, headers=_headers(headers), timeout=timeout)
    except SSRFError:
        raise
    except requests.RequestException as exc:
        raise AdapterError(strip_secrets(str(exc))) from exc
    _raise_for_status(resp)
    return resp


def safe_post(
    url: str,
    *,
    json: Any = None,
    data: Any = None,
    params: Optional[Mapping[str, Any]] = None,
    headers: Optional[Mapping[str, str]] = None,
    timeout: float = DEFAULT_TIMEOUT,
    validate_url: bool = True,
    session: Optional[requests.Session] = None,
) -> requests.Response:
    if validate_url:
        validate_http_url(url, resolve_dns=False)
    try:
        client = session or requests
        resp = client.post(
            url,
            json=json,
            data=data,
            params=params,
            headers=_headers(headers),
            timeout=timeout,
        )
    except SSRFError:
        raise
    except requests.RequestException as exc:
        raise AdapterError(strip_secrets(str(exc))) from exc
    _raise_for_status(resp)
    return resp


def merge_headers(*parts: Optional[Mapping[str, str]]) -> MutableMapping[str, str]:
    out: MutableMapping[str, str] = {}
    for part in parts:
        if part:
            out.update(part)
    return out
