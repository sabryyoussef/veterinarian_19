# -*- coding: utf-8 -*-
"""Create / refresh ShipBlu shipments from Odoo pickings (duplicate-guarded)."""

from __future__ import annotations

import json
import logging
import re

from odoo import _, fields
from odoo.exceptions import UserError

from odoo.addons.delivery_shipblu.services.duplicate_guard import DuplicateGuard
from odoo.addons.delivery_shipblu.services.status_mapping import (
    coerce_raw_status,
    normalize_shipblu_status,
)
from odoo.addons.petspot_shipblu_base.services.redaction import redact_payload
from odoo.addons.petspot_shipblu_base.services.shipblu_client import ShipBluApiError

_logger = logging.getLogger(__name__)
_PHONE_RE = re.compile(r"(01[0125]\d{8})")


class ShipmentService:
    def __init__(self, env):
        self.env = env

    def _backend(self, company):
        return self.env["shipblu.backend"]._get_for_company(company)

    def business_reference_for_picking(self, picking):
        """Canonical merchant_order_reference / idempotency key (stable across retries)."""
        return DuplicateGuard(self.env).canonical_shipment_key(picking)

    def compute_cod_amount(self, picking):
        order = picking.sale_id
        if not order:
            return 0.0
        total = float(order.amount_total or 0.0)
        paid = 0.0
        if "amount_paid" in order._fields:
            paid = float(order.amount_paid or 0.0)
        if hasattr(order, "invoice_ids"):
            invoiced_paid = sum(
                float(inv.amount_total or 0.0)
                for inv in order.invoice_ids.filtered(
                    lambda i: i.state == "posted" and i.payment_state in ("paid", "in_payment")
                )
            )
            paid = max(paid, invoiced_paid)
        if "payment_state" in order._fields and order.payment_state in ("paid", "in_payment"):
            paid = max(paid, total)
        residual = max(total - paid, 0.0)
        if paid >= total - 0.01:
            return 0.0
        return residual

    def assert_can_create(self, picking, backend, overrides=None):
        overrides = overrides or {}
        backend.assert_write_allowed("create")
        package_size = int(overrides.get("package_size") or backend.default_package_size or 0)
        if not package_size:
            raise UserError(
                _(
                    "Package size ID unresolved. Set Default Package Size ID or pass an explicit "
                    "verified package_size — never guess."
                )
            )
        size_map = self.env["shipblu.package.size"].search(
            [
                ("backend_id", "=", backend.id),
                ("shipblu_size_id", "=", package_size),
                ("active", "=", True),
            ],
            limit=1,
        )
        if backend.package_size_ids and not size_map:
            raise UserError(
                _(
                    "Package size ID %(id)s is not mapped on the backend. "
                    "Map it under Package Sizes before live create."
                )
                % {"id": package_size}
            )
        if not backend.default_zone_id and not overrides.get("zone"):
            raise UserError(_("Set Default Drop-off Zone ID on the ShipBlu backend."))

        weight = float(overrides.get("weight_kg") or 0.0)
        if not weight and picking:
            weight = sum(float(m.product_id.weight or 0.0) * float(m.quantity or m.product_uom_qty or 0.0)
                         for m in picking.move_ids)
        max_w = float(backend.max_shipment_weight_kg or 10.0)
        if backend.enable_package_weight_blocking and weight > max_w:
            if not overrides.get("weight_override"):
                raise UserError(
                    _("Shipment weight %(w).3f kg exceeds maximum %(m).3f kg. Apply an authorized override.")
                    % {"w": weight, "m": max_w}
                )

        if backend.enable_coverage_blocking:
            zone_id = int(overrides.get("zone") or backend.default_zone_id or 0)
            zone = self.env["shipblu.zone"].search(
                [
                    ("backend_id", "=", backend.id),
                    ("shipblu_id", "=", zone_id),
                    ("active", "=", True),
                    ("covered", "=", True),
                ],
                limit=1,
            )
            if not zone:
                raise UserError(
                    _("Destination zone %(z)s is unmapped or not covered. Refusing silent substitution.")
                    % {"z": zone_id}
                )

        if backend.enable_wallet_validation:
            cod = overrides.get("cash_amount")
            if cod is None:
                cod = self.compute_cod_amount(picking) if picking else 0.0
            if float(cod or 0.0) == 0.0:
                bal = backend.effective_wallet_balance()
                # Soft warning by default; hard block only if configured
                if backend.enable_wallet_hard_block and bal <= 0:
                    raise UserError(
                        _("Zero-COD shipment blocked: wallet balance %(b).2f is insufficient.")
                        % {"b": bal}
                    )

    def _partner_phone(self, partner):
        raw = getattr(partner, "mobile", None) or partner.phone or ""
        digits = re.sub(r"\D", "", raw)
        if digits.startswith("002"):
            digits = digits[2:]
        if digits.startswith("2") and len(digits) > 11:
            digits = digits[1:]
        m = _PHONE_RE.search(digits) or _PHONE_RE.search(raw.replace(" ", ""))
        if m:
            return m.group(1)
        if digits.startswith("01") and len(digits) >= 11:
            return digits[:11]
        raise UserError(_("Consignee needs an Egyptian mobile (01xxxxxxxxx). Got: %s") % (raw or "(empty)"))

    def build_payload(self, picking, backend, overrides=None, merchant_reference=None):
        overrides = overrides or {}
        partner = picking.partner_id
        line_1 = (partner.street or partner.street2 or partner.city or "Address").strip()
        line_2 = (partner.street2 or backend.fallback_line_2 or "EG").strip() or "EG"
        what3words = overrides.get("what3words") or "filled.by.odoo"
        phone = self._partner_phone(partner)
        cod = overrides["cash_amount"] if "cash_amount" in overrides else self.compute_cod_amount(picking)
        zone = int(overrides.get("zone") or backend.default_zone_id)
        package_size = int(overrides.get("package_size") or backend.default_package_size)
        ref = merchant_reference or self.business_reference_for_picking(picking)
        notes = overrides.get("order_notes") or picking.name
        if picking.sale_id:
            notes = f"{picking.sale_id.name} | {picking.name}"
        payload = {
            "customer": {
                "full_name": partner.name or "Customer",
                "phone": phone,
                "email": partner.email or False,
                "address": {
                    "line_1": (overrides.get("line_1") or line_1)[:200],
                    "line_2": (overrides.get("line_2") or line_2)[:200],
                    "what3words": what3words,
                    "zone": zone,
                },
            },
            "packages": [{"package_size": package_size}],
            "cash_amount": float(cod),
            "merchant_order_reference": ref,
            "order_notes": notes,
        }
        if overrides.get("is_counter_dropoff"):
            payload["is_counter_dropoff"] = True
        if overrides.get("allow_open_package"):
            payload["is_customer_allowed_to_open_packages"] = True
        if not payload["customer"]["email"]:
            payload["customer"].pop("email")
        return payload, cod, ref

    def _apply_create_result(self, shipment, picking, backend, result, canonical_key):
        order_id = result.get("id") if isinstance(result, dict) else None
        tracking = None
        if isinstance(result, dict):
            tracking = result.get("tracking_number") or result.get("tracking_no")
            packages = result.get("packages") or []
            if not tracking and packages and isinstance(packages[0], dict):
                tracking = packages[0].get("tracking_number")
        raw_status = result.get("status") if isinstance(result, dict) else False
        vals = {
            "shipblu_order_id": str(order_id) if order_id else False,
            "tracking_number": tracking or False,
            "tracking_url": backend.tracking_url_for(tracking) if tracking else False,
            "raw_status": raw_status or False,
            "shipblu_status": coerce_raw_status(raw_status) or False,
            "normalized_status": normalize_shipblu_status(raw_status),
            "state": "created" if order_id else "error",
            "last_error": False if order_id else _("Create response missing order id"),
            "shipment_owner": "odoo_shipblu",
            "creation_source": "odoo",
            "canonical_shipment_key": canonical_key,
            "duplicate_guard_status": "created",
            "duplicate_detection_source": False,
            "business_reference": canonical_key,
        }
        if picking.sale_id and getattr(picking.sale_id, "shopify_order_id", None):
            vals["shopify_order_id"] = str(picking.sale_id.shopify_order_id)
        shipment.write(vals)
        picking_vals = {
            "carrier_tracking_ref": tracking or picking.carrier_tracking_ref,
            "shipblu_order_id": str(order_id) if order_id else False,
            "shipblu_shipment_owner": "odoo_shipblu",
            "shipblu_canonical_key": canonical_key,
            "shipblu_duplicate_guard_status": "created",
            "shipblu_duplicate_detection_source": False,
        }
        if not picking.carrier_id:
            carrier = self.env["delivery.carrier"].search(
                [("delivery_type", "=", "shipblu"), ("company_id", "in", [False, picking.company_id.id])],
                limit=1,
            )
            if carrier:
                picking_vals["carrier_id"] = carrier.id
        picking.write(picking_vals)
        self._maybe_push_tracking_to_shopify(picking, tracking)
        return shipment

    def _maybe_push_tracking_to_shopify(self, picking, tracking):
        """Push AWB to Shopify only if no fulfillment exists yet (safe bridge)."""
        if not tracking or not picking.sale_id:
            return
        order = picking.sale_id
        if getattr(order, "shopify_fulfilled", False):
            return
        if getattr(order, "shopify_fulfillment_ids", None):
            return
        if getattr(picking, "shopify_fulfillment_origin", None) == "shopify":
            return
        # Do not invent a fulfillment push here if connector cron already handles
        # done pickings with tracking — only set origin to odoo so cron may push once.
        if "shopify_fulfillment_origin" in picking._fields and not picking.shopify_fulfillment_origin:
            try:
                picking.write({"shopify_fulfillment_origin": "odoo"})
            except Exception:  # noqa: BLE001
                _logger.debug("Could not set shopify_fulfillment_origin", exc_info=True)

    def create_from_picking(self, picking, overrides=None):
        picking.ensure_one()
        backend = self._backend(picking.company_id)
        self.assert_can_create(picking, backend)
        guard = DuplicateGuard(self.env)
        canonical_key = guard.canonical_shipment_key(picking)

        # Concurrency: advisory lock + row lock
        guard.advisory_lock(canonical_key)
        guard.lock_picking(picking)
        picking.invalidate_recordset()

        # Persist key early (idempotent)
        picking.write(
            {
                "shipblu_canonical_key": canonical_key,
                "shipblu_duplicate_guard_status": "checking",
            }
        )

        # Block if prior ambiguous create awaiting verification
        existing_vr = self.env["shipblu.shipment"].search(
            [
                ("canonical_shipment_key", "=", canonical_key),
                ("state", "=", "verification_required"),
            ],
            limit=1,
        )
        if existing_vr and not existing_vr.shipblu_order_id:
            hit = guard.remote_lookup(backend, picking, canonical_key)
            if hit and (hit.shipblu_order_id or hit.tracking):
                return guard.reconcile(picking, backend, hit, canonical_key)
            raise UserError(
                _(
                    "ShipBlu create is in verification_required for key %(key)s. "
                    "Remote lookup found nothing yet — resolve manually or sync, "
                    "do not force another create."
                )
                % {"key": canonical_key}
            )

        hit = guard.find_existing(picking, backend, canonical_key, do_remote=True)
        if hit:
            if hit.source == "verification_required" and not hit.shipblu_order_id and not hit.tracking:
                raise UserError(hit.note or _("Verification required — create blocked."))
            shipment = guard.reconcile(picking, backend, hit, canonical_key)
            # Return shipment; caller shows user message
            shipment = shipment.with_context(
                shipblu_reconciled=True,
                shipblu_guard_message=_(
                    "Existing ShipBlu AWB found and linked; no new delivery was created."
                ),
                shipblu_guard_source=hit.source,
            )
            return shipment

        Shipment = self.env["shipblu.shipment"]
        shipment = Shipment.search(
            [
                "|",
                ("picking_id", "=", picking.id),
                ("canonical_shipment_key", "=", canonical_key),
            ],
            limit=1,
        )
        if not shipment:
            shipment = Shipment.create(
                {
                    "picking_id": picking.id,
                    "sale_order_id": picking.sale_id.id if picking.sale_id else False,
                    "backend_id": backend.id,
                    "company_id": picking.company_id.id,
                    "business_reference": canonical_key,
                    "canonical_shipment_key": canonical_key,
                    "shipment_owner": "odoo_shipblu",
                    "creation_source": "odoo",
                    "state": "creating",
                    "duplicate_guard_status": "creating",
                    "shopify_order_id": (
                        str(picking.sale_id.shopify_order_id)
                        if picking.sale_id and getattr(picking.sale_id, "shopify_order_id", None)
                        else False
                    ),
                }
            )
        else:
            if shipment.shipblu_order_id:
                from odoo.addons.delivery_shipblu.services.duplicate_guard import GuardHit

                return guard.reconcile(
                    picking,
                    backend,
                    GuardHit(
                        source="imported_delivery",
                        shipment_id=shipment.id,
                        shipblu_order_id=shipment.shipblu_order_id,
                        tracking=shipment.tracking_number or None,
                        note=_("Already linked"),
                    ),
                    canonical_key,
                )
            shipment.write(
                {
                    "state": "creating",
                    "business_reference": canonical_key,
                    "canonical_shipment_key": canonical_key,
                    "backend_id": backend.id,
                    "duplicate_guard_status": "creating",
                }
            )

        payload, cod, ref = self.build_payload(
            picking, backend, overrides=overrides, merchant_reference=canonical_key
        )
        assert ref == canonical_key
        shipment.write(
            {
                "cod_amount": cod,
                "payload_snapshot": json.dumps(redact_payload(payload), ensure_ascii=False)[:8000],
                "last_remote_precheck_at": fields.Datetime.now(),
                "idempotency_key": canonical_key,
            }
        )

        client = backend.get_client()
        try:
            result = client.create_delivery_order(payload)
        except ShipBluApiError as exc:
            transient = bool(getattr(exc, "transient", False) or exc.status_code in (0, 408, 504, None))
            if transient or exc.status_code in (0, 408, 502, 503, 504):
                # Ambiguous — never blind retry. Mark verification_required then reconcile.
                shipment.write(
                    {
                        "state": "verification_required",
                        "duplicate_guard_status": "verification_required",
                        "last_error": str(exc)[:2000],
                        "reconciliation_notes": _(
                            "Create request ambiguous (%s). Remote reconcile required before retry."
                        )
                        % exc,
                    }
                )
                picking.write({"shipblu_duplicate_guard_status": "verification_required"})
                from odoo.tools import config as odoo_config

                # Persist before UserError rolls back the HTTP request cursor (not allowed in tests).
                if not odoo_config.get("test_enable"):
                    self.env.cr.commit()
                try:
                    remote = client.find_by_merchant_order_reference(canonical_key)
                except ShipBluApiError:
                    remote = None
                if remote and remote.get("id"):
                    return self._apply_create_result(shipment, picking, backend, remote, canonical_key)
                raise UserError(
                    _(
                        "ShipBlu create timed out or failed ambiguously. "
                        "Marked verification_required for key %(key)s. "
                        "Sync/import before any retry — do not create again blindly. Error: %(err)s"
                    )
                    % {"key": canonical_key, "err": exc}
                ) from exc
            shipment.write({"state": "error", "last_error": str(exc)[:2000], "duplicate_guard_status": "error"})
            raise UserError(str(exc)) from exc

        if not isinstance(result, dict) or not result.get("id"):
            remote = client.find_by_merchant_order_reference(canonical_key)
            if remote and remote.get("id"):
                result = remote
            else:
                shipment.write(
                    {
                        "state": "verification_required",
                        "duplicate_guard_status": "verification_required",
                        "last_error": _("Create response missing order id"),
                    }
                )
                picking.write({"shipblu_duplicate_guard_status": "verification_required"})
                from odoo.tools import config as odoo_config

                if not odoo_config.get("test_enable"):
                    self.env.cr.commit()
                raise UserError(
                    _(
                        "ShipBlu create response missing id and remote lookup empty — "
                        "verification_required for %s"
                    )
                    % canonical_key
                )

        return self._apply_create_result(shipment, picking, backend, result, canonical_key)

    def refresh_shipment(self, shipment):
        shipment.ensure_one()
        if not shipment.shipblu_order_id:
            raise UserError(_("No ShipBlu order id to refresh."))
        client = shipment.backend_id.get_client()
        result = client.get_delivery_order(shipment.shipblu_order_id)
        raw = result.get("status") if isinstance(result, dict) else False
        tracking = result.get("tracking_number") if isinstance(result, dict) else False
        norm = normalize_shipblu_status(raw)
        state = "tracking"
        if norm == "delivered":
            state = "done"
        elif norm == "cancelled":
            state = "cancelled"
        elif shipment.needs_matching:
            state = "needs_matching"
        shipment.write(
            {
                "raw_status": raw or shipment.raw_status,
                "shipblu_status": coerce_raw_status(raw) or shipment.shipblu_status,
                "normalized_status": norm,
                "tracking_number": tracking or shipment.tracking_number,
                "tracking_url": shipment.backend_id.tracking_url_for(tracking or shipment.tracking_number),
                "state": state,
                "last_sync_at": fields.Datetime.now(),
                "last_sync_result": "refreshed",
                "payload_snapshot": json.dumps(redact_payload(result), ensure_ascii=False)[:8000]
                if isinstance(result, dict)
                else shipment.payload_snapshot,
            }
        )
        Event = self.env["shipblu.shipment.event"].sudo()
        code = str(raw or "refresh")[:64]
        last = Event.search([("shipment_id", "=", shipment.id)], limit=1, order="event_at desc, id desc")
        if not last or last.event_code != code:
            Event.create(
                {
                    "shipment_id": shipment.id,
                    "event_code": code,
                    "event_label": str(raw or "refresh"),
                    "event_at": fields.Datetime.now(),
                }
            )
        if tracking and shipment.picking_id and not shipment.needs_matching:
            if (
                not shipment.picking_id.carrier_tracking_ref
                or shipment.picking_id.carrier_tracking_ref == tracking
            ):
                shipment.picking_id.carrier_tracking_ref = tracking
        return shipment
