# -*- coding: utf-8 -*-
"""JSON-RPC client for remote Odoo Online (no external dependencies)."""
from __future__ import annotations

import json
import logging
import ssl
import urllib.error
import urllib.request

_logger = logging.getLogger(__name__)


class OdooJsonRpc:
    def __init__(self, url: str, db: str, username: str, secret: str, timeout: int = 120):
        self.url = self.normalize_url(url)
        self.db = db
        self.username = username
        self.secret = secret
        self.timeout = timeout
        self.uid = None
        self._ctx = ssl.create_default_context()

    @staticmethod
    def normalize_url(url: str) -> str:
        url = (url or "").rstrip("/")
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
            headers={"Content-Type": "application/json"},
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
            raise RuntimeError("Authentication failed (check URL, DB, user, API key)")
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

    def create(self, model: str, vals: dict | list):
        return self.execute(model, "create", vals)

    def write(self, model: str, ids: list, vals: dict):
        return self.execute(model, "write", ids, vals)

    def unlink(self, model: str, ids: list):
        return self.execute(model, "unlink", ids)


def get_remote_client(env) -> OdooJsonRpc:
    ICP = env["ir.config_parameter"].sudo()
    url = ICP.get_param("social_media_connector.remote_url", "")
    db = ICP.get_param("social_media_connector.remote_db", "")
    user = ICP.get_param("social_media_connector.remote_username", "")
    secret = ICP.get_param("social_media_connector.remote_api_key", "")
    if not url or not db or not user or not secret:
        raise RuntimeError(
            "Remote Odoo not configured. Open Social Media Connector → Configuration → Settings."
        )
    return OdooJsonRpc(url, db, user, secret)


def test_remote_connection(env) -> dict:
    client = get_remote_client(env)
    uid = client.authenticate()
    modules = {}
    for name in ("social", "social_facebook"):
        rows = client.search_read("ir.module.module", [("name", "=", name)], ["name", "state"], limit=1)
        modules[name] = rows[0]["state"] if rows else "missing"
    pages = client.search_read(
        "social.account",
        [("media_id.media_type", "=", "facebook")],
        ["id", "name"],
        limit=50,
    )
    return {
        "uid": uid,
        "url": client.url,
        "db": client.db,
        "modules": modules,
        "page_count": len(pages),
    }


def fetch_remote_facebook_pages(env) -> list[dict]:
    client = get_remote_client(env)
    client.authenticate()
    return client.search_read(
        "social.account",
        [("media_id.media_type", "=", "facebook")],
        ["id", "name", "facebook_account_id", "facebook_access_token", "is_media_disconnected"],
        order="id asc",
    )


_REMOTE_POST_FIELDS = [
    "id",
    "message",
    "state",
    "scheduled_date",
    "post_method",
    "account_ids",
    "image_ids",
    "published_date",
]


def fetch_remote_sahel_posts(client: OdooJsonRpc) -> list[dict]:
    """Return social.post rows from Online matching PetSpot El Sahel campaign."""
    client.authenticate()
    return client.search_read(
        "social.post",
        [
            "|",
            ("message", "ilike", "Sahel"),
            ("message", "ilike", "الساحل"),
        ],
        _REMOTE_POST_FIELDS,
        order="id asc",
    )


def fetch_all_remote_posts(client: OdooJsonRpc, campaign_prefix: str = "") -> list[dict]:
    """Return all social.post rows from Online (optionally filtered by campaign prefix)."""
    client.authenticate()
    domain = [("message", "ilike", campaign_prefix)] if campaign_prefix else []
    posts = client.search_read("social.post", domain, _REMOTE_POST_FIELDS, order="id asc")
    if not posts and campaign_prefix:
        posts = client.search_read("social.post", [], _REMOTE_POST_FIELDS, order="id asc")
    return posts


_STREAM_POST_FIELDS = [
    "id",
    "message",
    "published_date",
    "stream_post_image_ids",
    "facebook_post_id",
    "link_image_url",
    "link_title",
    "link_description",
    "account_id",
    "media_type",
]


def fetch_all_feed_posts(client: OdooJsonRpc, account_ids: list[int] | None = None) -> list[dict]:
    """Return Facebook feed posts (social.stream.post) from Odoo Online."""
    client.authenticate()
    domain: list = [("media_type", "=", "facebook")]
    if account_ids:
        domain = [("account_id", "in", account_ids)] + domain
    return client.search_read(
        "social.stream.post",
        domain,
        _STREAM_POST_FIELDS,
        order="published_date desc",
    )
