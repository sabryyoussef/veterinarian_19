# -*- coding: utf-8 -*-
"""Shop page extensions: guided filters, cart warnings, product payload route."""

import logging

from odoo import http
from odoo.http import request
from odoo.addons.website_sale.controllers.main import WebsiteSale

_logger = logging.getLogger(__name__)


class PetspotWebsiteSale(WebsiteSale):

    def _get_search_options(self, *args, **kwargs):
        options = super()._get_search_options(*args, **kwargs)
        options["petspot_ready_only"] = request.params.get("include_request") != "1"
        options["petspot_include_request"] = request.params.get("include_request") == "1"
        return options

    def _shop_get_query_url_kwargs(self, search, min_price, max_price, order=None, tags=None, **kwargs):
        result = super()._shop_get_query_url_kwargs(
            search, min_price, max_price, order=order, tags=tags, **kwargs
        )
        for key in ("species", "brand", "availability", "include_request", "mode"):
            val = kwargs.get(key) or request.params.get(key)
            if val:
                result[key] = val
        return result

    def _add_search_subdomains_hook(self, search):
        """Match brand / species / ingredient / pack size for price-filter domain path.

        Must return a single OR-able domain (not a list of domains) — see
        website_sale ``_get_shop_domain``.
        """
        from odoo.fields import Domain

        super_result = super()._add_search_subdomains_hook(search)
        term = (search or "").strip()
        if not term:
            return super_result
        Brand = request.env["vetution.brand"].sudo()
        Species = request.env["vetution.species"].sudo()
        Ingredient = request.env["vetution.ingredient"].sudo()
        Tag = request.env["product.tag"].sudo()
        parts = [Domain("product_variant_ids.vetution_size_name", "ilike", term)]
        brand_ids = Brand.search([("name", "ilike", term)]).ids
        if brand_ids:
            parts.append(Domain("vetution_brand_id", "in", brand_ids))
        species_ids = Species.search([("name", "ilike", term)]).ids
        if species_ids:
            parts.append(Domain("vetution_species_ids", "in", species_ids))
        ingredient_ids = Ingredient.search([("name", "ilike", term)]).ids
        if ingredient_ids:
            parts.append(Domain("vetution_ingredient_ids", "in", ingredient_ids))
        tag_ids = Tag.search([("name", "ilike", term)]).ids
        if tag_ids:
            parts.append(Domain("product_tag_ids", "in", tag_ids))
        petspot = Domain.OR(parts)
        if super_result:
            return Domain.OR([super_result, petspot])
        return petspot

    def _shop_lookup_products(self, options, post, search, website):
        fuzzy_search_term, product_count, search_result = super()._shop_lookup_products(
            options, post, search, website
        )
        # Guided sidebar filters (species / brand / availability) — GET params, no JS required
        domain = []
        species = post.get("species") or request.params.get("species")
        brand = post.get("brand") or request.params.get("brand")
        availability = post.get("availability") or request.params.get("availability")
        if species:
            try:
                domain.append(("vetution_species_ids", "in", [int(species)]))
            except (TypeError, ValueError):
                pass
        if brand:
            try:
                domain.append(("vetution_brand_id", "=", int(brand)))
            except (TypeError, ValueError):
                pass
        if availability in ("available", "limited", "out_of_stock", "unknown"):
            domain.append(
                ("product_variant_ids.petspot_shop_availability", "=", availability)
            )
        if domain:
            search_result = search_result.filtered_domain(domain)
            product_count = len(search_result)
        return fuzzy_search_term, product_count, search_result

    def _get_additional_shop_values(self, values, **kwargs):
        # NB: the base hook returns a dict of *additional* values (merged into
        # the render context by shop()); the full render values arrive in the
        # ``values`` parameter. Read products from the parameter, never from
        # the returned additional dict.
        vals = super()._get_additional_shop_values(values, **kwargs)
        # Guided sidebar data (safe, no costs)
        Brand = request.env["vetution.brand"].sudo()
        Species = request.env["vetution.species"].sudo()
        vals["petspot_brands"] = Brand.search([], order="name", limit=80)
        vals["petspot_species"] = Species.search([], order="name", limit=40)
        vals["petspot_mode"] = request.params.get("mode") or "products"
        vals["petspot_active_species"] = request.params.get("species")
        vals["petspot_active_brand"] = request.params.get("brand")
        vals["petspot_active_availability"] = request.params.get("availability")
        vals["petspot_include_request"] = request.params.get("include_request") == "1"
        products = values.get("products") or request.env["product.template"]
        wishlist_ids = set()
        payloads = {}
        payload_json = {}
        import json as _json
        # Page-level offer prefetch: one query for every variant on the page so
        # per-card serialization never issues a per-variant (N+1) offer lookup.
        all_variant_ids = products.with_context(active_test=False).product_variant_ids.ids
        offer_map = request.env["product.template"]._petspot_bulk_offer_map(all_variant_ids)
        for tmpl in products:
            try:
                p = tmpl._get_petspot_shop_payload(
                    wishlist_product_ids=wishlist_ids, offer_map=offer_map
                )
                payloads[tmpl.id] = p
                payload_json[tmpl.id] = _json.dumps(p)
            except Exception:  # noqa: BLE001
                _logger.exception("petspot shop payload failed for template %s", tmpl.id)
        vals["petspot_payloads"] = payloads
        vals["petspot_payload_json"] = payload_json
        return vals

    @http.route()
    def cart(self, **post):
        response = super().cart(**post)
        # Inject commercial revalidation warnings (do not silently remove lines)
        order = request.website.sale_get_order()
        if order and hasattr(response, "qcontext"):
            response.qcontext["petspot_cart_warnings"] = order._petspot_cart_warnings()
        return response


class PetspotShopController(http.Controller):

    @http.route(
        "/petspot/shop/product_payload/<int:template_id>",
        type="jsonrpc",
        auth="public",
        website=True,
        readonly=True,
    )
    def product_payload(self, template_id, **kwargs):
        tmpl = request.env["product.template"].browse(template_id).exists()
        if not tmpl or not tmpl.is_published:
            return {"error": "not_found"}
        return tmpl._get_petspot_shop_payload()

    @http.route(
        "/petspot/shop/notify",
        type="jsonrpc",
        auth="public",
        website=True,
        methods=["POST"],
    )
    def notify_request(self, product_id=None, email=None, request_type="notify", note=None, **kwargs):
        email = (email or "").strip()
        if not email or "@" not in email:
            return {"ok": False, "error": "valid_email_required"}
        product = request.env["product.product"].browse(int(product_id or 0)).exists()
        if not product or not product.product_tmpl_id.is_published:
            return {"ok": False, "error": "not_found"}
        if request_type not in ("notify", "request", "contact"):
            return {"ok": False, "error": "invalid_type"}
        # Eligibility: notify only when notify_allowed; request when request_allowed
        if request_type == "notify" and not product.petspot_shop_notify_allowed:
            return {"ok": False, "error": "notify_not_allowed"}
        if request_type in ("request", "contact") and not (
            product.petspot_shop_request_allowed or product.petspot_shop_notify_allowed
        ):
            # Allow contact for price_hidden / unknown
            if product.petspot_shop_availability not in ("price_hidden", "unknown", "no_offer", "placeholder", "not_activated"):
                return {"ok": False, "error": "request_not_allowed"}
        partner = request.env.user.partner_id if not request.env.user._is_public() else False
        request.env["petspot.shop.notify"].sudo().create({
            "email": email,
            "partner_id": partner.id if partner else False,
            "product_tmpl_id": product.product_tmpl_id.id,
            "product_id": product.id,
            "request_type": request_type,
            "note": (note or "")[:2000],
            "website_id": request.website.id,
        })
        return {"ok": True}
