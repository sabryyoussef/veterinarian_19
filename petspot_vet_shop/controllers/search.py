# -*- coding: utf-8 -*-
"""Lightweight search suggestions — sanitized, limited, no costs."""

import re

from odoo import http
from odoo.http import request

_SAFE_TERM = re.compile(r"[^\w\s\-\+\./&']+", re.UNICODE)


class PetspotSearchController(http.Controller):

    @http.route(
        "/petspot/shop/suggest",
        type="jsonrpc",
        auth="public",
        website=True,
        readonly=True,
        methods=["POST"],
    )
    def suggest(self, term="", mode="products", limit=8, **kwargs):
        term = _SAFE_TERM.sub(" ", (term or "")).strip()[:80]
        if len(term) < 2:
            return {"products": [], "brands": []}
        limit = min(int(limit or 8), 12)
        website = request.website
        result = {"products": [], "brands": []}

        if mode in ("products", "all"):
            Product = request.env["product.template"].sudo()
            domain = website.sale_product_domain() + [
                ("is_published", "=", True),
                "|", "|", "|",
                ("name", "ilike", term),
                ("vetution_brand_id.name", "ilike", term),
                ("vetution_ingredient_ids.name", "ilike", term),
                ("vetution_species_ids.name", "ilike", term),
            ]
            # Prefer sellable when ready filter applies
            domain = domain + [
                "|",
                ("vetution_id", "=", False),
                ("petspot_shop_has_sellable", "=", True),
            ]
            products = Product.search(domain, limit=limit, order="petspot_shop_has_sellable desc, name")
            for p in products:
                result["products"].append({
                    "id": p.id,
                    "name": p.name,
                    "url": p.website_url,
                    "brand": p.vetution_brand_id.name if p.vetution_brand_id else None,
                    "image_url": f"/web/image/product.template/{p.id}/image_128",
                    "price": p.petspot_shop_min_sellable_price or None,
                    "has_sellable": bool(p.petspot_shop_has_sellable),
                })

        if mode in ("brands", "all"):
            Brand = request.env["vetution.brand"].sudo()
            brands = Brand.search([("name", "ilike", term)], limit=limit, order="name")
            for b in brands:
                result["brands"].append({
                    "id": b.id,
                    "name": b.name,
                    "url": f"/shop?brand={b.id}&search={b.name}",
                })
        return result
