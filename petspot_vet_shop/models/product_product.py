# -*- coding: utf-8 -*-
"""Variant commercial website state — separate from structural active/inactive."""

from odoo import api, fields, models

PLACEHOLDER_MAX = 1.01

# States that allow Add to Cart when price is activated.
SELLABLE_AVAIL = frozenset({"available", "limited"})

# Human labels for shop display (never expose internal codes alone).
AVAIL_LABELS = {
    "available": "Available",
    "limited": "Limited availability",
    "out_of_stock": "Out of stock",
    "unknown": "Available on request",
    "price_hidden": "Contact us",
    "expired": "Unavailable",
    "expiry_blocked": "Unavailable",
    "stale": "Availability being updated",
    "authentication_error": "Availability being updated",
}


class ProductProduct(models.Model):
    _inherit = "product.product"

    petspot_shop_sellable = fields.Boolean(
        string="Shop Sellable",
        compute="_compute_petspot_shop_state",
        store=True,
        index=True,
        help="True when this variant may be added to cart on the PetSpot shop.",
    )
    petspot_shop_block_reason = fields.Char(
        string="Shop Block Reason",
        compute="_compute_petspot_shop_state",
        store=True,
        help="Commercial reason the variant is blocked on the website (empty if sellable).",
    )
    petspot_shop_availability = fields.Selection(
        selection=[
            ("available", "Available"),
            ("limited", "Limited"),
            ("out_of_stock", "Out of Stock"),
            ("unknown", "Unknown"),
            ("price_hidden", "Price Hidden"),
            ("expired", "Expired"),
            ("expiry_blocked", "Expiry Blocked"),
            ("stale", "Stale"),
            ("authentication_error", "Auth Error"),
            ("not_vetution", "Not Vetution"),
            ("no_offer", "No Offer"),
            ("placeholder", "Placeholder Price"),
            ("not_activated", "Price Not Activated"),
            ("structurally_inactive", "Structurally Inactive"),
        ],
        compute="_compute_petspot_shop_state",
        store=True,
        index=True,
    )
    petspot_shop_notify_allowed = fields.Boolean(
        compute="_compute_petspot_shop_state", store=True,
    )
    petspot_shop_request_allowed = fields.Boolean(
        compute="_compute_petspot_shop_state", store=True,
    )
    petspot_shop_pricing_ready = fields.Boolean(
        compute="_compute_petspot_shop_state", store=True,
    )
    petspot_shop_display_price = fields.Float(
        compute="_compute_petspot_shop_state", store=True,
        digits="Product Price",
        help="Public selling price for shop display; 0 when not ready (never expose placeholder).",
    )

    def _petspot_primary_offer(self):
        self.ensure_one()
        return self.env["vetution.supplier.offer"].search(
            [
                ("product_id", "=", self.id),
                ("offer_type", "=", "vetution"),
                ("active", "=", True),
            ],
            limit=1,
            order="id",
        )

    @api.depends(
        "active",
        "list_price",
        "lst_price",
        "vetution_size_id",
        "vetution_variant_price_activated",
        "vetution_variant_blocked_by_pricing",
        "product_tmpl_id.vetution_id",
        "product_tmpl_id.list_price",
        "product_tmpl_id.vetution_price_activated",
        "product_tmpl_id.is_published",
        "product_template_attribute_value_ids.price_extra",
    )
    def _compute_petspot_shop_state(self):
        Offer = self.env["vetution.supplier.offer"]
        offers = Offer.search([
            ("product_id", "in", self.ids),
            ("offer_type", "=", "vetution"),
            ("active", "=", True),
        ])
        offer_by_product = {}
        for o in offers:
            offer_by_product.setdefault(o.product_id.id, o)
        for product in self:
            product._petspot_apply_shop_state(offer_by_product.get(product.id))

    def _petspot_evaluate_shop_state(self, offer=None):
        """Pure evaluation of commercial shop state (does not write fields)."""
        self.ensure_one()
        result = {
            "sellable": False,
            "block_reason": False,
            "availability": "not_vetution",
            "notify_allowed": False,
            "request_allowed": False,
            "pricing_ready": False,
            "display_price": 0.0,
        }
        tmpl = self.product_tmpl_id
        if not tmpl.vetution_id:
            if self.active and tmpl.is_published and self.lst_price > PLACEHOLDER_MAX:
                result.update(
                    sellable=True, pricing_ready=True,
                    display_price=self.lst_price, availability="available",
                )
            elif self.active and tmpl.is_published:
                result.update(availability="placeholder", block_reason="placeholder_price")
            else:
                result.update(availability="structurally_inactive", block_reason="inactive")
            return result

        if not self.active:
            result.update(availability="structurally_inactive", block_reason="structurally_inactive")
            return result

        offer = offer if offer is not None else self._petspot_primary_offer()
        if not offer:
            result.update(availability="no_offer", block_reason="no_offer", request_allowed=True)
            return result

        avail = offer.availability_state or "unknown"
        result["availability"] = avail
        price = float(self.lst_price or 0.0)
        single = len(tmpl.with_context(active_test=False).product_variant_ids) <= 1
        price_activated = bool(
            tmpl.vetution_price_activated
            and (single or self.vetution_variant_price_activated or price > PLACEHOLDER_MAX)
        )
        if price <= PLACEHOLDER_MAX or not price_activated:
            result.update(
                availability="placeholder" if price <= PLACEHOLDER_MAX else "not_activated",
                block_reason="placeholder_price" if price <= PLACEHOLDER_MAX else "price_not_activated",
                request_allowed=True,
            )
            return result

        result["pricing_ready"] = True
        result["display_price"] = price

        if avail in ("expired", "expiry_blocked", "stale", "authentication_error"):
            result["block_reason"] = avail
            return result
        if avail == "price_hidden" or not offer.show_price:
            result.update(
                availability="price_hidden", block_reason="price_hidden",
                pricing_ready=False, display_price=0.0, request_allowed=True,
            )
            return result
        if not offer.show:
            result.update(block_reason="not_shown", request_allowed=True)
            return result
        if avail == "out_of_stock":
            result.update(block_reason="out_of_stock", notify_allowed=True)
            return result
        if avail == "unknown":
            result.update(block_reason="unknown", request_allowed=True)
            return result
        if avail not in SELLABLE_AVAIL:
            result["block_reason"] = avail
            return result
        result["sellable"] = True
        result["block_reason"] = False
        return result

    def _petspot_apply_shop_state(self, offer):
        """Write computed shop-state fields from a pure evaluation."""
        self.ensure_one()
        state = self._petspot_evaluate_shop_state(offer)
        self.petspot_shop_sellable = state["sellable"]
        self.petspot_shop_block_reason = state["block_reason"]
        self.petspot_shop_notify_allowed = state["notify_allowed"]
        self.petspot_shop_request_allowed = state["request_allowed"]
        self.petspot_shop_pricing_ready = state["pricing_ready"]
        self.petspot_shop_display_price = state["display_price"]
        self.petspot_shop_availability = state["availability"]

    def _petspot_cart_eligibility(self):
        """Return (ok: bool, message: str) for server-side cart guard."""
        self.ensure_one()
        if not self.product_tmpl_id.vetution_id:
            return True, ""
        state = self._petspot_evaluate_shop_state()
        if state["sellable"]:
            return True, ""
        reason = state["block_reason"] or state["availability"] or "blocked"
        messages = {
            "out_of_stock": "This pack size is currently out of stock.",
            "unknown": "This pack size is available on request — please contact us.",
            "price_hidden": "Please contact us for pricing on this product.",
            "expired": "This pack size is unavailable.",
            "expiry_blocked": "This pack size is unavailable.",
            "stale": "Availability is being updated. Please try again shortly.",
            "placeholder_price": "Pricing for this product is not yet available.",
            "price_not_activated": "Pricing for this product is not yet available.",
            "not_shown": "This pack size is not available for online purchase.",
            "no_offer": "This pack size is available on request — please contact us.",
            "structurally_inactive": "This pack size is no longer available.",
        }
        return False, messages.get(reason, "This product cannot be added to the cart right now.")

    def _petspot_expiry_display(self, offer=None):
        """Safe expiry display text for frontend (never invalid placeholders)."""
        self.ensure_one()
        offer = offer or self._petspot_primary_offer()
        if not offer:
            return {"state": "unknown", "text": "Expiry confirmed before fulfilment", "near": False}
        if offer.is_expired or offer.availability_state in ("expired", "expiry_blocked"):
            return {"state": "expired", "text": "Unavailable", "near": False}
        if offer.expiry_is_exact and offer.expiry_date:
            raw = str(offer.expiry_date)
            if raw.startswith("0000") or raw.startswith("0001"):
                return {"state": "unknown", "text": "Expiry confirmed before fulfilment", "near": False}
            return {
                "state": "near" if offer.is_near_expiry else "exact",
                "text": f"EXP: {offer.expiry_date}",
                "near": bool(offer.is_near_expiry),
            }
        return {"state": "unknown", "text": "Expiry confirmed before fulfilment", "near": False}

    def _petspot_pack_size_label(self):
        self.ensure_one()
        if self.vetution_size_name:
            return self.vetution_size_name
        ptavs = self.product_template_attribute_value_ids
        if ptavs:
            return ptavs[0].name
        return self.display_name
