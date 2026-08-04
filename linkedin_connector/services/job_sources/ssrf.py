# -*- coding: utf-8 -*-
"""SSRF guards for outbound job-source HTTP URLs."""

from __future__ import annotations

import ipaddress
import logging
import socket
from typing import Optional
from urllib.parse import urlparse

from .base import AdapterError

_logger = logging.getLogger(__name__)

_BLOCKED_NETWORKS = (
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),  # link-local + cloud metadata
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
)


class SSRFError(AdapterError):
    """URL rejected by SSRF policy."""


def _is_blocked_ip(ip: ipaddress._BaseAddress) -> bool:
    if ip.is_loopback or ip.is_link_local or ip.is_private or ip.is_reserved or ip.is_multicast:
        return True
    for net in _BLOCKED_NETWORKS:
        if ip in net:
            return True
    return False


def validate_http_url(url: str, *, resolve_dns: bool = True) -> str:
    """Validate ``url`` is http(s) and not targeting loopback/link-local/metadata.

    Returns the stripped URL on success. Raises ``SSRFError`` otherwise.
    Blocks literal ``169.254.169.254`` (cloud metadata) and private ranges.
    """
    raw = (url or "").strip()
    if not raw:
        raise SSRFError("empty_url")
    parsed = urlparse(raw)
    scheme = (parsed.scheme or "").lower()
    if scheme not in {"http", "https"}:
        raise SSRFError("scheme_not_allowed")
    host = (parsed.hostname or "").strip().lower()
    if not host:
        raise SSRFError("missing_host")
    if host in {"localhost", "metadata.google.internal", "metadata"}:
        raise SSRFError("blocked_host")

    # Literal IP in hostname
    try:
        ip = ipaddress.ip_address(host)
        if _is_blocked_ip(ip):
            raise SSRFError("blocked_ip")
    except ValueError:
        ip = None

    if resolve_dns and ip is None:
        try:
            infos = socket.getaddrinfo(host, parsed.port or (443 if scheme == "https" else 80))
        except socket.gaierror as exc:
            _logger.info("ssrf dns failed host=%s err=%s", host, exc)
            raise SSRFError("dns_resolution_failed") from exc
        for info in infos:
            sockaddr = info[4]
            addr = sockaddr[0]
            try:
                resolved = ipaddress.ip_address(addr)
            except ValueError:
                continue
            if _is_blocked_ip(resolved):
                raise SSRFError("blocked_resolved_ip")

    return raw
