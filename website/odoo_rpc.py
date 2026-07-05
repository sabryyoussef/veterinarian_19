"""Minimal Odoo JSON-RPC client for website deploy scripts."""
from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from typing import Any


class OdooRPC:
    def __init__(self, url: str, db: str, username: str, secret: str, timeout: int = 120):
        self.url = url.rstrip("/")
        self.db = db
        self.username = username
        self.secret = secret
        self.timeout = timeout
        self.uid: int | None = None
        self._ctx = ssl.create_default_context()

    def _call(self, service: str, method: str, args: list) -> Any:
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
                "User-Agent": "OdooRPC/1.0",
            },
        )
        try:
            with urllib.request.urlopen(req, context=self._ctx, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"HTTP {exc.code} from {self.url}") from exc
        if data.get("error"):
            raise RuntimeError(data["error"])
        return data.get("result")

    def authenticate(self) -> int:
        uid = self._call(
            "common",
            "authenticate",
            [self.db, self.username, self.secret, {}],
        )
        if not uid:
            raise RuntimeError("Authentication failed (check DB, user, API key/password)")
        self.uid = uid
        return uid

    def execute(self, model: str, method: str, *args, **kwargs) -> Any:
        if self.uid is None:
            self.authenticate()
        return self._call(
            "object",
            "execute_kw",
            [self.db, self.uid, self.secret, model, method, list(args), kwargs or {}],
        )

    def search_read(self, model: str, domain: list, fields: list, **kwargs) -> list[dict]:
        return self.execute(model, "search_read", domain, fields=fields, **kwargs)

    def write(self, model: str, ids: list[int], vals: dict) -> bool:
        return self.execute(model, "write", ids, vals)

    def create(self, model: str, vals: dict | list[dict]) -> int | list[int]:
        return self.execute(model, "create", vals)
