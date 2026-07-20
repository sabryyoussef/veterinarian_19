# -*- coding: utf-8 -*-
"""OpenProject API v3 client (OpClient style from infra/openproject/scripts)."""
from __future__ import annotations

import base64
import json
import logging
import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

_logger = logging.getLogger(__name__)


class OpenProjectAPIError(Exception):
    """Structured OpenProject API failure."""

    def __init__(self, message: str, status_code: int | None = None, body: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.body = body

    @property
    def is_conflict(self) -> bool:
        return self.status_code == 409


class OpenProjectClient:
    """HTTP client for OpenProject API v3."""

    def __init__(
        self,
        base_url: str,
        token: str,
        host_header: str = "",
        verify_ssl: bool = True,
        timeout: int = 120,
    ) -> None:
        self.base = (base_url or "").rstrip("/")
        self.host = (host_header or "").strip()
        self.timeout = timeout
        self.auth = base64.b64encode(f"apikey:{token}".encode()).decode()

        class RH(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return urllib.request.Request(
                    newurl,
                    data=req.data,
                    headers=req.headers,
                    method=req.get_method(),
                )

        if verify_ssl:
            self.opener = urllib.request.build_opener(RH)
        else:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            self.opener = urllib.request.build_opener(
                RH, urllib.request.HTTPSHandler(context=ctx)
            )

    def request(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        query: dict | None = None,
    ) -> dict:
        if not path.startswith("/"):
            path = "/" + path
        url = f"{self.base}{path}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query, doseq=True)}"

        headers = {
            "Authorization": f"Basic {self.auth}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self.host:
            headers["Host"] = self.host

        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with self.opener.open(req, timeout=self.timeout) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            err_body = e.read().decode(errors="replace")[:2000]
            raise OpenProjectAPIError(
                f"{method} {path} -> {e.code}: {err_body[:800]}",
                status_code=e.code,
                body=err_body,
            ) from e
        except urllib.error.URLError as e:
            raise OpenProjectAPIError(f"{method} {path} -> URL error: {e}") from e

    def get(self, path: str, query: dict | None = None) -> dict:
        return self.request("GET", path, query=query)

    def post(self, path: str, body: dict) -> dict:
        return self.request("POST", path, body=body)

    def patch(self, path: str, body: dict) -> dict:
        return self.request("PATCH", path, body=body)

    def test_connection(self) -> dict:
        return self.get("/api/v3")

    def get_work_package(self, wp_id: int) -> dict:
        return self.get(f"/api/v3/work_packages/{int(wp_id)}")

    def list_project_work_packages(
        self,
        project_id: int,
        *,
        updated_after: str | None = None,
        offset: int = 1,
        page_size: int = 100,
        only_this_project: bool = True,
    ) -> dict:
        filters: list[dict[str, Any]] = []
        # Restrict to WPs whose primary project is this one (avoids subproject /
        # related WP duplicates that thrash Odoo ownership across maps).
        if only_this_project:
            filters.append(
                {
                    "project": {
                        "operator": "=",
                        "values": [str(int(project_id))],
                    }
                }
            )
        if updated_after:
            filters.append(
                {
                    "updatedAt": {
                        "operator": "<>d",
                        "values": [updated_after, ""],
                    }
                }
            )
        query: dict[str, Any] = {
            "offset": offset,
            "pageSize": page_size,
        }
        if filters:
            query["filters"] = json.dumps(filters)
        return self.get(
            f"/api/v3/projects/{int(project_id)}/work_packages",
            query=query,
        )

    def list_work_packages(
        self,
        *,
        project_ids: list[int] | None = None,
        updated_after: str | None = None,
        offset: int = 1,
        page_size: int = 100,
    ) -> dict:
        """Global WP list (preferred for full sync across many projects)."""
        filters: list[dict[str, Any]] = []
        if project_ids:
            filters.append(
                {
                    "project": {
                        "operator": "=",
                        "values": [str(int(p)) for p in project_ids],
                    }
                }
            )
        if updated_after:
            filters.append(
                {
                    "updatedAt": {
                        "operator": "<>d",
                        "values": [updated_after, ""],
                    }
                }
            )
        query: dict[str, Any] = {
            "offset": offset,
            "pageSize": page_size,
        }
        if filters:
            query["filters"] = json.dumps(filters)
        return self.get("/api/v3/work_packages", query=query)

    def create_work_package(self, body: dict) -> dict:
        return self.post("/api/v3/work_packages", body)

    def update_work_package(self, wp_id: int, body: dict) -> dict:
        return self.patch(f"/api/v3/work_packages/{int(wp_id)}", body)

    @staticmethod
    def href_id(href: str | None) -> int | None:
        if not href:
            return None
        try:
            return int(str(href).rstrip("/").split("/")[-1])
        except (TypeError, ValueError):
            return None

    @staticmethod
    def wp_description_raw(wp: dict) -> str:
        desc = wp.get("description") or {}
        if isinstance(desc, dict):
            return desc.get("raw") or ""
        return str(desc or "")

    @staticmethod
    def wp_link_id(wp: dict, rel: str) -> int | None:
        links = (wp.get("_links") or {}).get(rel) or {}
        return OpenProjectClient.href_id(links.get("href"))
