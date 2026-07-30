# -*- coding: utf-8 -*-
"""Immutable sanitized Vetution commercial snapshot for shadow assessments."""

from __future__ import annotations

import hashlib
import json

from odoo import api, fields, models

AVAIL_MAP = {
    "available": "confirmed_available",
    "limited": "limited_stock",
    "out_of_stock": "out_of_stock",
    "unknown": "unknown",
    "price_hidden": "unknown",
    "expired": "out_of_stock",
    "expiry_blocked": "unknown",
    "stale": "stale",
    "authentication_error": "sync_failed",
}

SNAPSHOT_SCHEMA_VERSION = "15A.1"


class PetspotVetutionSupplierSnapshot(models.Model):
    _name = "petspot.vetution.supplier.snapshot"
    _description = "Vetution Supplier Snapshot (immutable)"
    _order = "id desc"

    name = fields.Char(required=True, default="Snapshot")
    assessment_id = fields.Many2one(
        "petspot.vetution.shadow.assessment", ondelete="cascade", index=True
    )
    inquiry_id = fields.Many2one(
        "petspot.availability.inquiry", ondelete="cascade", index=True
    )
    connection_id = fields.Many2one("vetution.connection", ondelete="set null")
    offer_id = fields.Many2one("vetution.supplier.offer", ondelete="set null", index=True)

    vetution_drug_id = fields.Integer(index=True)
    vetution_size_id = fields.Integer(index=True)
    drug_slug = fields.Char()
    size_name = fields.Char()
    supplier_sku = fields.Char(help="Prefer size id as vendor code; barcode if known.")
    barcode = fields.Char()

    purchase_price = fields.Float(help="PetSpot commercial purchase / effective_cost")
    public_list_price = fields.Float(help="Supplier public/list (strike or list) if known")
    offer_show = fields.Boolean()
    offer_show_price = fields.Boolean()
    offer_expiry_date = fields.Date()
    offer_is_expired = fields.Boolean()

    availability_raw = fields.Char()
    availability_normalized = fields.Selection(
        [
            ("confirmed_available", "Confirmed available"),
            ("limited_stock", "Limited stock"),
            ("out_of_stock", "Out of stock"),
            ("unknown", "Unknown"),
            ("stale", "Stale"),
            ("sync_failed", "Sync failed"),
        ],
        required=True,
        default="unknown",
        index=True,
    )
    supplier_qty = fields.Float()
    source_sync_at = fields.Datetime(help="Offer last commercial sync / last_seen")
    assessed_at = fields.Datetime(required=True, default=fields.Datetime.now)
    payload_hash = fields.Char(index=True, required=True)
    schema_version = fields.Char(default=SNAPSHOT_SCHEMA_VERSION, required=True)
    resolution_confidence = fields.Selection(
        [
            ("exact", "Exact"),
            ("configured", "Configured mapping"),
            ("barcode", "Barcode / vendor code"),
            ("ambiguous", "Ambiguous"),
            ("missing", "Missing"),
        ],
        default="missing",
    )
    sanitized_summary = fields.Text(
        help="Sanitized field summary — never store JWT/cookies/full raw payloads.",
    )
    is_immutable = fields.Boolean(default=True)

    def write(self, vals):
        # Allow only linkage updates after create; commercial fields stay fixed.
        allowed = {"assessment_id", "inquiry_id", "name"}
        if self.filtered("is_immutable") and set(vals) - allowed:
            # Soft: strip protected keys
            vals = {k: v for k, v in vals.items() if k in allowed}
            if not vals:
                return True
        return super().write(vals)

    @api.model
    def build_from_offer(self, offer, *, resolution_confidence, inquiry=None, assessed_at=None):
        offer.ensure_one()
        assessed_at = assessed_at or fields.Datetime.now()
        raw_state = offer.availability_state or "unknown"
        if offer.is_stale:
            raw_state = "stale"
        normalized = AVAIL_MAP.get(raw_state, "unknown")
        purchase = float(offer.effective_cost or 0.0)
        public = float(offer.strike_price or offer.supplier_price or 0.0)
        source_sync = offer.last_commercial_sync_at or offer.last_seen_at
        summary = {
            "vetution_drug_id": offer.vetution_drug_id or False,
            "vetution_size_id": offer.vetution_size_id or False,
            "drug_slug": offer.drug_slug or False,
            "size_name": offer.size_name or False,
            "purchase_price": purchase,
            "public_list_price": public,
            "availability_raw": raw_state,
            "availability_normalized": normalized,
            "supplier_qty": offer.supplier_qty if offer.supplier_qty is not False else None,
            "offer_show": bool(offer.show),
            "offer_show_price": bool(offer.show_price),
            "expiry": str(offer.expiry_date or ""),
            "source_sync_at": fields.Datetime.to_string(source_sync) if source_sync else False,
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
        }
        payload_hash = hashlib.sha256(
            json.dumps(summary, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        barcode = False
        if offer.product_id and offer.product_id.barcode:
            barcode = offer.product_id.barcode
        return {
            "name": f"SNAP/{offer.vetution_size_id or offer.id}/{payload_hash[:8]}",
            "inquiry_id": inquiry.id if inquiry else False,
            "connection_id": offer.connection_id.id,
            "offer_id": offer.id,
            "vetution_drug_id": offer.vetution_drug_id or False,
            "vetution_size_id": offer.vetution_size_id or False,
            "drug_slug": offer.drug_slug or False,
            "size_name": offer.size_name or False,
            "supplier_sku": str(offer.vetution_size_id or "") or False,
            "barcode": barcode,
            "purchase_price": purchase,
            "public_list_price": public,
            "offer_show": bool(offer.show),
            "offer_show_price": bool(offer.show_price),
            "offer_expiry_date": offer.expiry_date or False,
            "offer_is_expired": bool(offer.is_expired),
            "availability_raw": raw_state,
            "availability_normalized": normalized,
            "supplier_qty": offer.supplier_qty if offer.supplier_qty is not False else 0.0,
            "source_sync_at": source_sync or False,
            "assessed_at": assessed_at,
            "payload_hash": payload_hash,
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "resolution_confidence": resolution_confidence,
            "sanitized_summary": json.dumps(summary, sort_keys=True, default=str),
            "is_immutable": True,
        }
