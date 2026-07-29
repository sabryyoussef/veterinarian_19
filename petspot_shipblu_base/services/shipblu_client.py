# -*- coding: utf-8 -*-
"""ShipBlu HTTP client — https://docs.shipblu.com/ (Authorization: Api-Key …)."""

from __future__ import annotations

import json
import logging
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from odoo.exceptions import UserError

from .redaction import redact_headers, redact_payload

_logger = logging.getLogger(__name__)


class ShipBluApiError(Exception):
    def __init__(self, message, status_code=None, payload=None, transient=False):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload
        self.transient = transient


class ShipBluClient:
    def __init__(self, backend, env=None):
        self.backend = backend
        self.env = env or backend.env
        self.api_key = (backend.api_key or "").strip()
        self.timeout = int(backend.timeout_seconds or 30)
        self.max_retries = int(backend.max_retries or 3)
        self.base = (backend.api_base or "https://api.shipblu.com/api").rstrip("/")

    def _headers(self):
        return {
            "Authorization": f"Api-Key {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Requested-By": "petspot-odoo-shipblu",
        }

    def _log(self, method, url, status, request_body=None, response_body=None, duration_ms=0, error=None):
        Log = self.env["shipblu.api.log"].sudo()
        try:
            Log.create(
                {
                    "backend_id": self.backend.id,
                    "company_id": self.backend.company_id.id,
                    "method": method,
                    "url": url,
                    "http_status": status or 0,
                    "duration_ms": int(duration_ms or 0),
                    "request_headers": json.dumps(redact_headers(self._headers()), ensure_ascii=False)[:4000],
                    "request_body": json.dumps(redact_payload(request_body), ensure_ascii=False)[:8000]
                    if request_body is not None
                    else False,
                    "response_body": json.dumps(redact_payload(response_body), ensure_ascii=False)[:8000]
                    if response_body is not None
                    else False,
                    "error_message": (error or "")[:2000] or False,
                }
            )
        except Exception:
            _logger.exception("Failed to persist ShipBlu API log")

    @staticmethod
    def _parse_body(raw: bytes):
        if not raw:
            return None
        text = raw.decode("utf-8", errors="replace")
        try:
            return json.loads(text)
        except Exception:
            return text

    def request(self, method, path, params=None, payload=None, allow_retry=True):
        if not self.api_key:
            raise UserError("ShipBlu API key is not configured.")
        url = f"{self.base}{path}"
        if params:
            url = f"{url}?{urlencode(params, doseq=True)}"
        body_bytes = None
        if payload is not None:
            body_bytes = json.dumps(payload).encode("utf-8")

        attempts = self.max_retries if allow_retry else 1
        last_error = None
        for attempt in range(1, attempts + 1):
            started = time.monotonic()
            try:
                req = Request(url, data=body_bytes, headers=self._headers(), method=method.upper())
                with urlopen(req, timeout=self.timeout) as resp:
                    raw = resp.read()
                    duration = (time.monotonic() - started) * 1000
                    parsed = self._parse_body(raw)
                    self._log(method.upper(), url, resp.status, payload, parsed, duration)
                    return parsed if parsed is not None else {}
            except HTTPError as exc:
                duration = (time.monotonic() - started) * 1000
                raw = exc.read() if hasattr(exc, "read") else b""
                parsed = self._parse_body(raw)
                msg = f"ShipBlu HTTP {exc.code}: {parsed if isinstance(parsed, str) else json.dumps(parsed)[:500]}"
                self._log(method.upper(), url, exc.code, payload, parsed, duration, error=msg)
                transient = exc.code in (408, 425, 429, 500, 502, 503, 504)
                last_error = ShipBluApiError(msg, status_code=exc.code, payload=parsed, transient=transient)
                if not (allow_retry and transient and attempt < attempts):
                    raise last_error
                time.sleep(min(2 ** attempt, 8))
            except URLError as exc:
                duration = (time.monotonic() - started) * 1000
                msg = f"ShipBlu network error: {exc}"
                self._log(method.upper(), url, 0, payload, None, duration, error=msg)
                last_error = ShipBluApiError(msg, transient=True)
                if not (allow_retry and attempt < attempts):
                    raise last_error
                time.sleep(min(2 ** attempt, 8))
        raise last_error or ShipBluApiError("ShipBlu request failed")

    # ---- high-level helpers ----
    def get_merchants(self):
        return self.request("GET", "/v1/merchants/")

    def get_governorates(self):
        return self.request("GET", "/v1/governorates/")

    def get_cities(self, governorate_id):
        return self.request("GET", f"/v1/governorates/{int(governorate_id)}/cities/")

    def get_zones(self, city_id):
        return self.request("GET", f"/v1/cities/{int(city_id)}/zones/")

    def get_pickup_points(self, limit=50):
        return self.request("GET", "/v1/pickup-points/", params={"limit": limit})

    def list_delivery_orders(self, limit=10, offset=0):
        return self.request("GET", "/v1/delivery-orders/", params={"limit": limit, "offset": offset})

    def get_delivery_order(self, order_id):
        return self.request("GET", f"/v1/delivery-orders/{order_id}/")

    def create_delivery_order(self, payload):
        return self.request("POST", "/v1/delivery-orders/", payload=payload, allow_retry=False)

    def request_pickup(self, tracking_numbers):
        if isinstance(tracking_numbers, (list, tuple)):
            tracking_numbers = ",".join(str(t) for t in tracking_numbers)
        return self.request(
            "POST",
            "/v1/delivery-orders/request-pickup/",
            params={"tracking_numbers": tracking_numbers},
            allow_retry=False,
        )

    def get_shipping_label(self, order_id, label_type="pdf"):
        """Return parsed JSON or raw bytes for PDF labels."""
        return self.request_raw(
            "GET",
            f"/v1/delivery-orders/{order_id}/shipping-label/",
            params={"type": label_type},
            allow_retry=True,
        )

    def get_orders_shipping_label(self, tracking_numbers, label_type="pdf", one_per_page=False):
        if isinstance(tracking_numbers, (list, tuple)):
            tracking_numbers = ",".join(str(t) for t in tracking_numbers)
        params = {"tracking_numbers": tracking_numbers, "type": label_type}
        if one_per_page:
            params["one_per_page"] = "True"
        return self.request_raw("GET", "/v1/orders/shipping-label/", params=params)

    def list_returns(self, limit=50, offset=0):
        return self.request("GET", "/v1/returns/", params={"limit": limit, "offset": offset})

    def get_return(self, return_id):
        return self.request("GET", f"/v1/returns/{return_id}/")

    def create_return(self, payload):
        return self.request("POST", "/v1/returns/", payload=payload, allow_retry=False)

    def list_exchanges(self, limit=50, offset=0):
        return self.request("GET", "/v1/exchanges/", params={"limit": limit, "offset": offset})

    def get_exchange(self, exchange_id):
        return self.request("GET", f"/v1/exchanges/{exchange_id}/")

    def create_exchange(self, payload, version="v1"):
        path = "/v2/exchanges/" if version == "v2" else "/v1/exchanges/"
        return self.request("POST", path, payload=payload, allow_retry=False)

    def list_cash_collections(self, limit=50, offset=0):
        return self.request("GET", "/v1/cash-collections/", params={"limit": limit, "offset": offset})

    def get_cash_collection(self, cc_id):
        return self.request("GET", f"/v1/cash-collections/{cc_id}/")

    def create_cash_collection(self, payload):
        return self.request("POST", "/v1/cash-collections/", payload=payload, allow_retry=False)

    def get_return_points(self, limit=50, offset=0):
        return self.request("GET", "/v1/return-points/", params={"limit": limit, "offset": offset})

    def request_raw(self, method, path, params=None, payload=None, allow_retry=True):
        """Like request(), but returns bytes when response is not JSON (e.g. PDF)."""
        if not self.api_key:
            raise UserError("ShipBlu API key is not configured.")
        url = f"{self.base}{path}"
        if params:
            url = f"{url}?{urlencode(params, doseq=True)}"
        body_bytes = None
        if payload is not None:
            body_bytes = json.dumps(payload).encode("utf-8")
        attempts = self.max_retries if allow_retry else 1
        last_error = None
        for attempt in range(1, attempts + 1):
            started = time.monotonic()
            try:
                req = Request(url, data=body_bytes, headers=self._headers(), method=method.upper())
                with urlopen(req, timeout=self.timeout) as resp:
                    raw = resp.read()
                    duration = (time.monotonic() - started) * 1000
                    ctype = (resp.headers.get("Content-Type") or "").lower()
                    if "json" in ctype or (raw[:1] in (b"{", b"[")):
                        parsed = self._parse_body(raw)
                        self._log(method.upper(), url, resp.status, payload, parsed, duration)
                        return parsed if parsed is not None else {}
                    self._log(
                        method.upper(),
                        url,
                        resp.status,
                        payload,
                        {"_binary": True, "bytes": len(raw), "content_type": ctype},
                        duration,
                    )
                    return raw
            except HTTPError as exc:
                duration = (time.monotonic() - started) * 1000
                raw = exc.read() if hasattr(exc, "read") else b""
                parsed = self._parse_body(raw)
                msg = f"ShipBlu HTTP {exc.code}: {parsed if isinstance(parsed, str) else json.dumps(parsed)[:500]}"
                self._log(method.upper(), url, exc.code, payload, parsed, duration, error=msg)
                transient = exc.code in (408, 425, 429, 500, 502, 503, 504)
                last_error = ShipBluApiError(msg, status_code=exc.code, payload=parsed, transient=transient)
                if not (allow_retry and transient and attempt < attempts):
                    raise last_error
                time.sleep(min(2 ** attempt, 8))
            except URLError as exc:
                duration = (time.monotonic() - started) * 1000
                msg = f"ShipBlu network error: {exc}"
                self._log(method.upper(), url, 0, payload, None, duration, error=msg)
                last_error = ShipBluApiError(msg, transient=True)
                if not (allow_retry and attempt < attempts):
                    raise last_error
                time.sleep(min(2 ** attempt, 8))
        raise last_error or ShipBluApiError("ShipBlu request failed")
