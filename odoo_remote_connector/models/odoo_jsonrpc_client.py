# -*- coding: utf-8 -*-
"""Minimal JSON-RPC client for remote Odoo instances."""
from __future__ import annotations

import json
import logging
import ssl
import urllib.error
import urllib.request

_logger = logging.getLogger(__name__)


class OdooJsonRpcClient:
    def __init__(self, url: str, db: str, username: str, secret: str, timeout: int = 120):
        self.url = self.normalize_url(url)
        self.db = db
        self.username = username
        self.secret = secret
        self.timeout = timeout
        self.uid: int | None = None
        self._ctx = ssl.create_default_context()

    @staticmethod
    def normalize_url(url: str) -> str:
        url = (url or "").strip().rstrip("/")
        if url.endswith("/odoo"):
            url = url[: -len("/odoo")]
        return url

    def _call(self, service: str, method: str, args: list):
        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {"service": service, "method": method, "args": args},
            "id": 1,
        }
        req = urllib.request.Request(
            f"{self.url}/jsonrpc",
            data=json.dumps(payload).encode(),
            headers={
                "Content-Type": "application/json",
                "User-Agent": "OdooRemoteConnector/1.0",
            },
        )
        try:
            with urllib.request.urlopen(req, context=self._ctx, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"HTTP {exc.code} from {self.url}") from exc
        if data.get("error"):
            err = data["error"]
            msg = err.get("data", {}).get("message") or err.get("message") or str(err)
            raise RuntimeError(msg)
        return data.get("result")

    def authenticate(self) -> int:
        uid = self._call(
            "common",
            "authenticate",
            [self.db, self.username, self.secret, {}],
        )
        if not uid:
            raise RuntimeError("Authentication failed (check URL, database, user, and secret)")
        self.uid = uid
        return uid

    def execute(self, model: str, method: str, *args, **kwargs):
        if self.uid is None:
            self.authenticate()
        return self._call(
            "object",
            "execute_kw",
            [self.db, self.uid, self.secret, model, method, list(args), kwargs or {}],
        )

    def search_read(self, model: str, domain: list, fields: list, **kwargs):
        return self.execute(model, "search_read", domain, fields=fields, **kwargs)
