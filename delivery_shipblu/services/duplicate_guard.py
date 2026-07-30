# -*- coding: utf-8 -*-
"""ShipBlu Duplicate AWB Guard — pre-create checks, reconcile, fail-closed."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field

from odoo import _
from odoo.exceptions import UserError

from odoo.addons.petspot_shipblu_base.services.redaction import redact_payload
from odoo.addons.petspot_shipblu_base.services.shipblu_client import ShipBluApiError

_logger = logging.getLogger(__name__)

DETECTION_SOURCES = (
    ("local_awb", "Local AWB / ShipBlu id on picking"),
    ("imported_delivery", "Imported ShipBlu delivery"),
    ("shopify_fulfillment", "Shopify fulfillment tracking"),
    ("remote_reference", "Remote merchant_order_reference"),
    ("remote_awb", "Remote tracking number"),
    ("verification_required", "Ambiguous prior create — verification required"),
)

_SHIPBLU_CARRIER_HINTS = re.compile(r"shipblu|ship.?blu", re.I)


@dataclass
class GuardHit:
    source: str
    tracking: str | None = None
    shipblu_order_id: str | None = None
    shipment_id: int | None = None
    remote_order: dict | None = None
    note: str = ""
    candidates: list = field(default_factory=list)


class DuplicateGuard:
    """Production-grade pre-create guard for ShipBlu outbound deliveries."""

    def __init__(self, env):
        self.env = env

    # ------------------------------------------------------------------
    # Canonical identity
    # ------------------------------------------------------------------
    def shopify_store_key(self, company):
        """Best-effort Shopify store identity (myshopify domain or company id)."""
        Store = self.env.get("shopify.store") or self.env.get("shopify.instance")
        if Store is not None:
            domain = [("company_id", "=", company.id)] if "company_id" in Store._fields else []
            store = Store.sudo().search(domain, limit=1)
            for attr in ("shopify_url", "shop_url", "myshopify_domain", "name"):
                if store and attr in store._fields and store[attr]:
                    raw = str(store[attr]).strip().lower()
                    raw = raw.replace("https://", "").replace("http://", "").rstrip("/")
                    if raw:
                        return raw.split("/")[0]
        return f"odoo-co-{company.id}"

    def canonical_shipment_key(self, picking):
        """Deterministic identity: shipblu:<store>:so:<shopify|odoo_so>:pick:<picking_id>."""
        picking.ensure_one()
        store = self.shopify_store_key(picking.company_id)
        order = picking.sale_id
        if order and "shopify_order_id" in order._fields and order.shopify_order_id:
            so_part = f"shopify-{order.shopify_order_id}"
        elif order:
            so_part = f"odoo-so-{order.id}"
        else:
            so_part = "no-so"
        return f"shipblu:{store}:so:{so_part}:pick:{picking.id}"

    def merchant_reference_candidates(self, picking, canonical_key=None):
        """All merchant_order_reference values that may identify this outbound."""
        picking.ensure_one()
        key = canonical_key or self.canonical_shipment_key(picking)
        refs = {key}
        # Legacy Odoo format (pre-guard)
        refs.add(f"ODOO-{picking.company_id.id}-{picking.id}-{picking.name}")
        order = picking.sale_id
        if order:
            for val in (
                order.name,
                order.client_order_ref,
                getattr(order, "shopify_order_id", None),
            ):
                if not val:
                    continue
                s = str(val).strip()
                refs.add(s)
                if s.startswith("#"):
                    refs.add(s.lstrip("#"))
                else:
                    refs.add(f"#{s}")
        return [r for r in refs if r]

    # ------------------------------------------------------------------
    # Locking
    # ------------------------------------------------------------------
    def advisory_lock(self, canonical_key):
        """Session-level PG advisory lock derived from canonical key (fail-closed)."""
        digest = hashlib.sha256(canonical_key.encode("utf-8")).digest()
        # two int32 keys
        k1 = int.from_bytes(digest[0:4], "big", signed=True)
        k2 = int.from_bytes(digest[4:8], "big", signed=True)
        self.env.cr.execute("SELECT pg_advisory_xact_lock(%s, %s)", (k1, k2))

    def lock_picking(self, picking):
        self.env.cr.execute(
            "SELECT id FROM stock_picking WHERE id = %s FOR UPDATE",
            (picking.id,),
        )

    # ------------------------------------------------------------------
    # Detection sequence
    # ------------------------------------------------------------------
    def check_local_picking(self, picking):
        if picking.shipblu_order_id:
            return GuardHit(
                source="local_awb",
                shipblu_order_id=str(picking.shipblu_order_id),
                tracking=(picking.carrier_tracking_ref or None),
                note=_("Picking already linked to ShipBlu order %s") % picking.shipblu_order_id,
            )
        if picking.carrier_tracking_ref:
            # Only treat as ShipBlu conflict when owner is shipblu or tracking matches imported AWB
            owner = getattr(picking, "shipblu_shipment_owner", False)
            if owner in ("odoo_shipblu", "legacy_shopify", "imported"):
                return GuardHit(
                    source="local_awb",
                    tracking=picking.carrier_tracking_ref,
                    note=_("Picking already has ShipBlu tracking %s") % picking.carrier_tracking_ref,
                )
            # Unknown tracking — fail-closed for ShipBlu create
            return GuardHit(
                source="local_awb",
                tracking=picking.carrier_tracking_ref,
                note=_(
                    "Picking already has tracking %s — refusing ShipBlu create "
                    "(fail-closed). Clear tracking or link existing shipment first."
                )
                % picking.carrier_tracking_ref,
            )
        if getattr(picking, "bosta_delivery_id", False):
            return GuardHit(
                source="local_awb",
                note=_("Picking already has Bosta delivery %s") % picking.bosta_delivery_id,
            )
        return None

    def check_local_shipments(self, picking, canonical_key):
        Shipment = self.env["shipblu.shipment"].sudo()
        domain_base = [("company_id", "=", picking.company_id.id)]
        # By picking + remote id
        hit = Shipment.search(
            domain_base + [("picking_id", "=", picking.id), ("shipblu_order_id", "!=", False)],
            limit=1,
        )
        if hit:
            return GuardHit(
                source="imported_delivery",
                shipment_id=hit.id,
                shipblu_order_id=hit.shipblu_order_id,
                tracking=hit.tracking_number or None,
                note=_("Existing ShipBlu shipment %s on this picking") % hit.name,
            )
        # By canonical key / business_reference
        refs = self.merchant_reference_candidates(picking, canonical_key)
        hit = Shipment.search(
            domain_base
            + [
                "|",
                ("canonical_shipment_key", "=", canonical_key),
                ("business_reference", "in", refs),
            ],
            limit=1,
        )
        if hit and (hit.shipblu_order_id or hit.tracking_number or hit.state == "verification_required"):
            source = (
                "verification_required"
                if hit.state == "verification_required" and not hit.shipblu_order_id
                else "imported_delivery"
            )
            return GuardHit(
                source=source,
                shipment_id=hit.id,
                shipblu_order_id=hit.shipblu_order_id or None,
                tracking=hit.tracking_number or None,
                note=_("Matched local shipment %s by reference/key") % hit.name,
            )
        # Same picking draft/creating without remote id — reuse row, not a hit
        return None

    def check_shopify_fulfillment(self, picking):
        """Detect ShipBlu AWB already present via Shopify fulfillments / SO metadata."""
        order = picking.sale_id
        if not order:
            return None
        trackings = []
        # From other pickings on same SO that look like ShipBlu
        for p in order.picking_ids.filtered(lambda x: x.id != picking.id and x.carrier_tracking_ref):
            carrier_name = (p.carrier_id.name or "") if p.carrier_id else ""
            owner = getattr(p, "shipblu_shipment_owner", False)
            if owner in ("legacy_shopify", "odoo_shipblu", "imported") or _SHIPBLU_CARRIER_HINTS.search(
                carrier_name
            ):
                trackings.append(p.carrier_tracking_ref.strip())
        # Shopify connector may have left tracking on this picking already handled in check_local
        # Scan SO note / fulfillment ids is weak — prefer imported shipments by shopify_order_id
        Shipment = self.env["shipblu.shipment"].sudo()
        shopify_id = getattr(order, "shopify_order_id", None)
        if shopify_id:
            hit = Shipment.search(
                [
                    ("company_id", "=", picking.company_id.id),
                    ("shopify_order_id", "=", str(shopify_id)),
                    ("shipblu_order_id", "!=", False),
                    ("picking_id", "in", [False, picking.id]),
                ],
                limit=1,
            )
            if hit:
                return GuardHit(
                    source="shopify_fulfillment",
                    shipment_id=hit.id,
                    shipblu_order_id=hit.shipblu_order_id,
                    tracking=hit.tracking_number or None,
                    note=_("ShipBlu delivery linked to Shopify order %s") % shopify_id,
                )
        if trackings:
            hit = Shipment.search(
                [
                    ("company_id", "=", picking.company_id.id),
                    ("tracking_number", "in", trackings),
                    ("shipblu_order_id", "!=", False),
                ],
                limit=1,
            )
            if hit:
                return GuardHit(
                    source="shopify_fulfillment",
                    shipment_id=hit.id,
                    shipblu_order_id=hit.shipblu_order_id,
                    tracking=hit.tracking_number or None,
                    note=_("Shopify-side ShipBlu tracking %s") % hit.tracking_number,
                )
            # Tracking present on sibling picking but not imported — fail-closed
            return GuardHit(
                source="shopify_fulfillment",
                tracking=trackings[0],
                note=_(
                    "Sibling picking already has tracking %s (likely Shopify ShipBlu). "
                    "Import/sync before creating."
                )
                % trackings[0],
            )
        return None

    def remote_lookup(self, backend, picking, canonical_key):
        """Fresh ShipBlu API lookup by merchant_order_reference and candidate trackings."""
        client = backend.get_client()
        refs = self.merchant_reference_candidates(picking, canonical_key)
        hits = []
        try:
            for ref in refs:
                data = client.list_delivery_orders_filtered(
                    merchant_order_reference=ref, limit=10
                )
                results = data.get("results") if isinstance(data, dict) else (data or [])
                for row in results or []:
                    hits.append(("remote_reference", row, ref))
            # Also search by known local trackings on SO
            order = picking.sale_id
            trackings = set()
            if picking.carrier_tracking_ref:
                trackings.add(picking.carrier_tracking_ref.strip())
            if order:
                for p in order.picking_ids:
                    if p.carrier_tracking_ref:
                        trackings.add(p.carrier_tracking_ref.strip())
            for trk in trackings:
                data = client.list_delivery_orders_filtered(tracking_number=trk, limit=5)
                results = data.get("results") if isinstance(data, dict) else (data or [])
                for row in results or []:
                    hits.append(("remote_awb", row, trk))
        except ShipBluApiError as exc:
            raise UserError(
                _(
                    "ShipBlu remote pre-check failed — create blocked (fail-closed): %s"
                )
                % exc
            ) from exc

        if not hits:
            return None
        source, row, matched = hits[0]
        tracking = row.get("tracking_number") or row.get("tracking_no")
        packages = row.get("packages") or []
        if not tracking and packages and isinstance(packages[0], dict):
            tracking = packages[0].get("tracking_number")
        return GuardHit(
            source=source,
            shipblu_order_id=str(row.get("id") or "") or None,
            tracking=tracking or None,
            remote_order=row,
            note=_("Remote ShipBlu match via %s=%s") % (source, matched),
            candidates=[h[2] for h in hits],
        )

    def find_existing(self, picking, backend, canonical_key=None, do_remote=True):
        """Run full detection sequence. Raises UserError on remote failure (fail-closed)."""
        picking.ensure_one()
        key = canonical_key or self.canonical_shipment_key(picking)
        for checker in (
            lambda: self.check_local_picking(picking),
            lambda: self.check_local_shipments(picking, key),
            lambda: self.check_shopify_fulfillment(picking),
        ):
            hit = checker()
            if hit:
                return hit
        if do_remote:
            # Fresh import of recent pages then re-check local (cheap when empty)
            try:
                from odoo.addons.delivery_shipblu.services.import_service import ImportService

                ImportService(self.env).import_delivery_orders(backend, max_pages=3)
            except Exception as exc:  # noqa: BLE001 — fail-closed on sync failure
                raise UserError(
                    _("ShipBlu import before create failed — blocked (fail-closed): %s") % exc
                ) from exc
            hit = self.check_local_shipments(picking, key)
            if hit:
                return hit
            hit = self.check_shopify_fulfillment(picking)
            if hit:
                return hit
            hit = self.remote_lookup(backend, picking, key)
            if hit:
                return hit
            # Final local pass after remote
            hit = self.check_local_shipments(picking, key)
            if hit:
                return hit
        return None

    # ------------------------------------------------------------------
    # Reconcile
    # ------------------------------------------------------------------
    def reconcile(self, picking, backend, hit, canonical_key=None):
        """Link existing ShipBlu delivery to picking/SO; never create."""
        from odoo.addons.delivery_shipblu.services.status_mapping import (
            coerce_raw_status,
            normalize_shipblu_status,
        )
        from odoo import fields as odoo_fields

        picking.ensure_one()
        key = canonical_key or self.canonical_shipment_key(picking)
        Shipment = self.env["shipblu.shipment"].sudo()
        shipment = Shipment.browse(hit.shipment_id) if hit.shipment_id else Shipment.browse()
        if not shipment:
            domain = [("company_id", "=", picking.company_id.id)]
            if hit.shipblu_order_id:
                shipment = Shipment.search(domain + [("shipblu_order_id", "=", hit.shipblu_order_id)], limit=1)
            if not shipment and hit.tracking:
                shipment = Shipment.search(domain + [("tracking_number", "=", hit.tracking)], limit=1)
            if not shipment and picking.id:
                shipment = Shipment.search(domain + [("picking_id", "=", picking.id)], limit=1)
            if not shipment and key:
                shipment = Shipment.search(domain + [("canonical_shipment_key", "=", key)], limit=1)
        remote = hit.remote_order
        if not shipment and remote and remote.get("id"):
            existing = Shipment.search(
                [("shipblu_order_id", "=", str(remote["id"]))], limit=1
            )
            if existing:
                shipment = existing
            else:
                raw = remote.get("status")
                tracking = hit.tracking
                shipment = Shipment.create(
                    {
                        "backend_id": backend.id,
                        "company_id": picking.company_id.id,
                        "picking_id": picking.id,
                        "sale_order_id": picking.sale_id.id if picking.sale_id else False,
                        "business_reference": remote.get("merchant_order_reference") or key,
                        "canonical_shipment_key": key,
                        "shipblu_order_id": str(remote["id"]),
                        "tracking_number": tracking or False,
                        "tracking_url": backend.tracking_url_for(tracking) if tracking else False,
                        "raw_status": raw or False,
                        "shipblu_status": coerce_raw_status(raw) or False,
                        "normalized_status": normalize_shipblu_status(raw),
                        "shopify_order_ref": remote.get("merchant_order_reference") or False,
                        "shopify_order_id": (
                            str(picking.sale_id.shopify_order_id)
                            if picking.sale_id and getattr(picking.sale_id, "shopify_order_id", None)
                            else False
                        ),
                        "creation_source": (
                            "shopify"
                            if hit.source == "shopify_fulfillment"
                            else "odoo"
                            if str(remote.get("merchant_order_reference") or "").startswith(
                                "shipblu:"
                            )
                            or hit.source.startswith("remote")
                            else "unknown"
                        ),
                        "shipment_owner": (
                            "legacy_shopify"
                            if hit.source == "shopify_fulfillment"
                            else "odoo_shipblu"
                            if str(remote.get("merchant_order_reference") or "").startswith(
                                "shipblu:"
                            )
                            else "imported"
                        ),
                        "state": "created",
                        "duplicate_guard_status": "reconciled",
                        "duplicate_detection_source": hit.source,
                        "payload_snapshot": json.dumps(
                            redact_payload(remote), ensure_ascii=False
                        )[:8000],
                        "reconciliation_notes": hit.note,
                    }
                )
        if not shipment and (hit.shipblu_order_id or hit.tracking):
            # Local AWB on picking without shipment row yet
            shipment = Shipment.create(
                {
                    "backend_id": backend.id,
                    "company_id": picking.company_id.id,
                    "picking_id": picking.id,
                    "sale_order_id": picking.sale_id.id if picking.sale_id else False,
                    "business_reference": key,
                    "canonical_shipment_key": key,
                    "shipblu_order_id": hit.shipblu_order_id or False,
                    "tracking_number": hit.tracking or False,
                    "tracking_url": backend.tracking_url_for(hit.tracking) if hit.tracking else False,
                    "creation_source": "shopify"
                    if hit.source == "shopify_fulfillment"
                    else "odoo",
                    "shipment_owner": "legacy_shopify"
                    if hit.source == "shopify_fulfillment"
                    else "odoo_shipblu",
                    "state": "created" if hit.shipblu_order_id else "draft",
                    "duplicate_guard_status": "reconciled",
                    "duplicate_detection_source": hit.source,
                    "reconciliation_notes": hit.note,
                    "shopify_order_id": (
                        str(picking.sale_id.shopify_order_id)
                        if picking.sale_id and getattr(picking.sale_id, "shopify_order_id", None)
                        else False
                    ),
                }
            )
        if shipment:
            vals = {
                "picking_id": picking.id or shipment.picking_id.id,
                "sale_order_id": (picking.sale_id.id if picking.sale_id else shipment.sale_order_id.id),
                "canonical_shipment_key": key,
                "duplicate_guard_status": "reconciled",
                "duplicate_detection_source": hit.source,
                "reconciliation_notes": (hit.note or "")[:2000],
                "last_remote_precheck_at": odoo_fields.Datetime.now(),
            }
            if hit.shipblu_order_id:
                vals["shipblu_order_id"] = hit.shipblu_order_id
            if hit.tracking:
                vals["tracking_number"] = hit.tracking
                vals["tracking_url"] = backend.tracking_url_for(hit.tracking)
            if hit.source == "shopify_fulfillment" and shipment.creation_source in (
                "unknown",
                "imported",
                False,
            ):
                vals["creation_source"] = "shopify"
                vals["shipment_owner"] = "legacy_shopify"
            if shipment.state == "verification_required" and hit.shipblu_order_id:
                vals["state"] = "created"
            shipment.write(vals)
            picking_vals = {
                "shipblu_order_id": shipment.shipblu_order_id or picking.shipblu_order_id,
                "shipblu_shipment_owner": shipment.shipment_owner or "imported",
                "shipblu_canonical_key": key,
                "shipblu_duplicate_guard_status": "reconciled",
                "shipblu_duplicate_detection_source": hit.source,
            }
            if shipment.tracking_number and not picking.carrier_tracking_ref:
                picking_vals["carrier_tracking_ref"] = shipment.tracking_number
            elif shipment.tracking_number:
                picking_vals["carrier_tracking_ref"] = shipment.tracking_number
            picking.write(picking_vals)
            shipment.message_post(
                body=_(
                    "Existing ShipBlu AWB found and linked; no new delivery was created. "
                    "Source: %(src)s. AWB: %(awb)s."
                )
                % {"src": hit.source, "awb": shipment.tracking_number or shipment.shipblu_order_id}
            )
        return shipment

    def assert_can_create_shipblu(self, picking, allow_manager_override=False):
        """Backward-compatible hard block used by legacy call sites."""
        picking.ensure_one()
        backend = self.env["shipblu.backend"]._get_for_company(picking.company_id)
        key = self.canonical_shipment_key(picking)
        hit = self.find_existing(picking, backend, key, do_remote=False)
        if not hit:
            # Cross-provider: Bosta on same picking
            if getattr(picking, "bosta_delivery_id", False):
                raise UserError(
                    _("Picking already has Bosta delivery %s") % picking.bosta_delivery_id
                )
            return True
        if allow_manager_override and self.env.context.get("shipblu_force_create"):
            if self.env.user.has_group("petspot_shipblu_base.group_shipblu_manager"):
                return True
        raise UserError(
            _("ShipBlu create blocked — %(note)s") % {"note": hit.note or hit.source}
        )
