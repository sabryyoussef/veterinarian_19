# -*- coding: utf-8 -*-
"""PetSpot shop serializer and search extensions on product.template."""

from odoo import api, fields, models

from .product_product import AVAIL_LABELS, PLACEHOLDER_MAX

try:
    from odoo.fields import Domain
except ImportError:  # pragma: no cover
    Domain = None


# Fields that must NEVER appear in any public shop payload.
PROHIBITED_PAYLOAD_KEYS = frozenset({
    "effective_cost",
    "supplier_price",
    "supplier_user_price",
    "supplier_qty",
    "supplier_qty_raw",
    "raw_json",
    "vetution_raw_json",
    "token",
    "api_token",
    "password",
    "connection_id",
    "vetution_last_activated_cost",
})


class ProductTemplate(models.Model):
    _inherit = "product.template"

    petspot_shop_has_sellable = fields.Boolean(
        string="Has Shop-Sellable Variant",
        compute="_compute_petspot_shop_has_sellable",
        store=True,
        index=True,
        help="True when at least one variant is commercially sellable on the PetSpot shop.",
    )
    petspot_shop_min_sellable_price = fields.Float(
        compute="_compute_petspot_shop_has_sellable",
        store=True,
        digits="Product Price",
        help="Minimum sellable activated variant price (for shop sorting).",
    )

    @api.depends(
        "product_variant_ids.petspot_shop_sellable",
        "product_variant_ids.petspot_shop_display_price",
        "product_variant_ids.active",
    )
    def _compute_petspot_shop_has_sellable(self):
        for tmpl in self:
            sellable = tmpl.product_variant_ids.filtered("petspot_shop_sellable")
            tmpl.petspot_shop_has_sellable = bool(sellable)
            prices = sellable.mapped("petspot_shop_display_price")
            tmpl.petspot_shop_min_sellable_price = min(prices) if prices else 0.0

    def _get_petspot_default_variant(self):
        """First commercially sellable variant, else first active informational variant."""
        self.ensure_one()
        variants = self.product_variant_ids  # active only by default
        sellable = variants.filtered("petspot_shop_sellable").sorted(
            key=lambda v: v.petspot_shop_display_price or 0.0
        )
        if sellable:
            return sellable[0]
        # Informational: pricing-ready but not sellable, or any active
        ready = variants.filtered("petspot_shop_pricing_ready")
        return ready[:1] or variants[:1]

    @api.model
    def _petspot_bulk_offer_map(self, variant_ids):
        """One-query map {product_id: primary active vetution offer} for a set of variants.

        Lets controllers prefetch offers for a whole listing page so per-card
        serialization does not issue a per-variant (N+1) supplier-offer query.
        """
        offer_map = {}
        if not variant_ids:
            return offer_map
        # sudo: supplier offers are ACL-restricted to purchase users, but the
        # payload serializer only ever exposes safe fields (availability,
        # expiry display). Website visitors need the offer rows to price cards.
        offers = self.env["vetution.supplier.offer"].sudo().search(
            [
                ("product_id", "in", list(variant_ids)),
                ("offer_type", "=", "vetution"),
                ("active", "=", True),
            ],
            order="id",
        )
        for o in offers:
            offer_map.setdefault(o.product_id.id, o)
        return offer_map

    def _get_petspot_shop_payload(self, wishlist_product_ids=None, offer_map=None):
        """Canonical safe frontend serializer for listing cards and PDP helpers.

        Never includes supplier costs, tokens, credentials, or raw JSON.
        ``offer_map`` (optional) is a prefetched {product_id: offer} dict; when not
        supplied it is built once for this template's variants (avoids per-variant
        offer searches / N+1).
        """
        self.ensure_one()
        wishlist_product_ids = set(wishlist_product_ids or [])
        brand = self.vetution_brand_id
        species = self.vetution_species_ids
        ingredients = self.vetution_ingredient_ids
        tags = self.product_tag_ids
        categories = self.public_categ_ids

        # Prefer active variants; include blocked commercial ones that remain active.
        variants = self.product_variant_ids
        default = self._get_petspot_default_variant()
        chip_labels = []
        for ing in ingredients[:6]:
            chip_labels.append({"type": "ingredient", "name": ing.name})
        for sp in species[:4]:
            chip_labels.append({"type": "species", "name": sp.name})
        for tag in tags[:4]:
            chip_labels.append({"type": "tag", "name": tag.name})
        overflow = max(0, len(ingredients) + len(species) + len(tags) - len(chip_labels))

        if offer_map is None:
            offer_map = self._petspot_bulk_offer_map(variants.ids)

        variant_payloads = []
        for v in variants:
            offer = offer_map.get(v.id) or v._petspot_primary_offer()
            expiry = v._petspot_expiry_display(offer)
            avail = v.petspot_shop_availability or "unknown"
            display_price = v.petspot_shop_display_price if v.petspot_shop_pricing_ready else 0.0
            variant_payloads.append({
                "id": v.id,
                "pack_size_label": v._petspot_pack_size_label(),
                "selling_price": display_price,
                "formatted_price": self._petspot_format_price(display_price) if display_price else None,
                "pricing_ready": bool(v.petspot_shop_pricing_ready and display_price > PLACEHOLDER_MAX),
                "availability_state": avail,
                "availability_label": AVAIL_LABELS.get(avail, "Contact us"),
                "expiry_state": expiry["state"],
                "expiry_display": expiry["text"],
                "near_expiry": expiry["near"],
                "supplier_backed": bool(offer),
                "is_express": bool(offer and offer.is_express),
                "add_to_cart_allowed": bool(v.petspot_shop_sellable),
                "notify_me_allowed": bool(v.petspot_shop_notify_allowed),
                "available_on_request": bool(v.petspot_shop_request_allowed),
                "active": bool(v.active),
                "is_default": bool(default and v.id == default.id),
            })

        payload = {
            "id": self.id,
            "name": self.name,
            "url": self.website_url,
            "image_url": f"/web/image/product.template/{self.id}/image_512",
            "brand": brand.name if brand else None,
            "brand_id": brand.id if brand else None,
            "species": species.mapped("name"),
            "ingredients": ingredients.mapped("name"),
            "tags": tags.mapped("name"),
            "categories": categories.mapped("name"),
            "chips": chip_labels,
            "chips_overflow": overflow,
            "cold_chain": bool(self.vetution_cold_chain),
            "wishlist": self.id in wishlist_product_ids or any(
                v.id in wishlist_product_ids for v in variants
            ),
            "published": bool(self.is_published),
            "has_sellable": bool(self.petspot_shop_has_sellable),
            "min_sellable_price": self.petspot_shop_min_sellable_price,
            "default_variant_id": default.id if default else None,
            "variants": variant_payloads,
            "currency": "EGP",
            "tax_label": "excl. tax" if not self.taxes_id else "incl. tax" if all(
                t.price_include for t in self.taxes_id
            ) else "excl. tax",
        }
        # Hard security assert in production paths too
        for key in PROHIBITED_PAYLOAD_KEYS:
            if key in payload:
                payload.pop(key, None)
            for vp in payload["variants"]:
                vp.pop(key, None)
        return payload

    def _petspot_format_price(self, amount):
        currency = self.env.company.currency_id
        return f"{amount:,.2f} {currency.symbol or currency.name}"

    def _search_get_detail(self, website, order, options):
        """Extend native website search carefully.

        Related M2O/M2M paths must NOT go in ``search_fields`` — Odoo fuzzy/
        trigram search breaks on them. Use ``search_extra`` + controller
        subdomain hooks instead.
        """
        result = super()._search_get_detail(website, order, options)
        search_fields = list(result.get("search_fields") or [])
        if "vetution_slug" not in search_fields:
            search_fields.append("vetution_slug")
        result["search_fields"] = search_fields

        def _petspot_search_extra(env, search_term):
            """OR-match brand / species / ingredient / tags / pack size."""
            term = (search_term or "").strip()
            if not term:
                return [("id", "!=", False)]
            brand_ids = env["vetution.brand"].sudo().search([("name", "ilike", term)]).ids
            species_ids = env["vetution.species"].sudo().search([("name", "ilike", term)]).ids
            ingredient_ids = env["vetution.ingredient"].sudo().search([("name", "ilike", term)]).ids
            tag_ids = env["product.tag"].sudo().search([("name", "ilike", term)]).ids
            parts = [
                [("product_variant_ids.vetution_size_name", "ilike", term)],
            ]
            if brand_ids:
                parts.append([("vetution_brand_id", "in", brand_ids)])
            if species_ids:
                parts.append([("vetution_species_ids", "in", species_ids)])
            if ingredient_ids:
                parts.append([("vetution_ingredient_ids", "in", ingredient_ids)])
            if tag_ids:
                parts.append([("product_tag_ids", "in", tag_ids)])
            if Domain is not None:
                return Domain.OR(parts)
            domain = ["|"] * (len(parts) - 1)
            for p in parts:
                domain.extend(p)
            return domain

        result["search_extra"] = _petspot_search_extra

        base_domain = list(result.get("base_domain") or [[]])
        if options.get("petspot_ready_only", True) and not options.get("petspot_include_request"):
            ready_domain = [
                "|",
                ("vetution_id", "=", False),
                ("petspot_shop_has_sellable", "=", True),
            ]
            new_domains = []
            for d in base_domain:
                if Domain is not None:
                    new_domains.append(list(Domain(d) & Domain(ready_domain)))
                else:
                    new_domains.append(list(d) + ready_domain)
            result["base_domain"] = new_domains or [ready_domain]
        else:
            result["base_domain"] = base_domain

        mapping = {
            "petspot_price_asc": "petspot_shop_min_sellable_price asc, name asc",
            "petspot_price_desc": "petspot_shop_min_sellable_price desc, name asc",
            "petspot_brand": "vetution_brand_id, name asc",
            "petspot_availability": "petspot_shop_has_sellable desc, name asc",
        }
        if order in mapping:
            result["order"] = mapping[order]
        return result

    def _get_sales_prices(self, website):
        """Hide placeholder 1.00 prices from public listing price maps."""
        prices = super()._get_sales_prices(website)
        for tmpl in self:
            info = prices.get(tmpl.id)
            if not info:
                continue
            if tmpl.vetution_id and not tmpl.vetution_price_activated:
                info["price_reduce"] = 0.0
                info["price"] = 0.0
                info["petspot_price_pending"] = True
            elif tmpl.vetution_id and float(info.get("price_reduce") or info.get("price") or 0) <= PLACEHOLDER_MAX:
                info["price_reduce"] = 0.0
                info["price"] = 0.0
                info["petspot_price_pending"] = True
        return prices
