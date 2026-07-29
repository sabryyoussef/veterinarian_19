# -*- coding: utf-8 -*-
"""Create / refresh ShipBlu shipments from Odoo pickings."""

from __future__ import annotations

import json
import logging
import re

from odoo import _, fields
from odoo.exceptions import UserError

from odoo.addons.delivery_shipblu.services.status_mapping import normalize_shipblu_status
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
        return f"ODOO-{picking.company_id.id}-{picking.id}-{picking.name}"

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

    def assert_can_create(self, picking, backend):
        backend.assert_write_allowed("create")
        if not backend.default_package_size:
            raise UserError(_("Set Default Package Size ID on the ShipBlu backend before creating shipments."))
        if not backend.default_zone_id:
            raise UserError(_("Set Default Drop-off Zone ID on the ShipBlu backend."))
        from odoo.addons.delivery_shipblu.services.duplicate_guard import DuplicateGuard

        DuplicateGuard(self.env).assert_can_create_shipblu(picking)
        existing = self.env["shipblu.shipment"].search(
            [("picking_id", "=", picking.id), ("shipblu_order_id", "!=", False)], limit=1
        )
        if existing:
            raise UserError(_("ShipBlu shipment already exists for this picking: %s") % existing.name)

    def _partner_phone(self, partner):
        raw = partner.mobile or partner.phone or ""
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

    def build_payload(self, picking, backend):
        partner = picking.partner_id
        line_1 = (partner.street or partner.street2 or partner.city or "Address").strip()
        line_2 = (partner.street2 or backend.fallback_line_2 or "EG").strip() or "EG"
        # what3words: API schema may require it; send placeholder if unknown
        what3words = "filled.by.odoo"
        phone = self._partner_phone(partner)
        cod = self.compute_cod_amount(picking)
        payload = {
            "customer": {
                "full_name": partner.name or "Customer",
                "phone": phone,
                "email": partner.email or False,
                "address": {
                    "line_1": line_1[:200],
                    "line_2": line_2[:200],
                    "what3words": what3words,
                    "zone": int(backend.default_zone_id),
                },
            },
            "packages": [{"package_size": int(backend.default_package_size)}],
            "cash_amount": float(cod),
            "merchant_order_reference": self.business_reference_for_picking(picking),
            "order_notes": picking.name,
        }
        if not payload["customer"]["email"]:
            payload["customer"].pop("email")
        return payload, cod

    def create_from_picking(self, picking):
        picking.ensure_one()
        backend = self._backend(picking.company_id)
        self.assert_can_create(picking, backend)
        Shipment = self.env["shipblu.shipment"]
        shipment = Shipment.search([("picking_id", "=", picking.id)], limit=1)
        ref = self.business_reference_for_picking(picking)
        if not shipment:
            shipment = Shipment.create(
                {
                    "picking_id": picking.id,
                    "sale_order_id": picking.sale_id.id if picking.sale_id else False,
                    "backend_id": backend.id,
                    "company_id": picking.company_id.id,
                    "business_reference": ref,
                    "shipment_owner": "odoo_shipblu",
                    "creation_source": "odoo",
                    "state": "creating",
                }
            )
        else:
            shipment.write({"state": "creating", "business_reference": ref, "backend_id": backend.id})

        payload, cod = self.build_payload(picking, backend)
        shipment.write(
            {
                "cod_amount": cod,
                "payload_snapshot": json.dumps(redact_payload(payload), ensure_ascii=False)[:8000],
            }
        )
        client = backend.get_client()
        try:
            result = client.create_delivery_order(payload)
        except ShipBluApiError as exc:
            shipment.write({"state": "error", "last_error": str(exc)[:2000]})
            raise UserError(str(exc)) from exc

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
            "normalized_status": normalize_shipblu_status(raw_status),
            "state": "created" if order_id else "error",
            "last_error": False if order_id else _("Create response missing order id"),
            "shipment_owner": "odoo_shipblu",
        }
        shipment.write(vals)
        picking_vals = {
            "carrier_tracking_ref": tracking or picking.carrier_tracking_ref,
            "shipblu_order_id": str(order_id) if order_id else False,
            "shipblu_shipment_owner": "odoo_shipblu",
        }
        if picking.carrier_id and picking.carrier_id.delivery_type == "shipblu":
            pass
        elif not picking.carrier_id:
            carrier = self.env["delivery.carrier"].search(
                [("delivery_type", "=", "shipblu"), ("company_id", "in", [False, picking.company_id.id])],
                limit=1,
            )
            if carrier:
                picking_vals["carrier_id"] = carrier.id
        picking.write(picking_vals)
        return shipment

    def refresh_shipment(self, shipment):
        shipment.ensure_one()
        if not shipment.shipblu_order_id:
            raise UserError(_("No ShipBlu order id to refresh."))
        client = shipment.backend_id.get_client()
        result = client.get_delivery_order(shipment.shipblu_order_id)
        raw = result.get("status") if isinstance(result, dict) else False
        tracking = result.get("tracking_number") if isinstance(result, dict) else False
        from odoo.addons.delivery_shipblu.services.status_mapping import coerce_raw_status

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
