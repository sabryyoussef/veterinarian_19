# -*- coding: utf-8 -*-
"""Normalized Vetution / marketplace supplier offers."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, datetime

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

UNKNOWN_EXPIRY_MARKERS = {None, "", "0000-00-00", "0001-01-01"}


class VetutionSupplierOffer(models.Model):
    _name = "vetution.supplier.offer"
    _description = "Vetution Supplier Offer"
    _order = "vetution_drug_id, vetution_size_id, offer_type, id"

    connection_id = fields.Many2one(
        "vetution.connection",
        required=True,
        ondelete="cascade",
        index=True,
    )
    product_id = fields.Many2one("product.product", index=True, ondelete="set null")
    product_tmpl_id = fields.Many2one(
        "product.template",
        related="product_id.product_tmpl_id",
        store=True,
        index=True,
    )
    offer_type = fields.Selection(
        [
            ("vetution", "Vetution Primary"),
            ("marketplace_vendor", "Marketplace Vendor"),
        ],
        required=True,
        index=True,
    )
    vetution_drug_id = fields.Integer(index=True)
    vetution_size_id = fields.Integer(index=True)
    vendor_drug_size_id = fields.Integer(index=True)
    external_vendor_id = fields.Integer()
    external_vendor_name = fields.Char()
    size_name = fields.Char()
    drug_slug = fields.Char(index=True)
    drug_name = fields.Char()

    # Price
    supplier_price = fields.Float()
    supplier_user_price = fields.Float()
    effective_cost = fields.Float()
    strike_price = fields.Float()
    is_promo = fields.Boolean()
    promo_discount_raw = fields.Char()
    is_express = fields.Boolean()
    show = fields.Boolean(default=True)
    show_price = fields.Boolean(default=True)

    # Availability
    supplier_qty_raw = fields.Char()
    supplier_qty = fields.Float()
    supplier_out_of_stock = fields.Boolean()
    availability_state = fields.Selection(
        [
            ("available", "Available"),
            ("limited", "Limited"),
            ("out_of_stock", "Out of Stock"),
            ("unknown", "Unknown"),
            ("price_hidden", "Price Hidden"),
            ("expired", "Expired"),
            ("expiry_blocked", "Expiry Blocked"),
            ("stale", "Stale"),
            ("authentication_error", "Authentication Error"),
        ],
        default="unknown",
        index=True,
    )

    # Expiry
    expiry_date = fields.Date()
    expiry_text = fields.Char()
    expiry_is_exact = fields.Boolean()
    expiry_source = fields.Selection(
        [
            ("vetution_offer", "Vetution Offer"),
            ("vendor_offer", "Vendor Offer"),
            ("manual", "Manual"),
        ],
        default="vetution_offer",
    )
    days_to_expiry = fields.Integer()
    is_expired = fields.Boolean()
    is_near_expiry = fields.Boolean()

    # Control / audit
    active_for_procurement = fields.Boolean(default=False, index=True)
    needs_review = fields.Boolean(default=False, index=True)
    review_reason = fields.Char()
    last_seen_at = fields.Datetime()
    last_commercial_sync_at = fields.Datetime()
    is_stale = fields.Boolean(default=False)
    raw_json = fields.Text()
    data_hash = fields.Char(index=True)
    active = fields.Boolean(default=True)
    preview_sale_price = fields.Float(
        help="Pricing-engine preview only. Never written to list_price in Phase 1.",
    )

    def init(self):
        """Partial unique indexes (Phase 0 evidence)."""
        cr = self.env.cr
        cr.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS vetution_offer_primary_uniq
            ON vetution_supplier_offer (connection_id, vetution_size_id)
            WHERE offer_type = 'vetution' AND vetution_size_id IS NOT NULL
            """
        )
        cr.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS vetution_offer_vendor_uniq
            ON vetution_supplier_offer (connection_id, vendor_drug_size_id)
            WHERE offer_type = 'marketplace_vendor' AND vendor_drug_size_id IS NOT NULL
            """
        )

    # ------------------------------------------------------------------ helpers
    @api.model
    def parse_qty(self, raw):
        """Return (qty_float_or_False, qty_raw_str, flags_list)."""
        flags = []
        if raw is None:
            return False, False, flags
        raw_str = str(raw).strip()
        try:
            qty = float(raw_str)
        except (TypeError, ValueError):
            flags.append("qty_unparseable")
            return False, raw_str, flags
        if qty < 0:
            flags.append("qty_negative")
        if abs(qty - int(qty)) > 1e-9 and qty > 0:
            flags.append("fractional_qty")
        return qty, raw_str, flags

    @api.model
    def parse_expiry(self, raw, today=None):
        """Return dict with expiry_date, expiry_text, expiry_is_exact, days, is_expired, is_near."""
        today = today or date.today()
        text = None if raw is None else str(raw).strip()
        result = {
            "expiry_date": False,
            "expiry_text": text or False,
            "expiry_is_exact": False,
            "days_to_expiry": False,
            "is_expired": False,
            "is_near_expiry": False,
            "flags": [],
        }
        if text in UNKNOWN_EXPIRY_MARKERS or text is False:
            result["flags"].append("expiry_unknown")
            result["expiry_text"] = text if text not in (None, False) else False
            return result
        try:
            y, m, d = [int(x) for x in text.split("-")]
            if y < 1900:
                result["flags"].append("expiry_unknown")
                return result
            dt = date(y, m, d)
        except (ValueError, TypeError, AttributeError):
            result["flags"].append("expiry_invalid")
            return result
        days = (dt - today).days
        result.update(
            {
                "expiry_date": dt,
                "expiry_is_exact": True,
                "days_to_expiry": days,
                "is_expired": days < 0,
            }
        )
        return result

    @api.model
    def compute_effective_cost(self, price, user_price, show, show_price):
        try:
            up = float(user_price or 0)
        except (TypeError, ValueError):
            up = 0.0
        try:
            p = float(price or 0)
        except (TypeError, ValueError):
            p = 0.0
        show_ok = bool(show) and bool(show_price)
        if up > 0 and show_ok:
            return up
        if p > 0 and show_ok:
            return p
        return 0.0

    @api.model
    def compute_strike_price(self, price, old_price_offer, offer_flag):
        try:
            p = float(price or 0)
            old = float(old_price_offer or 0)
        except (TypeError, ValueError):
            return 0.0
        if int(offer_flag or 0) == 1 and old > p > 0:
            return old
        return 0.0

    @api.model
    def normalize_availability(
        self,
        *,
        show,
        show_price,
        out_of_stock,
        qty,
        effective_cost,
        is_expired,
        expiry_is_exact,
        days_to_expiry,
        minimum_expiry_days,
        near_expiry_days,
        low_stock_threshold,
        is_stale=False,
    ):
        """Return (availability_state, is_near_expiry, flags, active_for_procurement_allowed)."""
        flags = []
        if is_stale:
            return "stale", False, flags, False

        show_b = bool(show)
        show_price_b = bool(show_price)
        if not show_b or not show_price_b:
            return "price_hidden", False, flags, False

        if expiry_is_exact and is_expired:
            return "expired", False, flags, False

        near = False
        if expiry_is_exact and days_to_expiry is not False and days_to_expiry is not None:
            if 0 <= days_to_expiry <= (near_expiry_days or 180):
                near = True
                flags.append("near_expiry")
            if days_to_expiry < (minimum_expiry_days or 90):
                # Blocked from procurement but may still show as available/limited/oos
                flags.append("expiry_below_minimum")

        oos = bool(out_of_stock)
        qty_val = qty if qty is not False and qty is not None else None

        if oos:
            if qty_val is not None and qty_val > 0:
                flags.append("conflict_qty_pos")
            if qty_val is not None and qty_val < 0:
                flags.append("qty_negative")
            return "out_of_stock", near, flags, False

        cost_ok = float(effective_cost or 0) > 0
        if not cost_ok:
            flags.append("no_cost")
            return "unknown", near, flags, False

        if qty_val is not None and qty_val > 0:
            threshold = low_stock_threshold if low_stock_threshold is not None else 3.0
            if qty_val <= threshold:
                return "limited", near, flags, True
            return "available", near, flags, True

        # oos false + qty 0 / missing
        if qty_val == 0:
            flags.append("qty_zero_not_oos")
        return "unknown", near, flags, False

    @api.model
    def hash_payload(self, payload):
        blob = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def action_set_needs_review(self, reason):
        for rec in self:
            reasons = [r for r in (rec.review_reason or "").split("|") if r]
            if reason and reason not in reasons:
                reasons.append(reason)
            rec.write(
                {
                    "needs_review": True,
                    "review_reason": "|".join(reasons) if reasons else reason,
                    "active_for_procurement": False,
                }
            )
