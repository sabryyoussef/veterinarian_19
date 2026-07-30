# -*- coding: utf-8 -*-
"""Wizards that mirror ShipBlu merchant portal write actions."""

from __future__ import annotations

import base64
import json
import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.delivery_shipblu.services.shipment_service import ShipmentService
from odoo.addons.delivery_shipblu.services.status_mapping import normalize_shipblu_status
from odoo.addons.petspot_shipblu_base.services.redaction import redact_payload
from odoo.addons.petspot_shipblu_base.services.shipblu_client import ShipBluApiError

_PHONE_RE = re.compile(r"(01[0125]\d{8})")


def _normalize_eg_phone(raw):
    digits = re.sub(r"\D", "", raw or "")
    if digits.startswith("002"):
        digits = digits[2:]
    if digits.startswith("2") and len(digits) > 11:
        digits = digits[1:]
    m = _PHONE_RE.search(digits) or _PHONE_RE.search((raw or "").replace(" ", ""))
    if m:
        return m.group(1)
    if digits.startswith("01") and len(digits) >= 11:
        return digits[:11]
    raise UserError(_("Egyptian mobile required (01xxxxxxxxx). Got: %s") % (raw or "(empty)"))


class ShipBluCreateDeliveryWizard(models.TransientModel):
    _name = "shipblu.create.delivery.wizard"
    _description = "Create ShipBlu Delivery Order"

    backend_id = fields.Many2one(
        "shipblu.backend",
        required=True,
        default=lambda self: self.env["shipblu.backend"].search(
            [("company_id", "=", self.env.company.id)], limit=1
        ),
    )
    picking_id = fields.Many2one("stock.picking", string="Delivery Order")
    sale_order_id = fields.Many2one("sale.order")
    partner_id = fields.Many2one("res.partner")

    customer_name = fields.Char(required=True)
    customer_phone = fields.Char(required=True)
    customer_email = fields.Char()
    address_line_1 = fields.Char(required=True)
    address_line_2 = fields.Char(required=True, default="EG")
    what3words = fields.Char(default="filled.by.odoo")
    zone_id = fields.Many2one("shipblu.zone", string="Drop-off Zone")
    zone_shipblu_id = fields.Integer(string="Zone ID", required=True)
    package_size = fields.Integer(required=True, default=1)
    cash_amount = fields.Float(string="COD Amount", digits="Product Price")
    declared_value = fields.Char()
    order_notes = fields.Char()
    merchant_order_reference = fields.Char()
    is_counter_dropoff = fields.Boolean(string="Counter Drop-off")
    allow_open_package = fields.Boolean(string="Allow Open Package")
    fragile = fields.Boolean()

    @api.onchange("picking_id")
    def _onchange_picking(self):
        if not self.picking_id:
            return
        p = self.picking_id
        partner = p.partner_id
        self.sale_order_id = p.sale_id
        self.partner_id = partner
        self.customer_name = partner.name
        self.customer_phone = partner.mobile or partner.phone
        self.customer_email = partner.email
        self.address_line_1 = partner.street or partner.street2 or partner.city or "Address"
        self.address_line_2 = partner.street2 or (self.backend_id.fallback_line_2 if self.backend_id else "EG") or "EG"
        self.order_notes = p.name
        self.merchant_order_reference = f"ODOO-{p.company_id.id}-{p.id}-{p.name}"
        if self.backend_id:
            self.zone_shipblu_id = self.backend_id.default_zone_id
            self.package_size = self.backend_id.default_package_size or 1
            self.cash_amount = ShipmentService(self.env).compute_cod_amount(p)

    @api.onchange("partner_id")
    def _onchange_partner(self):
        if not self.partner_id or self.picking_id:
            return
        partner = self.partner_id
        self.customer_name = partner.name
        self.customer_phone = partner.mobile or partner.phone
        self.customer_email = partner.email
        self.address_line_1 = partner.street or partner.street2 or partner.city or "Address"
        self.address_line_2 = partner.street2 or (self.backend_id.fallback_line_2 if self.backend_id else "EG") or "EG"

    @api.onchange("zone_id")
    def _onchange_zone(self):
        if self.zone_id:
            self.zone_shipblu_id = self.zone_id.shipblu_id

    @api.onchange("backend_id")
    def _onchange_backend(self):
        if self.backend_id:
            if not self.zone_shipblu_id:
                self.zone_shipblu_id = self.backend_id.default_zone_id
            if not self.package_size:
                self.package_size = self.backend_id.default_package_size or 1

    def action_quote(self):
        self.ensure_one()
        backend = self.backend_id
        zone = self.env["shipblu.zone"].search(
            [("shipblu_id", "=", self.zone_shipblu_id), ("company_id", "=", backend.company_id.id)],
            limit=1,
        )
        # pricing needs governorate — derive via city if synced
        gov_id = False
        if zone and zone.city_shipblu_id:
            city = self.env["shipblu.city"].search(
                [("shipblu_id", "=", zone.city_shipblu_id), ("company_id", "=", backend.company_id.id)],
                limit=1,
            )
            gov_id = city.governorate_shipblu_id if city else False
        if not gov_id:
            raise UserError(_("Sync coverage and pick a known zone so governorate can be resolved for pricing."))
        try:
            result = backend.get_client().get_pricing(
                "delivery",
                {
                    "to_governorate": int(gov_id),
                    "cash_amount": float(self.cash_amount or 0.0),
                    "packages": [int(self.package_size)],
                    "is_customer_allowed_to_open_packages": bool(self.allow_open_package),
                },
            )
        except ShipBluApiError as exc:
            raise UserError(str(exc)) from exc
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("ShipBlu Price Quote"),
                "message": _("subtotal=%(s)s VAT=%(v)s total=%(t)s")
                % {
                    "s": result.get("subtotal"),
                    "v": result.get("vat"),
                    "t": result.get("total"),
                },
                "type": "success",
                "sticky": True,
            },
        }

    def action_create(self):
        self.ensure_one()
        backend = self.backend_id
        backend.assert_write_allowed("create")
        if not self.picking_id:
            raise UserError(
                _(
                    "Select a delivery transfer (picking). Unguarded manual creates without a picking "
                    "are blocked by the Duplicate AWB Guard — use Operations → Create Delivery with a picking."
                )
            )
        if not backend.default_package_size:
            backend.sudo().write({"default_package_size": self.package_size})
        shipment = ShipmentService(self.env).create_from_picking(
            self.picking_id,
            overrides={
                "zone": int(self.zone_shipblu_id),
                "package_size": int(self.package_size),
                "cash_amount": float(self.cash_amount or 0.0),
                "line_1": self.address_line_1,
                "line_2": self.address_line_2,
                "what3words": self.what3words or "filled.by.odoo",
                "is_counter_dropoff": self.is_counter_dropoff,
                "allow_open_package": self.allow_open_package,
            },
        )
        return {
            "type": "ir.actions.act_window",
            "res_model": "shipblu.shipment",
            "res_id": shipment.id,
            "view_mode": "form",
            "target": "current",
            "context": {
                "default_notification": shipment.env.context.get("shipblu_guard_message")
                or False,
            },
        }


class ShipBluCreateReturnWizard(models.TransientModel):
    _name = "shipblu.create.return.wizard"
    _description = "Create ShipBlu Return Order"

    backend_id = fields.Many2one(
        "shipblu.backend",
        required=True,
        default=lambda self: self.env["shipblu.backend"].search(
            [("company_id", "=", self.env.company.id)], limit=1
        ),
    )
    customer_name = fields.Char(required=True)
    customer_phone = fields.Char(required=True)
    customer_email = fields.Char()
    address_line_1 = fields.Char(required=True)
    address_line_2 = fields.Char(required=True, default="EG")
    what3words = fields.Char(default="filled.by.odoo")
    zone_shipblu_id = fields.Integer(string="Zone ID", required=True)
    package_size = fields.Integer(required=True, default=1)
    order_notes = fields.Char(required=True, default="Return from Odoo")
    cash_amount = fields.Float(digits="Product Price")
    merchant_order_reference = fields.Char()
    is_counter_dropoff = fields.Boolean()

    @api.onchange("backend_id")
    def _onchange_backend(self):
        if self.backend_id:
            self.zone_shipblu_id = self.backend_id.default_zone_id
            self.package_size = self.backend_id.default_package_size or 1

    def action_create(self):
        self.ensure_one()
        backend = self.backend_id
        backend.assert_write_allowed("create return")
        phone = _normalize_eg_phone(self.customer_phone)
        payload = {
            "customer": {
                "full_name": self.customer_name,
                "phone": phone,
                "address": {
                    "line_1": self.address_line_1[:200],
                    "line_2": self.address_line_2[:200],
                    "what3words": (self.what3words or "filled.by.odoo")[:80],
                    "zone": int(self.zone_shipblu_id),
                },
            },
            "packages": [{"package_size": int(self.package_size)}],
            "order_notes": self.order_notes,
            "cash_amount": float(self.cash_amount or 0.0),
            "is_counter_dropoff": bool(self.is_counter_dropoff),
        }
        if self.customer_email:
            payload["customer"]["email"] = self.customer_email
        if self.merchant_order_reference:
            payload["merchant_order_reference"] = self.merchant_order_reference
        try:
            result = backend.get_client().create_return(payload)
        except ShipBluApiError as exc:
            raise UserError(str(exc)) from exc
        rid = str((result or {}).get("id") or "")
        tracking = (result or {}).get("tracking_number") or False
        if rid:
            self.env["shipblu.return.order"].create(
                {
                    "name": tracking or rid,
                    "backend_id": backend.id,
                    "company_id": backend.company_id.id,
                    "shipblu_return_id": rid,
                    "tracking_number": tracking,
                    "raw_status": (result or {}).get("status") or False,
                    "payload_json": json.dumps(redact_payload(result), ensure_ascii=False)[:8000],
                }
            )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("ShipBlu Return"),
                "message": _("Created return #%(id)s AWB=%(awb)s") % {"id": rid or "?", "awb": tracking or "-"},
                "type": "success",
                "sticky": False,
            },
        }


class ShipBluCreateCashWizard(models.TransientModel):
    _name = "shipblu.create.cash.wizard"
    _description = "Create ShipBlu Cash Collection"

    backend_id = fields.Many2one(
        "shipblu.backend",
        required=True,
        default=lambda self: self.env["shipblu.backend"].search(
            [("company_id", "=", self.env.company.id)], limit=1
        ),
    )
    customer_name = fields.Char(required=True)
    customer_phone = fields.Char(required=True)
    address_line_1 = fields.Char(required=True)
    address_line_2 = fields.Char(required=True, default="EG")
    what3words = fields.Char(default="filled.by.odoo")
    zone_shipblu_id = fields.Integer(string="Zone ID", required=True)
    amount = fields.Float(string="Collection Amount", required=True, digits="Product Price")

    @api.onchange("backend_id")
    def _onchange_backend(self):
        if self.backend_id:
            self.zone_shipblu_id = self.backend_id.default_zone_id

    def action_create(self):
        self.ensure_one()
        backend = self.backend_id
        backend.assert_write_allowed("create cash collection")
        phone = _normalize_eg_phone(self.customer_phone)
        payload = {
            "customer": {
                "full_name": self.customer_name,
                "phone": phone,
                "address": {
                    "line_1": self.address_line_1[:200],
                    "line_2": self.address_line_2[:200],
                    "what3words": (self.what3words or "filled.by.odoo")[:80],
                    "zone": int(self.zone_shipblu_id),
                },
            },
            "amount": float(self.amount),
        }
        try:
            result = backend.get_client().create_cash_collection(payload)
        except ShipBluApiError as exc:
            raise UserError(str(exc)) from exc
        cid = str((result or {}).get("id") or "")
        tracking = (result or {}).get("tracking_number") or False
        if cid:
            self.env["shipblu.cash.collection"].create(
                {
                    "name": tracking or cid,
                    "backend_id": backend.id,
                    "company_id": backend.company_id.id,
                    "shipblu_cc_id": cid,
                    "tracking_number": tracking,
                    "raw_status": (result or {}).get("status") or False,
                    "payload_json": json.dumps(redact_payload(result), ensure_ascii=False)[:8000],
                }
            )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("ShipBlu Cash Collection"),
                "message": _("Created #%(id)s AWB=%(awb)s") % {"id": cid or "?", "awb": tracking or "-"},
                "type": "success",
                "sticky": False,
            },
        }


class ShipBluCreateExchangeWizard(models.TransientModel):
    _name = "shipblu.create.exchange.wizard"
    _description = "Create ShipBlu Exchange (v2)"

    backend_id = fields.Many2one(
        "shipblu.backend",
        required=True,
        default=lambda self: self.env["shipblu.backend"].search(
            [("company_id", "=", self.env.company.id)], limit=1
        ),
    )
    customer_name = fields.Char(required=True)
    customer_phone = fields.Char(required=True)
    address_line_1 = fields.Char(required=True)
    address_line_2 = fields.Char(required=True, default="EG")
    zone_shipblu_id = fields.Integer(string="Zone ID", required=True)
    package_size = fields.Integer(required=True, default=1)
    cash_amount = fields.Float(digits="Product Price")
    refund_amount = fields.Float(digits="Product Price")
    refund = fields.Boolean()
    order_notes = fields.Char()
    merchant_order_reference = fields.Char()

    @api.onchange("backend_id")
    def _onchange_backend(self):
        if self.backend_id:
            self.zone_shipblu_id = self.backend_id.default_zone_id
            self.package_size = self.backend_id.default_package_size or 1

    def action_create(self):
        self.ensure_one()
        backend = self.backend_id
        backend.assert_write_allowed("create exchange")
        phone = _normalize_eg_phone(self.customer_phone)
        payload = {
            "customer": {
                "full_name": self.customer_name,
                "phone": phone,
                "address": {
                    "line_1": self.address_line_1[:200],
                    "line_2": self.address_line_2[:200],
                    "zone": int(self.zone_shipblu_id),
                },
            },
            "packages": [{"package_size": int(self.package_size)}],
            "cash_amount": float(self.cash_amount or 0.0),
            "refund": bool(self.refund),
            "refund_amount": float(self.refund_amount or 0.0),
        }
        if self.order_notes:
            payload["order_notes"] = self.order_notes
        if self.merchant_order_reference:
            payload["merchant_order_reference"] = self.merchant_order_reference
        try:
            result = backend.get_client().create_exchange(payload, version="v2")
        except ShipBluApiError as exc:
            raise UserError(str(exc)) from exc
        eid = str((result or {}).get("id") or "")
        tracking = (result or {}).get("tracking_number") or False
        if eid:
            self.env["shipblu.exchange.order"].create(
                {
                    "name": tracking or eid,
                    "backend_id": backend.id,
                    "company_id": backend.company_id.id,
                    "shipblu_exchange_id": eid,
                    "tracking_number": tracking,
                    "raw_status": (result or {}).get("status") or False,
                    "payload_json": json.dumps(redact_payload(result), ensure_ascii=False)[:8000],
                }
            )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("ShipBlu Exchange"),
                "message": _("Created #%(id)s AWB=%(awb)s") % {"id": eid or "?", "awb": tracking or "-"},
                "type": "success",
                "sticky": False,
            },
        }


class ShipBluBatchOpsWizard(models.TransientModel):
    _name = "shipblu.batch.ops.wizard"
    _description = "ShipBlu Batch Labels / Pickup"

    backend_id = fields.Many2one(
        "shipblu.backend",
        required=True,
        default=lambda self: self.env["shipblu.backend"].search(
            [("company_id", "=", self.env.company.id)], limit=1
        ),
    )
    shipment_ids = fields.Many2many(
        "shipblu.shipment",
        string="Shipments",
        domain="[('tracking_number', '!=', False)]",
    )
    one_per_page = fields.Boolean(string="One label per page")

    def action_download_labels(self):
        self.ensure_one()
        trackings = [s.tracking_number for s in self.shipment_ids if s.tracking_number]
        if not trackings:
            raise UserError(_("Select shipments with tracking numbers."))
        try:
            result = self.backend_id.get_client().get_orders_shipping_label(
                trackings, label_type="pdf", one_per_page=self.one_per_page
            )
        except ShipBluApiError as exc:
            raise UserError(str(exc)) from exc
        if not isinstance(result, (bytes, bytearray)):
            raise UserError(_("Batch label response was not a PDF."))
        att = self.env["ir.attachment"].create(
            {
                "name": f"ShipBlu-Labels-{fields.Datetime.now()}.pdf",
                "type": "binary",
                "datas": base64.b64encode(bytes(result)).decode(),
                "mimetype": "application/pdf",
                "res_model": "shipblu.backend",
                "res_id": self.backend_id.id,
            }
        )
        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/{att.id}?download=true",
            "target": "new",
        }

    def action_request_pickup(self):
        self.ensure_one()
        self.backend_id.assert_write_allowed("request pickup")
        trackings = [s.tracking_number for s in self.shipment_ids if s.tracking_number]
        if not trackings:
            raise UserError(_("Select shipments with tracking numbers."))
        try:
            self.backend_id.get_client().request_pickup(trackings)
        except ShipBluApiError as exc:
            raise UserError(str(exc)) from exc
        for s in self.shipment_ids:
            s._record_action("request_pickup_batch", "ok")
            s.message_post(body=_("Batch pickup requested for %s") % s.tracking_number)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("ShipBlu Pickup"),
                "message": _("Pickup requested for %s AWBs") % len(trackings),
                "type": "success",
                "sticky": False,
            },
        }
