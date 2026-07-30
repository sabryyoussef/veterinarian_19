# -*- coding: utf-8 -*-
"""Import / match ShipBlu delivery orders into Odoo (read-only sync)."""

from __future__ import annotations

import json
import logging
import re

from odoo import _, fields
from odoo.exceptions import UserError

from odoo.addons.delivery_shipblu.services.status_mapping import (
    coerce_raw_status,
    normalize_shipblu_status,
)
from odoo.addons.petspot_shipblu_base.services.redaction import redact_payload
from odoo.addons.petspot_shipblu_base.services.shipblu_client import ShipBluApiError

_logger = logging.getLogger(__name__)


class ImportService:
    def __init__(self, env):
        self.env = env

    def _backend(self, company=None):
        return self.env["shipblu.backend"]._get_for_company(company or self.env.company)

    def import_delivery_orders(self, backend=None, max_pages=50):
        backend = backend or self._backend()
        client = backend.get_client()
        page_size = max(1, min(int(backend.import_page_size or 50), 100))
        offset = 0
        created = updated = matched = needs_matching = 0
        pages = 0
        while pages < max_pages:
            pages += 1
            try:
                payload = client.list_delivery_orders(limit=page_size, offset=offset)
            except ShipBluApiError as exc:
                backend.write(
                    {
                        "last_import_at": fields.Datetime.now(),
                        "last_import_result": f"error: {exc}"[:500],
                    }
                )
                raise UserError(str(exc)) from exc
            results = payload.get("results") if isinstance(payload, dict) else []
            results = results or []
            for order in results:
                stats = self.upsert_delivery_order(backend, order)
                created += stats["created"]
                updated += stats["updated"]
                matched += stats["matched"]
                needs_matching += stats["needs_matching"]
            if not results or not payload.get("next"):
                break
            offset += page_size
        msg = _(
            "Import OK — pages=%(p)s created=%(c)s updated=%(u)s matched=%(m)s needs_matching=%(n)s"
        ) % {
            "p": pages,
            "c": created,
            "u": updated,
            "m": matched,
            "n": needs_matching,
        }
        backend.write({"last_import_at": fields.Datetime.now(), "last_import_result": msg})
        return {
            "pages": pages,
            "created": created,
            "updated": updated,
            "matched": matched,
            "needs_matching": needs_matching,
            "message": msg,
        }

    def upsert_delivery_order(self, backend, order):
        Shipment = self.env["shipblu.shipment"].sudo()
        Event = self.env["shipblu.shipment.event"].sudo()
        oid = str(order.get("id") or "")
        if not oid:
            return {"created": 0, "updated": 0, "matched": 0, "needs_matching": 0}
        tracking = order.get("tracking_number") or False
        if not tracking:
            packages = order.get("packages") or []
            if packages and isinstance(packages[0], dict):
                tracking = packages[0].get("tracking_number") or False
        merchant_ref = order.get("merchant_order_reference") or False
        customer = order.get("customer") or {}
        address = (customer.get("address") or {}) if isinstance(customer, dict) else {}
        zone = address.get("zone")
        zone_id = zone.get("id") if isinstance(zone, dict) else zone
        zone_name = zone.get("name") if isinstance(zone, dict) else False
        packages = order.get("packages") or []
        package_summary = ", ".join(
            str(p.get("package_size") or p.get("id") or "?") for p in packages if isinstance(p, dict)
        ) or False
        raw_status = order.get("status") or False
        vals = {
            "backend_id": backend.id,
            "company_id": backend.company_id.id,
            "shipblu_order_id": oid,
            "tracking_number": tracking or False,
            "tracking_url": backend.tracking_url_for(tracking) if tracking else False,
            "business_reference": merchant_ref or f"SHIPBLU-{oid}",
            "shopify_order_ref": merchant_ref or False,
            "customer_name": customer.get("full_name") if isinstance(customer, dict) else False,
            "customer_phone": customer.get("phone") if isinstance(customer, dict) else False,
            "customer_email": customer.get("email") if isinstance(customer, dict) else False,
            "address_line_1": address.get("line_1") if isinstance(address, dict) else False,
            "address_line_2": address.get("line_2") if isinstance(address, dict) else False,
            "zone_id": int(zone_id) if zone_id else False,
            "zone_name": zone_name or False,
            "packages_json": json.dumps(redact_payload(packages), ensure_ascii=False)[:8000],
            "package_summary": package_summary,
            "cod_amount": float(order.get("cash_amount") or 0.0),
            "raw_status": raw_status or False,
            "shipblu_status": coerce_raw_status(raw_status),
            "normalized_status": normalize_shipblu_status(raw_status),
            "payload_snapshot": json.dumps(redact_payload(order), ensure_ascii=False)[:8000],
            "creation_source": self._infer_source(order, merchant_ref),
            "shipment_owner": "legacy_shopify"
            if self._infer_source(order, merchant_ref) == "shopify"
            else "imported",
            "last_sync_at": fields.Datetime.now(),
            "last_sync_result": "imported",
        }
        existing = Shipment.search([("shipblu_order_id", "=", oid)], limit=1)
        created = updated = 0
        if existing:
            # Prefer tracking unique collision check
            if tracking:
                clash = Shipment.search(
                    [("tracking_number", "=", tracking), ("id", "!=", existing.id)], limit=1
                )
                if clash:
                    existing.write(
                        {
                            "needs_matching": True,
                            "state": "needs_matching",
                            "last_error": _("AWB already linked to %s") % clash.name,
                        }
                    )
            # Never downgrade an Odoo-owned create to shopify/imported on re-import
            if existing.creation_source == "odoo" or existing.shipment_owner == "odoo_shipblu":
                vals.pop("creation_source", None)
                vals.pop("shipment_owner", None)
                if existing.canonical_shipment_key:
                    vals["business_reference"] = existing.canonical_shipment_key
                    vals["canonical_shipment_key"] = existing.canonical_shipment_key
            existing.write(vals)
            shipment = existing
            updated = 1
        else:
            if tracking:
                by_awb = Shipment.search([("tracking_number", "=", tracking)], limit=2)
                if len(by_awb) > 1:
                    vals.update({"needs_matching": True, "state": "needs_matching"})
                    shipment = Shipment.create(vals)
                    created = 1
                elif len(by_awb) == 1 and not by_awb.shipblu_order_id:
                    by_awb.write(vals)
                    shipment = by_awb
                    updated = 1
                elif len(by_awb) == 1 and by_awb.shipblu_order_id and by_awb.shipblu_order_id != oid:
                    # Same AWB, different remote id — never guess
                    vals.update(
                        {
                            "needs_matching": True,
                            "state": "needs_matching",
                            "last_error": _("AWB already linked to %s") % by_awb.name,
                        }
                    )
                    shipment = Shipment.create(vals)
                    created = 1
                    by_awb.write({"needs_matching": True, "state": "needs_matching"})
                else:
                    shipment = Shipment.create(vals)
                    created = 1
            else:
                shipment = Shipment.create(vals)
                created = 1

        # timeline: append only when status code changes
        if raw_status:
            last = Event.search([("shipment_id", "=", shipment.id)], limit=1, order="event_at desc, id desc")
            code = str(raw_status)[:64]
            if not last or last.event_code != code:
                Event.create(
                    {
                        "shipment_id": shipment.id,
                        "event_code": code,
                        "event_label": str(raw_status),
                        "event_at": fields.Datetime.now(),
                        "payload_json": json.dumps(
                            redact_payload({"status": raw_status}), ensure_ascii=False
                        )[:4000],
                    }
                )

        match_stats = self.match_shipment(shipment)
        return {
            "created": created,
            "updated": updated,
            "matched": match_stats["matched"],
            "needs_matching": match_stats["needs_matching"],
        }

    def _infer_source(self, order, merchant_ref):
        # Heuristic: Shopify apps often put #1004; Odoo uses ODOO- or shipblu: canonical keys.
        # Do not treat "shopify-<id>" inside shipblu:… keys as Shopify-created.
        merchant_ref = (merchant_ref or "").strip()
        if merchant_ref.startswith("shipblu:") or re.search(r"ODOO-\d+-", merchant_ref):
            return "odoo"
        ref = merchant_ref + " " + str(order.get("order_notes") or "")
        if re.search(r"ODOO-\d+-", ref) or "shipblu:" in ref:
            return "odoo"
        if re.search(r"#\d+", merchant_ref) or (
            "shopify" in ref.lower() and not merchant_ref.startswith("shipblu:")
        ):
            return "shopify"
        return "unknown"

    def match_shipment(self, shipment):
        shipment.ensure_one()
        Sale = self.env["sale.order"].sudo()
        Picking = self.env["stock.picking"].sudo()
        candidates = []

        # 1 already linked
        if shipment.sale_order_id and shipment.picking_id and not shipment.needs_matching:
            return {"matched": 1, "needs_matching": 0}

        # 2 by shipblu remote already done via upsert
        # 3 by AWB on picking
        if shipment.tracking_number:
            picks = Picking.search(
                [
                    ("carrier_tracking_ref", "=", shipment.tracking_number),
                    ("company_id", "=", shipment.company_id.id),
                ],
                limit=5,
            )
            for p in picks:
                candidates.append(("awb_picking", p.sale_id.id if p.sale_id else False, p.id))

        # 4 shopify order id / reference
        ref = (shipment.shopify_order_ref or shipment.business_reference or "").strip()
        if ref:
            domain = [
                ("company_id", "=", shipment.company_id.id),
                "|",
                "|",
                ("client_order_ref", "=", ref),
                ("client_order_ref", "=", ref.lstrip("#")),
                ("name", "=", ref.lstrip("#")),
            ]
            if "shopify_order_id" in Sale._fields and ref.isdigit():
                domain = ["|", ("shopify_order_id", "=", ref)] + domain
            orders = Sale.search(domain, limit=5)
            for o in orders:
                pick = o.picking_ids.filtered(lambda p: p.picking_type_code == "outgoing")[:1]
                candidates.append(("sale_ref", o.id, pick.id if pick else False))

        # Deduplicate candidate sale ids
        sale_ids = {c[1] for c in candidates if c[1]}
        pick_ids = {c[2] for c in candidates if c[2]}
        if len(sale_ids) > 1 or len(pick_ids) > 1:
            shipment.write(
                {
                    "needs_matching": True,
                    "state": "needs_matching",
                    "match_candidates": json.dumps(candidates)[:4000],
                    "last_sync_result": "needs_matching",
                }
            )
            return {"matched": 0, "needs_matching": 1}
        if len(sale_ids) == 1 or len(pick_ids) == 1:
            sale_id = next(iter(sale_ids)) if sale_ids else False
            pick_id = next(iter(pick_ids)) if pick_ids else False
            if sale_id and not pick_id:
                order = Sale.browse(sale_id)
                pick = order.picking_ids.filtered(lambda p: p.picking_type_code == "outgoing")[:1]
                pick_id = pick.id if pick else False
            vals = {
                "sale_order_id": sale_id or False,
                "picking_id": pick_id or False,
                "needs_matching": False,
                "match_candidates": False,
                "last_sync_result": "matched",
            }
            if shipment.state == "needs_matching":
                vals["state"] = "tracking" if shipment.shipblu_order_id else "created"
            shipment.write(vals)
            if pick_id and shipment.tracking_number:
                pick = Picking.browse(pick_id)
                # only set tracking when unambiguous
                if not pick.carrier_tracking_ref or pick.carrier_tracking_ref == shipment.tracking_number:
                    pick.write(
                        {
                            "carrier_tracking_ref": shipment.tracking_number,
                            "shipblu_order_id": shipment.shipblu_order_id,
                            "shipblu_shipment_owner": shipment.shipment_owner,
                        }
                    )
            if sale_id and "shopify_order_id" in Sale._fields:
                order = Sale.browse(sale_id)
                if order.shopify_order_id:
                    shipment.shopify_order_id = order.shopify_order_id
            return {"matched": 1, "needs_matching": 0}

        # no match
        if not shipment.sale_order_id:
            shipment.write(
                {
                    "needs_matching": True,
                    "state": "needs_matching",
                    "last_sync_result": "unmatched",
                }
            )
            return {"matched": 0, "needs_matching": 1}
        return {"matched": 0, "needs_matching": 0}

    def rematch_shipment(self, shipment):
        return self.match_shipment(shipment)

    def sync_tracking_batch(self, backend=None, limit=100):
        backend = backend or self._backend()
        Shipment = self.env["shipblu.shipment"].sudo()
        domain = [
            ("backend_id", "=", backend.id),
            ("shipblu_order_id", "!=", False),
            ("normalized_status", "not in", ("delivered", "cancelled", "returned")),
        ]
        shipments = Shipment.search(domain, limit=limit, order="last_sync_at asc, id asc")
        ok = err = 0
        service = self.env["shipblu.shipment"]  # noqa — use ShipmentService
        from odoo.addons.delivery_shipblu.services.shipment_service import ShipmentService

        svc = ShipmentService(self.env)
        for shipment in shipments:
            try:
                svc.refresh_shipment(shipment)
                ok += 1
            except Exception as exc:
                _logger.warning("ShipBlu tracking sync failed for %s: %s", shipment.id, exc)
                shipment.write({"last_error": str(exc)[:2000], "last_sync_result": "error"})
                err += 1
        msg = _("Tracking sync OK=%(ok)s ERR=%(err)s") % {"ok": ok, "err": err}
        backend.write({"last_tracking_sync_at": fields.Datetime.now(), "last_tracking_sync_result": msg})
        return {"ok": ok, "err": err, "message": msg}

    def sync_coverage(self, backend=None):
        backend = backend or self._backend()
        client = backend.get_client()
        Gov = self.env["shipblu.governorate"].sudo()
        City = self.env["shipblu.city"].sudo()
        Zone = self.env["shipblu.zone"].sudo()
        govs = client.get_governorates()
        if isinstance(govs, dict):
            govs = govs.get("results") or govs.get("Value") or []
        g_count = c_count = z_count = 0
        for g in govs or []:
            gid = g.get("id")
            if not gid:
                continue
            rec = Gov.search([("shipblu_id", "=", gid), ("company_id", "=", backend.company_id.id)], limit=1)
            vals = {
                "shipblu_id": gid,
                "name": g.get("name") or str(gid),
                "code": g.get("code") or False,
                "company_id": backend.company_id.id,
                "backend_id": backend.id,
            }
            if rec:
                rec.write(vals)
            else:
                Gov.create(vals)
            g_count += 1
            cities = client.get_cities(gid)
            if isinstance(cities, dict):
                cities = cities.get("results") or []
            for c in cities or []:
                cid = c.get("id")
                if not cid:
                    continue
                crec = City.search(
                    [("shipblu_id", "=", cid), ("company_id", "=", backend.company_id.id)], limit=1
                )
                cvals = {
                    "shipblu_id": cid,
                    "name": c.get("name") or str(cid),
                    "governorate_shipblu_id": gid,
                    "company_id": backend.company_id.id,
                    "backend_id": backend.id,
                }
                if crec:
                    crec.write(cvals)
                else:
                    City.create(cvals)
                c_count += 1
                zones = client.get_zones(cid)
                if isinstance(zones, dict):
                    zones = zones.get("results") or []
                for z in zones or []:
                    zid = z.get("id")
                    if not zid:
                        continue
                    zrec = Zone.search(
                        [("shipblu_id", "=", zid), ("company_id", "=", backend.company_id.id)], limit=1
                    )
                    zvals = {
                        "shipblu_id": zid,
                        "name": z.get("name") or str(zid),
                        "city_shipblu_id": cid,
                        "company_id": backend.company_id.id,
                        "backend_id": backend.id,
                    }
                    if zrec:
                        zrec.write(zvals)
                    else:
                        Zone.create(zvals)
                    z_count += 1
        return {"governorates": g_count, "cities": c_count, "zones": z_count}

    def sync_merchant_profile(self, backend=None):
        """Pull merchant wallet / pickup flags from GET /v1/merchants/."""
        backend = backend or self._backend()
        client = backend.get_client()
        data = client.get_merchants()
        results = data.get("results") if isinstance(data, dict) else data
        merchant = (results or [None])[0] if isinstance(results, list) else None
        if not isinstance(merchant, dict):
            raise UserError(_("No merchant returned from ShipBlu."))
        address = merchant.get("address") or {}
        zone = address.get("zone") if isinstance(address, dict) else {}
        zone_id = zone.get("id") if isinstance(zone, dict) else address.get("zone")
        vals = {
            "merchant_id": merchant.get("id") or 0,
            "merchant_name": merchant.get("name") or False,
            "merchant_status": merchant.get("status") or False,
            "merchant_van_or_bike": merchant.get("van_or_bike") or False,
            "merchant_is_self_signup": bool(merchant.get("is_self_signup")),
            "merchant_store_phone": merchant.get("store_phone") or False,
            "merchant_store_email": merchant.get("store_email") or False,
            "merchant_pickup_fees": float(merchant.get("pickup_fees") or 0.0),
            "merchant_pickup_time": int(merchant.get("pickup_time") or 0),
            "merchant_wallet_balance": float(merchant.get("quickbooks_wallet_balance") or 0.0),
            "merchant_cod_balance": float(merchant.get("quickbooks_cod_balance") or 0.0),
            "merchant_refunds_balance": float(merchant.get("quickbooks_refunds_balance") or 0.0),
            "merchant_customer_balance": float(merchant.get("quickbooks_customer_balance") or 0.0),
            "merchant_transfer_days": merchant.get("transfer_days") or False,
            "merchant_store_line_1": (address.get("line_1") if isinstance(address, dict) else False) or False,
            "merchant_store_line_2": (address.get("line_2") if isinstance(address, dict) else False) or False,
            "merchant_store_zone_id": int(zone_id or 0) or False,
            "last_merchant_sync_at": fields.Datetime.now(),
        }
        if not backend.default_package_size:
            vals["default_package_size"] = 1
        backend.write(vals)
        return vals

    def sync_portal_locations(self, backend=None):
        """Sync pickup points, return points, and ShipBlu hubs (drop-off warehouses)."""
        backend = backend or self._backend()
        client = backend.get_client()
        company = backend.company_id.id
        Pickup = self.env["shipblu.pickup.point"].sudo()
        ReturnPt = self.env["shipblu.return.point"].sudo()
        Wh = self.env["shipblu.warehouse"].sudo()

        pickups = client.get_pickup_points(limit=100)
        pickup_rows = pickups.get("results") if isinstance(pickups, dict) else (pickups or [])
        p_count = 0
        for row in pickup_rows or []:
            sid = row.get("id")
            if not sid:
                continue
            addr = row.get("address") or {}
            zone = addr.get("zone")
            zone_id = zone.get("id") if isinstance(zone, dict) else zone
            name = addr.get("nickname") or addr.get("line_1") or f"Pickup {sid}"
            vals = {
                "name": name,
                "backend_id": backend.id,
                "company_id": company,
                "shipblu_id": int(sid),
                "is_default": bool(row.get("is_default")),
                "nickname": addr.get("nickname") or False,
                "line_1": addr.get("line_1") or False,
                "line_2": addr.get("line_2") or False,
                "zone_id": int(zone_id or 0) or False,
                "zone_name": zone.get("name") if isinstance(zone, dict) else False,
                "what3words": addr.get("what3words") or False,
                "payload_json": json.dumps(redact_payload(row), ensure_ascii=False)[:8000],
            }
            existing = Pickup.search([("backend_id", "=", backend.id), ("shipblu_id", "=", int(sid))], limit=1)
            if existing:
                existing.write(vals)
            else:
                Pickup.create(vals)
            p_count += 1

        returns = client.get_return_points(limit=100)
        return_rows = returns.get("results") if isinstance(returns, dict) else (returns or [])
        r_count = 0
        for row in return_rows or []:
            sid = row.get("id")
            if not sid:
                continue
            addr = row.get("address") or {}
            zone = addr.get("zone")
            zone_id = zone.get("id") if isinstance(zone, dict) else zone
            name = addr.get("nickname") or addr.get("line_1") or f"Return {sid}"
            vals = {
                "name": name,
                "backend_id": backend.id,
                "company_id": company,
                "shipblu_id": int(sid),
                "is_default": bool(row.get("is_default")),
                "nickname": addr.get("nickname") or False,
                "line_1": addr.get("line_1") or False,
                "line_2": addr.get("line_2") or False,
                "zone_id": int(zone_id or 0) or False,
                "payload_json": json.dumps(redact_payload(row), ensure_ascii=False)[:8000],
            }
            existing = ReturnPt.search([("backend_id", "=", backend.id), ("shipblu_id", "=", int(sid))], limit=1)
            if existing:
                existing.write(vals)
            else:
                ReturnPt.create(vals)
            r_count += 1

        warehouses = client.get_warehouses(limit=200)
        wh_rows = warehouses.get("results") if isinstance(warehouses, dict) else (warehouses or [])
        w_count = 0
        for row in wh_rows or []:
            sid = row.get("id")
            if not sid:
                continue
            vals = {
                "name": row.get("name") or f"Hub {sid}",
                "backend_id": backend.id,
                "company_id": company,
                "shipblu_id": int(sid),
                "code": row.get("code") or False,
                "address": row.get("address") or False,
                "latitude": float(row.get("latitude") or 0.0),
                "longitude": float(row.get("longitude") or 0.0),
                "is_virtual": bool(row.get("is_virtual")),
                "payload_json": json.dumps(redact_payload(row), ensure_ascii=False)[:8000],
            }
            existing = Wh.search([("backend_id", "=", backend.id), ("shipblu_id", "=", int(sid))], limit=1)
            if existing:
                existing.write(vals)
            else:
                Wh.create(vals)
            w_count += 1

        return {"pickups": p_count, "return_points": r_count, "warehouses": w_count}

    def import_aux_orders(self, backend=None):
        """Import returns / exchanges / cash collections (read-only mirrors)."""
        backend = backend or self._backend()
        client = backend.get_client()
        stats = {}
        for kind, list_fn, model_name, id_field in [
            ("returns", client.list_returns, "shipblu.return.order", "shipblu_return_id"),
            ("exchanges", client.list_exchanges, "shipblu.exchange.order", "shipblu_exchange_id"),
            (
                "cash_collections",
                client.list_cash_collections,
                "shipblu.cash.collection",
                "shipblu_cc_id",
            ),
        ]:
            Model = self.env[model_name].sudo()
            created = updated = 0
            offset = 0
            while True:
                data = list_fn(limit=50, offset=offset)
                results = data.get("results") if isinstance(data, dict) else (data or [])
                results = results or []
                for row in results:
                    rid = str(row.get("id") or "")
                    if not rid:
                        continue
                    existing = Model.search([(id_field, "=", rid)], limit=1)
                    vals = {
                        "backend_id": backend.id,
                        "company_id": backend.company_id.id,
                        id_field: rid,
                        "name": row.get("tracking_number") or rid,
                        "tracking_number": row.get("tracking_number") or False,
                        "raw_status": row.get("status") or False,
                        "payload_json": json.dumps(redact_payload(row), ensure_ascii=False)[:8000],
                    }
                    if existing:
                        existing.write(vals)
                        updated += 1
                    else:
                        Model.create(vals)
                        created += 1
                if not results or not (isinstance(data, dict) and data.get("next")):
                    break
                offset += 50
            stats[kind] = {"created": created, "updated": updated}
        return stats
