# -*- coding: utf-8 -*-
"""Authenticated Vetution commercial sync client + upsert engine."""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

from .vetution_connection import mask_secret

_logger = logging.getLogger(__name__)

USER_AGENT = "PetSpotVetutionSupplier/1.0 (+odoo; phase1)"
REQUEST_DELAY = 0.2
MAX_RETRIES = 3
REQUEST_TIMEOUT = 40

# Phase 0 approved 24 UAT product slugs
PILOT_SLUGS = [
    "bravecto",
    "frontec-flea-tick-spray",
    "wenefro-advanced",
    "anti-flea-tick-shampoo-500-ml",
    "vetmedin-chewable-tablets",
    "nexgard-3-tablets",
    "pronefra",
    "simparica-trio-3-tablets",
    "omniguard-anti-parasitic-shampoo",
    "simparica-trio-6-tablets",
    "royal-canin-feline-care-nutrition-hairball-care",
    "royal-canin-gastrointestinal-cat-dry-kibble",
    "friskies-5-promises-cat-300-gm",
    "thyforon",
    "revolution-dog-3-doses",
    "fiproes-dog-spot-on",
    "frontec-flea-tick-shampoo",
    "advantix-4-doses",
    "revolution-cat-3-doses",
    "vanguard-plus-5cv-l",
    "cystaid",
    "effitix-4-ampoules",
    "cardisure",
    "friskies-cat-156-gm",
]


def _sanitize_for_log(text):
    if not text:
        return text
    out = str(text)
    # Scrub anything that looks like a JWT or Bearer header
    import re

    out = re.sub(r"Bearer\s+[A-Za-z0-9\-_\.]+", "Bearer ***", out, flags=re.I)
    out = re.sub(r"eyJ[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+", "***JWT***", out)
    return out


class VetutionCommercialSync(models.AbstractModel):
    _name = "vetution.commercial.sync"
    _description = "Vetution Commercial Sync"

    # ------------------------------------------------------------------ HTTP
    @api.model
    def _api_url(self, connection, path):
        base = (connection.base_url or "").rstrip("/") + "/"
        return urllib.parse.urljoin(base, path.lstrip("/"))

    @api.model
    def _http(self, connection, method, path, body=None, token=None, timeout=REQUEST_TIMEOUT):
        url = self._api_url(connection, path)
        headers = {
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
        if token:
            # Persist and send exactly as returned by login (already includes "Bearer ").
            headers["Authorization"] = token
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        last_err = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                time.sleep(REQUEST_DELAY)
                req = urllib.request.Request(url, data=data, headers=headers, method=method)
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    raw = resp.read().decode("utf-8", "replace")
                    try:
                        parsed = json.loads(raw) if raw else {}
                    except json.JSONDecodeError:
                        parsed = {"_nonjson": raw[:200]}
                    return resp.status, parsed
            except urllib.error.HTTPError as err:
                raw = err.read().decode("utf-8", "replace")
                try:
                    parsed = json.loads(raw) if raw else {}
                except json.JSONDecodeError:
                    parsed = {"_nonjson": raw[:200]}
                if err.code in (429, 500, 502, 503, 504) and attempt < MAX_RETRIES:
                    delay = 2 ** attempt
                    _logger.warning(
                        "Vetution HTTP %s on %s — retry in %ss",
                        err.code,
                        path,
                        delay,
                    )
                    time.sleep(delay)
                    last_err = err
                    continue
                return err.code, parsed
            except Exception as err:  # noqa: BLE001
                last_err = err
                if attempt < MAX_RETRIES:
                    delay = 2 ** attempt
                    _logger.warning(
                        "Vetution request failed (%s) — retry in %ss",
                        _sanitize_for_log(err),
                        delay,
                    )
                    time.sleep(delay)
                    continue
                raise UserError(
                    f"Vetution request failed for {path}: {_sanitize_for_log(err)}"
                ) from err
        raise UserError(f"Vetution request failed for {path}: {_sanitize_for_log(last_err)}")

    # ------------------------------------------------------------------ Auth
    @api.model
    def login(self, connection, force=False):
        connection.ensure_one()
        if not force and connection._get_stored_token() and not connection._token_needs_proactive_renewal():
            return connection._get_stored_token()

        if not connection.phone:
            connection.write({"state": "configuration_error", "last_error": "Phone is not configured."})
            raise UserError("Vetution connection phone is not configured.")

        try:
            password = connection._get_password()
        except UserError as err:
            connection.write({"state": "configuration_error", "last_error": str(err)})
            raise

        status, payload = self._http(
            connection,
            "POST",
            "/user/login",
            body={"phone": connection.phone, "password": password},
        )
        if status != 200 or not isinstance(payload, dict) or not payload.get("access_token"):
            # Never log password or full payload (may include token on weird responses)
            err_msg = "Login failed"
            if isinstance(payload, dict):
                err_msg = _sanitize_for_log(
                    payload.get("error") or payload.get("data") or err_msg
                )
            connection.write(
                {
                    "state": "authentication_error",
                    "last_error": f"HTTP {status}: {err_msg}",
                    "last_auth_check_at": fields.Datetime.now(),
                }
            )
            raise UserError(f"Vetution login failed (HTTP {status}).")

        token = payload["access_token"]
        user = payload.get("user") or {}
        accepted = bool(user.get("is_accepted"))
        expires_at = False
        # Decode exp claim locally without logging token
        try:
            import base64

            parts = token.split()
            jwt = parts[-1] if parts else token
            payload_b64 = jwt.split(".")[1]
            payload_b64 += "=" * (-len(payload_b64) % 4)
            claims = json.loads(base64.urlsafe_b64decode(payload_b64))
            if claims.get("exp"):
                expires_at = datetime.utcfromtimestamp(int(claims["exp"]))
        except Exception:  # noqa: BLE001
            expires_at = False

        connection._store_token(token, issued_at=fields.Datetime.now(), expires_at=expires_at)
        connection.write(
            {
                "user_id_external": user.get("id") or False,
                "account_is_accepted": accepted,
                "state": "connected" if accepted else "unaccepted",
                "last_auth_check_at": fields.Datetime.now(),
            }
        )
        if not accepted:
            raise UserError("Vetution account is not accepted (is_accepted=0).")
        _logger.info(
            "Vetution login ok for connection %s (user=%s, token=%s)",
            connection.id,
            user.get("id"),
            mask_secret(token),
        )
        return token

    @api.model
    def assert_authentication(self, connection, sample_drugs=None):
        """Mandatory auth assertion before any commercial write batch.

        Catalog endpoints return HTTP 200 with anonymous zeroed data when auth fails.
        Therefore we assert on a protected endpoint (/carts) and account acceptance.
        """
        connection.ensure_one()
        token = connection._get_stored_token()
        if not token or connection._token_needs_proactive_renewal():
            token = self.login(connection, force=True)

        status, payload = self._http(connection, "GET", "/carts", token=token)
        if status == 401:
            _logger.info("Vetution /carts returned 401 — re-login once")
            token = self.login(connection, force=True)
            status, payload = self._http(connection, "GET", "/carts", token=token)

        if status != 200:
            connection.write(
                {
                    "state": "authentication_error",
                    "last_error": f"Auth assertion failed: /carts HTTP {status}",
                    "last_auth_check_at": fields.Datetime.now(),
                }
            )
            raise UserError(
                f"Authentication assertion failed (/carts HTTP {status}). "
                "Commercial batch aborted; previous offers preserved."
            )

        if not connection.account_is_accepted:
            # Re-check profile if needed
            connection.write(
                {
                    "state": "unaccepted",
                    "last_error": "Account is_accepted is false.",
                    "last_auth_check_at": fields.Datetime.now(),
                }
            )
            raise UserError("Vetution account is not accepted. Commercial batch aborted.")

        # Optional catalog degradation probe
        if sample_drugs is not None:
            priced = sum(
                1
                for d in sample_drugs
                if d.get("show_price")
                or self._drug_has_positive_vetution_price(d)
            )
            if sample_drugs and priced == 0:
                connection.write(
                    {
                        "state": "authentication_error",
                        "last_error": (
                            "Silent auth degradation detected: catalog rows have "
                            "show_price=false and zero prices despite HTTP 200."
                        ),
                        "last_auth_check_at": fields.Datetime.now(),
                    }
                )
                raise UserError(
                    "Silent authentication degradation detected on catalog payload. "
                    "Commercial batch aborted; previous offers preserved."
                )

        connection.write(
            {
                "state": "connected",
                "last_auth_check_at": fields.Datetime.now(),
                "last_error": False,
            }
        )
        return token

    @api.model
    def _drug_has_positive_vetution_price(self, drug):
        for entry in drug.get("prices") or []:
            for _size, blocks in (entry or {}).items():
                vet = (blocks or {}).get("vetution") or {}
                try:
                    if float(vet.get("price") or 0) > 0:
                        return True
                except (TypeError, ValueError):
                    continue
        return False

    # ------------------------------------------------------------------ Parse / upsert
    @api.model
    def _iter_size_blocks(self, drug):
        for entry in drug.get("prices") or []:
            if not isinstance(entry, dict):
                continue
            for size_name, blocks in entry.items():
                yield size_name, blocks or {}

    @api.model
    def _build_offer_vals(
        self,
        connection,
        drug,
        size_name,
        blocks,
        offer_type,
        vendor=None,
        *,
        today=None,
        extra_flags=None,
    ):
        Offer = self.env["vetution.supplier.offer"]
        today = today or date.today()
        flags = list(extra_flags or [])
        show_price = bool(drug.get("show_price"))
        slug = drug.get("slug") or ""
        drug_id = drug.get("id")
        drug_name = (drug.get("name") or "")[:200]

        if offer_type == "vetution":
            src = (blocks or {}).get("vetution") or {}
            size_id = src.get("drug_size_id")
            vendor_dsid = False
            vendor_id = False
            vendor_name = False
            expiry_source = "vetution_offer"
            active_default = True
        else:
            src = vendor or {}
            size_id = ((blocks or {}).get("vetution") or {}).get("drug_size_id")
            vendor_dsid = src.get("vendor_drug_size_id")
            vendor_id = src.get("vendor_id")
            vendor_name = (src.get("vendor_name") or "")[:64]
            expiry_source = "vendor_offer"
            active_default = False

        qty, qty_raw, qty_flags = Offer.parse_qty(src.get("qty"))
        flags.extend(qty_flags)
        expiry = Offer.parse_expiry(src.get("expire_date"), today=today)
        flags.extend(expiry["flags"])

        show = bool(src.get("show", 1))
        price = src.get("price") or 0
        user_price = src.get("user_price") or 0
        effective = Offer.compute_effective_cost(price, user_price, show, show_price)
        if effective <= 0:
            flags.append("no_cost" if "no_cost" not in flags else "no_cost")

        strike = Offer.compute_strike_price(
            price, src.get("old_price_offer"), src.get("offer")
        )
        oos = bool(src.get("out_of_stock"))

        state, near, more_flags, procure_ok = Offer.normalize_availability(
            show=show,
            show_price=show_price,
            out_of_stock=oos,
            qty=qty,
            effective_cost=effective,
            is_expired=expiry["is_expired"],
            expiry_is_exact=expiry["expiry_is_exact"],
            days_to_expiry=expiry["days_to_expiry"],
            minimum_expiry_days=connection.minimum_expiry_days,
            near_expiry_days=connection.near_expiry_days,
            low_stock_threshold=connection.low_stock_threshold,
        )
        flags.extend(more_flags)

        # Expired exact dates: force expired state + block procurement
        if expiry["is_expired"] and expiry["expiry_is_exact"]:
            state = "expired"
            procure_ok = False

        # Expiry below minimum days: block procurement even if available
        if (
            expiry["expiry_is_exact"]
            and expiry["days_to_expiry"] is not False
            and expiry["days_to_expiry"] < (connection.minimum_expiry_days or 90)
            and not expiry["is_expired"]
        ):
            procure_ok = False
            if "expiry_below_minimum" not in flags:
                flags.append("expiry_below_minimum")

        if offer_type == "marketplace_vendor":
            procure_ok = False
            active_default = False

        if "duplicate_size_id_in_payload" in flags:
            procure_ok = False

        # Resolve Odoo variant
        product = self.env["product.product"]
        if size_id:
            product = self.env["product.product"].search(
                [("vetution_size_id", "=", size_id)], limit=1
            )
        if not product and offer_type == "vetution":
            flags.append("missing_variant_mapping")
            procure_ok = False

        # Sanitize raw JSON: never include Authorization; store only commercial block
        raw_payload = {
            "drug_id": drug_id,
            "slug": slug,
            "size_name": size_name,
            "offer_type": offer_type,
            "source": src,
        }
        data_hash = Offer.hash_payload(raw_payload)

        needs_review = bool(
            flags
            and any(
                f
                in {
                    "conflict_qty_pos",
                    "qty_negative",
                    "duplicate_size_id_in_payload",
                    "expiry_invalid",
                    "missing_variant_mapping",
                }
                for f in flags
            )
        )
        # Also review when expired / no cost for primary (informational)
        if offer_type == "vetution" and (
            state in ("expired",) or "duplicate_size_id_in_payload" in flags
        ):
            needs_review = True

        review_reason = "|".join(dict.fromkeys(flags)) if flags else False

        now = fields.Datetime.now()
        preview = connection.preview_sale_price(effective) if effective > 0 else 0.0

        vals = {
            "connection_id": connection.id,
            "product_id": product.id if product else False,
            "offer_type": offer_type,
            "vetution_drug_id": drug_id or False,
            "vetution_size_id": size_id or False,
            "vendor_drug_size_id": vendor_dsid or False,
            "external_vendor_id": vendor_id or False,
            "external_vendor_name": vendor_name or False,
            "size_name": size_name,
            "drug_slug": slug,
            "drug_name": drug_name,
            "supplier_price": float(price or 0),
            "supplier_user_price": float(user_price or 0),
            "effective_cost": effective,
            "strike_price": strike,
            "is_promo": bool(int(src.get("offer") or 0)),
            "promo_discount_raw": (
                str(src.get("discount")) if src.get("discount") is not None else False
            ),
            "is_express": bool(int(src.get("express") or 0)),
            "show": show,
            "show_price": show_price,
            "supplier_qty_raw": qty_raw or False,
            "supplier_qty": qty if qty is not False else 0.0,
            "supplier_out_of_stock": oos,
            "availability_state": state,
            "expiry_date": expiry["expiry_date"] or False,
            "expiry_text": expiry["expiry_text"] or False,
            "expiry_is_exact": expiry["expiry_is_exact"],
            "expiry_source": expiry_source,
            "days_to_expiry": (
                expiry["days_to_expiry"] if expiry["days_to_expiry"] is not False else False
            ),
            "is_expired": expiry["is_expired"],
            "is_near_expiry": near or expiry.get("is_near_expiry") or False,
            "active_for_procurement": bool(procure_ok and active_default),
            "needs_review": needs_review,
            "review_reason": review_reason,
            "last_seen_at": now,
            "last_commercial_sync_at": now,
            "is_stale": False,
            "raw_json": json.dumps(raw_payload, ensure_ascii=False, default=str),
            "data_hash": data_hash,
            "active": True,
            "preview_sale_price": preview,
        }
        # Near-expiry flag from days
        if (
            expiry["expiry_is_exact"]
            and expiry["days_to_expiry"] is not False
            and 0 <= expiry["days_to_expiry"] <= (connection.near_expiry_days or 180)
        ):
            vals["is_near_expiry"] = True

        return vals, flags, product

    @api.model
    def _upsert_offer(self, vals, metrics):
        Offer = self.env["vetution.supplier.offer"]
        offer_type = vals["offer_type"]
        domain = [("connection_id", "=", vals["connection_id"]), ("offer_type", "=", offer_type)]
        if offer_type == "vetution":
            if not vals.get("vetution_size_id"):
                metrics["invalid_prices"] = metrics.get("invalid_prices", 0) + 1
                return Offer.browse()
            domain.append(("vetution_size_id", "=", vals["vetution_size_id"]))
        else:
            if not vals.get("vendor_drug_size_id"):
                return Offer.browse()
            domain.append(("vendor_drug_size_id", "=", vals["vendor_drug_size_id"]))

        existing = Offer.search(domain, limit=1)
        if existing:
            if existing.data_hash == vals.get("data_hash") and not existing.is_stale:
                # Still refresh seen timestamps lightly
                existing.write(
                    {
                        "last_seen_at": vals["last_seen_at"],
                        "last_commercial_sync_at": vals["last_commercial_sync_at"],
                    }
                )
                metrics["offers_unchanged"] = metrics.get("offers_unchanged", 0) + 1
                return existing
            existing.write(vals)
            if offer_type == "marketplace_vendor":
                metrics["vendor_offers_updated"] = metrics.get("vendor_offers_updated", 0) + 1
            else:
                metrics["offers_updated"] = metrics.get("offers_updated", 0) + 1
            return existing

        rec = Offer.create(vals)
        if offer_type == "marketplace_vendor":
            metrics["vendor_offers_created"] = metrics.get("vendor_offers_created", 0) + 1
        else:
            metrics["offers_created"] = metrics.get("offers_created", 0) + 1
        return rec

    @api.model
    def process_drug(self, connection, drug, metrics, dry_run=False, quarantine_bucket=None):
        """Parse one drug payload and upsert offers. Detects duplicate size IDs."""
        seen_size_ids = {}
        quarantine_bucket = quarantine_bucket if quarantine_bucket is not None else []
        today = date.today()

        size_items = list(self._iter_size_blocks(drug))
        # First pass: detect duplicate vetution size ids in this payload
        size_id_counts = {}
        for size_name, blocks in size_items:
            vet = (blocks or {}).get("vetution") or {}
            sid = vet.get("drug_size_id")
            if sid is not None:
                size_id_counts[sid] = size_id_counts.get(sid, 0) + 1

        for size_name, blocks in size_items:
            vet = (blocks or {}).get("vetution") or {}
            sid = vet.get("drug_size_id")
            extra = []
            if sid is not None and size_id_counts.get(sid, 0) > 1:
                if sid in seen_size_ids:
                    # Duplicate occurrence — quarantine, do not upsert twice
                    metrics["duplicate_ids"] = metrics.get("duplicate_ids", 0) + 1
                    quarantine_bucket.append(
                        {
                            "slug": drug.get("slug"),
                            "size_name": size_name,
                            "vetution_size_id": sid,
                            "source": vet,
                            "reason": "duplicate_size_id_in_payload",
                        }
                    )
                    continue
                seen_size_ids[sid] = True
                extra.append("duplicate_size_id_in_payload")
                metrics["duplicate_ids"] = metrics.get("duplicate_ids", 0) + 1
                quarantine_bucket.append(
                    {
                        "slug": drug.get("slug"),
                        "size_name": size_name,
                        "vetution_size_id": sid,
                        "source": vet,
                        "reason": "duplicate_size_id_in_payload_kept",
                    }
                )

            vals, flags, product = self._build_offer_vals(
                connection,
                drug,
                size_name,
                blocks,
                "vetution",
                today=today,
                extra_flags=extra,
            )
            if not product and "missing_variant_mapping" in flags:
                metrics["missing_variant_mappings"] = (
                    metrics.get("missing_variant_mappings", 0) + 1
                )
            if vals["effective_cost"] <= 0:
                metrics["invalid_prices"] = metrics.get("invalid_prices", 0) + 1
            if "expiry_invalid" in flags or "expiry_unknown" in flags:
                if "expiry_invalid" in flags:
                    metrics["invalid_expiry"] = metrics.get("invalid_expiry", 0) + 1
            if "conflict_qty_pos" in flags or "qty_negative" in flags:
                metrics["conflicts"] = metrics.get("conflicts", 0) + 1

            offer = False
            if not dry_run:
                offer = self._upsert_offer(vals, metrics)
                if offer and offer.offer_type == "vetution":
                    si_metrics = self.env["product.supplierinfo"]._vetution_mirror_offer(offer)
                    for k, v in si_metrics.items():
                        metrics[k] = metrics.get(k, 0) + v
            else:
                metrics["offers_unchanged"] = metrics.get("offers_unchanged", 0) + 1

            # Marketplace vendors — audit only
            for vendor in (blocks or {}).get("vendors") or []:
                vvals, vflags, _ = self._build_offer_vals(
                    connection,
                    drug,
                    size_name,
                    blocks,
                    "marketplace_vendor",
                    vendor=vendor,
                    today=today,
                )
                if not dry_run:
                    self._upsert_offer(vvals, metrics)
                else:
                    metrics["vendor_offers_updated"] = (
                        metrics.get("vendor_offers_updated", 0) + 1
                    )

        metrics["products_processed"] = metrics.get("products_processed", 0) + 1

    # ------------------------------------------------------------------ Sync runners
    @api.model
    def _new_log(self, connection, sync_type, dry_run=False, note=None):
        return self.env["vetution.sync.log"].create(
            {
                "name": f"{sync_type} {fields.Datetime.now()}",
                "connection_id": connection.id,
                "sync_type": sync_type,
                "state": "running",
                "dry_run": dry_run,
                "note": note or False,
            }
        )

    @api.model
    def _finish_log(self, log, metrics, state="done", error=None, detail=None):
        started = log.started_at or fields.Datetime.now()
        ended = fields.Datetime.now()
        duration = (ended - started).total_seconds()
        vals = {
            "state": state,
            "ended_at": ended,
            "duration_seconds": duration,
            "pages_requested": metrics.get("pages_requested", 0),
            "pages_successful": metrics.get("pages_successful", 0),
            "pages_failed": metrics.get("pages_failed", 0),
            "products_processed": metrics.get("products_processed", 0),
            "offers_created": metrics.get("offers_created", 0),
            "offers_updated": metrics.get("offers_updated", 0),
            "offers_unchanged": metrics.get("offers_unchanged", 0),
            "vendor_offers_created": metrics.get("vendor_offers_created", 0),
            "vendor_offers_updated": metrics.get("vendor_offers_updated", 0),
            "missing_variant_mappings": metrics.get("missing_variant_mappings", 0),
            "duplicate_ids": metrics.get("duplicate_ids", 0),
            "invalid_prices": metrics.get("invalid_prices", 0),
            "invalid_expiry": metrics.get("invalid_expiry", 0),
            "conflicts": metrics.get("conflicts", 0),
            "authentication_failures": metrics.get("authentication_failures", 0),
            "supplierinfo_created": metrics.get("supplierinfo_created", 0),
            "supplierinfo_updated": metrics.get("supplierinfo_updated", 0),
            "supplierinfo_deactivated": metrics.get("supplierinfo_deactivated", 0),
            "error_summary": _sanitize_for_log(error) if error else False,
            "detail_json": json.dumps(detail or {}, ensure_ascii=False, default=str)[
                : 200000
            ]
            if detail
            else False,
        }
        log.write(vals)
        return log

    @api.model
    def sync_slugs(self, connection, slugs, sync_type="selected", dry_run=False):
        connection.ensure_one()
        metrics = {}
        quarantine = []
        log = self._new_log(connection, sync_type, dry_run=dry_run)

        try:
            token = self.assert_authentication(connection)
        except UserError as err:
            metrics["authentication_failures"] = 1
            self._finish_log(
                log, metrics, state="aborted_auth", error=str(err)
            )
            raise

        try:
            for slug in slugs:
                status, payload = self._http(
                    connection, "GET", f"/drugs/{slug}", token=token
                )
                metrics["pages_requested"] = metrics.get("pages_requested", 0) + 1
                if status == 401:
                    token = self.login(connection, force=True)
                    status, payload = self._http(
                        connection, "GET", f"/drugs/{slug}", token=token
                    )
                if status != 200:
                    metrics["pages_failed"] = metrics.get("pages_failed", 0) + 1
                    continue
                drug = payload.get("data", payload) if isinstance(payload, dict) else {}
                if not isinstance(drug, dict) or not drug.get("id"):
                    metrics["pages_failed"] = metrics.get("pages_failed", 0) + 1
                    continue
                # Silent degradation on a "should be priced" detail
                if not drug.get("show_price") and not self._drug_has_positive_vetution_price(drug):
                    # Could be legitimately hidden — only abort if ALL fail later
                    pass
                metrics["pages_successful"] = metrics.get("pages_successful", 0) + 1
                if not dry_run:
                    # savepoint per product
                    with self.env.cr.savepoint():
                        self.process_drug(
                            connection,
                            drug,
                            metrics,
                            dry_run=False,
                            quarantine_bucket=quarantine,
                        )
                else:
                    self.process_drug(
                        connection,
                        drug,
                        metrics,
                        dry_run=True,
                        quarantine_bucket=quarantine,
                    )
            # If zero products had show_price among successful pages, treat as degradation
            # (only when we expected commercial data). Soft check via auth already done.
            self._finish_log(
                log,
                metrics,
                state="done",
                detail={"quarantine": quarantine, "slugs": list(slugs)},
            )
            return log
        except Exception as err:  # noqa: BLE001
            self._finish_log(
                log,
                metrics,
                state="failed",
                error=_sanitize_for_log(err),
                detail={"quarantine": quarantine},
            )
            raise

    @api.model
    def sync_pilot(self, connection, dry_run=False):
        return self.sync_slugs(
            connection, PILOT_SLUGS, sync_type="pilot", dry_run=dry_run
        )

    @api.model
    def sync_full_commercial(self, connection, dry_run=False, max_pages=None):
        """Full paginated commercial list sync. Auth assertion mandatory."""
        connection.ensure_one()
        metrics = {}
        quarantine = []
        log = self._new_log(connection, "full_commercial", dry_run=dry_run)

        try:
            token = self.assert_authentication(connection)
        except UserError as err:
            metrics["authentication_failures"] = 1
            self._finish_log(log, metrics, state="aborted_auth", error=str(err))
            raise

        try:
            status, payload = self._http(
                connection, "GET", "/drugs?page=1", token=token
            )
            metrics["pages_requested"] = 1
            if status != 200:
                raise UserError(f"drugs page 1 failed HTTP {status}")
            data = payload.get("data", {})
            items = data.get("data") or []
            meta = data.get("meta") or {}
            last_page = int(meta.get("last_page") or 1)
            if max_pages:
                last_page = min(last_page, max_pages)

            # Degradation guard on first page
            self.assert_authentication(connection, sample_drugs=items)

            def _handle_page(page_items):
                for drug in page_items:
                    if dry_run:
                        self.process_drug(
                            connection, drug, metrics, dry_run=True, quarantine_bucket=quarantine
                        )
                    else:
                        with self.env.cr.savepoint():
                            self.process_drug(
                                connection,
                                drug,
                                metrics,
                                dry_run=False,
                                quarantine_bucket=quarantine,
                            )

            _handle_page(items)
            metrics["pages_successful"] = 1

            for page in range(2, last_page + 1):
                status, payload = self._http(
                    connection, "GET", f"/drugs?page={page}", token=token
                )
                metrics["pages_requested"] = metrics.get("pages_requested", 0) + 1
                if status == 401:
                    token = self.login(connection, force=True)
                    status, payload = self._http(
                        connection, "GET", f"/drugs?page={page}", token=token
                    )
                if status != 200:
                    metrics["pages_failed"] = metrics.get("pages_failed", 0) + 1
                    continue
                data = payload.get("data", {})
                page_items = data.get("data") or []
                # Quick degradation: if whole page zeroed, abort
                priced = sum(
                    1
                    for d in page_items
                    if d.get("show_price") or self._drug_has_positive_vetution_price(d)
                )
                if page_items and priced == 0:
                    metrics["authentication_failures"] = (
                        metrics.get("authentication_failures", 0) + 1
                    )
                    connection.write(
                        {
                            "state": "authentication_error",
                            "last_error": f"Silent degradation on drugs page {page}",
                        }
                    )
                    self._finish_log(
                        log,
                        metrics,
                        state="aborted_auth",
                        error=f"Silent degradation on page {page}",
                        detail={"quarantine": quarantine},
                    )
                    raise UserError(
                        f"Silent authentication degradation on page {page}. "
                        "Batch aborted; previous data preserved."
                    )
                _handle_page(page_items)
                metrics["pages_successful"] = metrics.get("pages_successful", 0) + 1
                # Checkpoint commit
                if not dry_run:
                    from odoo.tools import config as odoo_config

                    if not odoo_config.get("test_enable"):
                        self.env.cr.commit()  # noqa: intentional mid-sync checkpoint

            self._finish_log(
                log, metrics, state="done", detail={"quarantine": quarantine}
            )
            return log
        except UserError:
            raise
        except Exception as err:  # noqa: BLE001
            self._finish_log(
                log,
                metrics,
                state="failed",
                error=_sanitize_for_log(err),
                detail={"quarantine": quarantine},
            )
            raise

    # Cron stubs (disabled via XML active=False)
    @api.model
    def cron_commercial_refresh(self):
        connection = self.env["vetution.connection"].get_default_connection()
        if not connection.commercial_sync_enabled:
            _logger.info("Commercial sync cron skipped (commercial_sync_enabled=False)")
            return
        self.sync_full_commercial(connection, dry_run=False)

    @api.model
    def cron_reconciliation(self):
        connection = self.env["vetution.connection"].get_default_connection()
        if not connection.commercial_sync_enabled:
            return
        Offer = self.env["vetution.supplier.offer"]
        stale_before = fields.Datetime.now() - timedelta(
            hours=connection.stale_after_hours or 12
        )
        stale = Offer.search(
            [
                ("connection_id", "=", connection.id),
                ("last_commercial_sync_at", "<", stale_before),
                ("is_stale", "=", False),
            ]
        )
        stale.write({"is_stale": True})

    @api.model
    def cron_retry_failed(self):
        connection = self.env["vetution.connection"].get_default_connection()
        if not connection.commercial_sync_enabled:
            return
        # Phase 1: no persistent retry queue yet — no-op when disabled.
        return
