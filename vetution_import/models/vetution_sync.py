# -*- coding: utf-8 -*-
"""Vetution HTTP client + catalog sync (Phase 2).

API quirks handled here:
- Nested pagination: ``{data: {data: [...], meta, links}}`` for brands/drugs.
- Brand detail: ``{data: {brand: {...}, drugs: {...}}}``.
- Category parent ids collide with sub_category ids → parents store slug only;
  children own ``vetution_id`` (product linking key).
- ``meta.total`` is buggy; trust ``meta.last_page``.
- Anonymous prices are 0 / show_price false → never overwrite list_price with 0.

Batch commits every ``COMMIT_EVERY`` products are intentional so a mid-run crash
keeps progress (cron-style).
"""

from __future__ import annotations

import base64
import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

from odoo import api, fields, models
from odoo.exceptions import UserError

from .content_labels import LABEL_TO_FIELD, canonical_field_for_label

_logger = logging.getLogger(__name__)

BASE_URL = "https://dashboard.vetution.site/api/"
COMMIT_EVERY = 50
REQUEST_DELAY = 0.15  # ~6–7 req/s
MAX_RETRIES = 3
USER_AGENT = "PetSpotVetutionSync/1.1 (+odoo; phase2)"

COUNTRY_CODE_MAP = {
    "egypt": "EG",
    "uae": "AE",
    "united arab emirates": "AE",
}

CANONICAL_HTML_FIELDS = list(dict.fromkeys(LABEL_TO_FIELD.values()))

_ISTRANSLATED_RE = re.compile(r"\s*_istranslated=\"[^\"]*\"", re.IGNORECASE)
# Match style="..." even when the value contains nested quotes (e.g. font-family: "Open Sans").
# Ends at a quote followed by whitespace, /, or > (end of the attribute / tag).
_STYLE_ATTR_RE = re.compile(
    r'\s*style\s*=\s*"(?:[^"]*"(?!\s|/?>)[^"]*)*[^"]*"(?=\s|/?>)',
    re.IGNORECASE | re.DOTALL,
)
# Fallback: from style= to just before the tag closer when nested quotes still break parsing.
_STYLE_ATTR_FALLBACK_RE = re.compile(r"\s*style\s*=\s*\"[^\"]*(?=>)", re.IGNORECASE | re.DOTALL)


def mild_sanitize_html(html: str | None) -> str:
    """Strip noisy inline style / _istranslated; keep structure.

    Source HTML often has ``style="font-family: "Open Sans", ..."`` which breaks naive
    ``[^"]*`` stripping and later Odoo's HTML parser (``Multiple elements found (div, divopen)``).
    """
    if not html:
        return ""
    text = _STYLE_ATTR_RE.sub("", html)
    # Second pass for any leftover broken style= remnants
    text = _STYLE_ATTR_FALLBACK_RE.sub("", text)
    text = _ISTRANSLATED_RE.sub("", text)
    # Normalize remaining nested-quote font-family leftovers if any style survived
    text = text.replace('font-family: "Open Sans"', "font-family: Open Sans")
    text = text.replace("font-family: 'Open Sans'", "font-family: Open Sans")
    return text


class VetutionSync(models.AbstractModel):
    _name = "vetution.sync"
    _description = "Vetution Catalog Sync"

    # ------------------------------------------------------------------ HTTP
    @api.model
    def _vetution_http_get(self, path, params=None, raw=False):
        """GET JSON (or bytes if raw) from the Vetution API with retry/backoff."""
        url = path if path.startswith("http") else urllib.parse.urljoin(BASE_URL, path.lstrip("/"))
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        last_err = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                time.sleep(REQUEST_DELAY)
                req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=60) as resp:
                    body = resp.read()
                    if raw:
                        return body
                    return json.loads(body.decode("utf-8"))
            except urllib.error.HTTPError as err:
                last_err = err
                if err.code in (429, 500, 502, 503, 504) and attempt < MAX_RETRIES:
                    delay = 2 ** attempt
                    _logger.warning("Vetution HTTP %s on %s — retry in %ss", err.code, url, delay)
                    time.sleep(delay)
                    continue
                raise
            except Exception as err:  # noqa: BLE001 — network; retry then raise
                last_err = err
                if attempt < MAX_RETRIES:
                    delay = 2 ** attempt
                    _logger.warning("Vetution request failed (%s) — retry in %ss", err, delay)
                    time.sleep(delay)
                    continue
                raise
        raise UserError(f"Vetution HTTP failed for {url}: {last_err}")

    @api.model
    def _unwrap_list_page(self, payload):
        """Return (items, meta) for species/categories/brands/drugs list shapes."""
        data = payload.get("data", payload) if isinstance(payload, dict) else payload
        if isinstance(data, dict) and isinstance(data.get("data"), list):
            return data["data"], data.get("meta") or {}
        if isinstance(data, list):
            return data, (payload.get("meta") if isinstance(payload, dict) else {}) or {}
        return [], {}

    @api.model
    def _download_image_b64(self, url):
        if not url:
            return False
        try:
            raw = self._vetution_http_get(url, raw=True)
            return base64.b64encode(raw)
        except Exception as err:  # noqa: BLE001
            _logger.warning("Logo/image download failed for %s: %s", url, err)
            return False

    # ------------------------------------------------------------------ helpers
    @api.model
    def _log(self, wizard, message):
        _logger.info("vetution.sync: %s", message)
        if wizard:
            wizard._append_log(message)

    @api.model
    def _get_pack_size_attribute(self):
        return self.env.ref("vetution_import.product_attribute_pack_size")

    @api.model
    def _get_vetution_internal_category(self):
        try:
            return self.env.ref("vetution_import.product_category_vetution_import")
        except ValueError:
            Category = self.env["product.category"]
            categ = Category.search([("name", "=", "Vetution Import")], limit=1)
            if not categ:
                categ = Category.create({"name": "Vetution Import"})
            return categ

    @api.model
    def _find_variant_for_size(self, template, size_name, size_id):
        Product = self.env["product.product"]
        if size_id:
            variant = Product.search([("vetution_size_id", "=", size_id)], limit=1)
            if variant:
                return variant
        if not size_name:
            return Product.browse()
        for variant in template.product_variant_ids:
            names = variant.product_template_attribute_value_ids.mapped(
                "product_attribute_value_id.name"
            )
            if size_name in names:
                return variant
        return Product.browse()

    @api.model
    def _upsert_species(self, vetution_id, name):
        Species = self.env["vetution.species"]
        rec = Species.search([("vetution_id", "=", vetution_id)], limit=1)
        vals = {"name": name, "vetution_id": vetution_id}
        if rec:
            rec.write({"name": name})
            return rec
        return Species.create(vals)

    @api.model
    def _upsert_ingredient(self, vetution_id, name):
        Ingredient = self.env["vetution.ingredient"]
        rec = Ingredient.search([("vetution_id", "=", vetution_id)], limit=1)
        if rec:
            # Keep first-seen casing unless name empty
            if not rec.name and name:
                rec.write({"name": name})
            return rec
        return Ingredient.create({"vetution_id": vetution_id, "name": name})

    @api.model
    def _upsert_tag(self, name):
        if not name:
            return self.env["product.tag"]
        Tag = self.env["product.tag"]
        existing = Tag.search([("name", "=ilike", name)], limit=1)
        if existing:
            return existing
        return Tag.create({"name": name})

    @api.model
    def _map_countries(self, country_payloads, wizard=None):
        Country = self.env["res.country"]
        records = Country.browse()
        for item in country_payloads or []:
            name = (item.get("name") or "").strip()
            code = COUNTRY_CODE_MAP.get(name.lower())
            country = Country.search([("code", "=", code)], limit=1) if code else Country.browse()
            if not country and name:
                country = Country.search([("name", "=ilike", name)], limit=1)
            if country:
                records |= country
            else:
                self._log(wizard, f"Unknown country skipped: {name!r}")
        return records

    @api.model
    def _parse_expire_date(self, value):
        if not value:
            return False
        if isinstance(value, datetime):
            return value.date()
        text = str(value).strip()
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y"):
            try:
                return datetime.strptime(text[:10], fmt).date()
            except ValueError:
                continue
        return False

    # ------------------------------------------------------------------ taxonomy
    @api.model
    def sync_species(self, wizard=None):
        payload = self._vetution_http_get("species")
        items, _meta = self._unwrap_list_page(payload)
        count = 0
        for item in items:
            self._upsert_species(item["id"], item["name"])
            count += 1
        self._log(wizard, f"Species synced: {count}")
        return count

    @api.model
    def sync_categories(self, wizard=None):
        """Import category tree into product.public.category.

        Source parent ids collide with sub_category ids. Parents are identified by
        ``vetution_slug`` and do **not** set ``vetution_id``. Children own
        ``vetution_id`` (used when linking products via public_categ_ids).
        """
        PublicCateg = self.env["product.public.category"]
        payload = self._vetution_http_get("categories")
        parents, _meta = self._unwrap_list_page(payload)
        parent_count = 0
        child_count = 0

        # Pre-collect sub ids so we never stamp a colliding parent vetution_id
        sub_ids = {
            sub["id"]
            for parent in parents
            for sub in (parent.get("sub_categories") or [])
        }

        for parent in parents:
            parent_vals = {
                "name": parent.get("name") or parent.get("slug"),
                "vetution_slug": parent.get("slug"),
            }
            # Only set vetution_id on parents when it cannot collide with a sub
            if parent["id"] not in sub_ids:
                parent_vals["vetution_id"] = parent["id"]

            parent_rec = PublicCateg.search(
                [("vetution_slug", "=", parent.get("slug")), ("parent_id", "=", False)],
                limit=1,
            )
            if not parent_rec and parent["id"] not in sub_ids:
                parent_rec = PublicCateg.search(
                    [("vetution_id", "=", parent["id"])],
                    limit=1,
                )
            if parent_rec:
                # Never overwrite a child that already claimed this vetution_id
                write_vals = {
                    "name": parent_vals["name"],
                    "vetution_slug": parent_vals["vetution_slug"],
                }
                if "vetution_id" in parent_vals and not parent_rec.vetution_id:
                    write_vals["vetution_id"] = parent_vals["vetution_id"]
                parent_rec.write(write_vals)
            else:
                parent_rec = PublicCateg.create(parent_vals)
            parent_count += 1

            for sub in parent.get("sub_categories") or []:
                child_vals = {
                    "name": sub.get("name") or sub.get("slug"),
                    "vetution_id": sub["id"],
                    "vetution_slug": sub.get("slug"),
                    "parent_id": parent_rec.id,
                }
                child = PublicCateg.search([("vetution_id", "=", sub["id"])], limit=1)
                if child:
                    child.write(child_vals)
                else:
                    PublicCateg.create(child_vals)
                child_count += 1

        self._log(
            wizard,
            f"Categories synced: {parent_count} parents + {child_count} subs "
            f"(subs own vetution_id; parents use slug due to source id collisions)",
        )
        return parent_count + child_count

    @api.model
    def sync_brands(self, wizard=None, page_from=None, page_to=None):
        Brand = self.env["vetution.brand"]
        first = self._vetution_http_get("brands", params={"page": 1})
        items, meta = self._unwrap_list_page(first)
        last_page = int(meta.get("last_page") or 1)
        start = max(1, int(page_from or 1))
        end = min(last_page, int(page_to or last_page))
        created = updated = 0
        pages = list(range(start, end + 1))
        # page 1 already fetched if start==1
        page_items = {1: items} if start == 1 else {}

        for page in pages:
            if page not in page_items:
                payload = self._vetution_http_get("brands", params={"page": page})
                page_items[page], _m = self._unwrap_list_page(payload)
            for stub in page_items[page]:
                detail = stub
                slug = stub.get("slug")
                try:
                    detail_payload = self._vetution_http_get(f"brands/{slug}")
                    brand_data = (detail_payload.get("data") or {}).get("brand") or detail_payload.get("data") or stub
                    if isinstance(brand_data, dict) and brand_data.get("id"):
                        detail = brand_data
                except Exception as err:  # noqa: BLE001
                    self._log(wizard, f"Brand detail failed for {slug}: {err}")

                vetution_id = detail.get("id") or stub.get("id")
                logo_url = detail.get("logo") or stub.get("logo") or False
                vals = {
                    "name": detail.get("name") or stub.get("name"),
                    "slug": detail.get("slug") or stub.get("slug"),
                    "vetution_id": vetution_id,
                    "logo_url": logo_url,
                    "facebook_page": detail.get("facebook_page") or False,
                    "info": detail.get("info") or False,
                    "meta_title": detail.get("meta_title") or False,
                    "meta_description": detail.get("meta_description") or False,
                }

                rec = Brand.search([("vetution_id", "=", vetution_id)], limit=1)
                if not rec:
                    rec = Brand.search([("slug", "=", vals["slug"])], limit=1)

                # Download logo only when missing (avoids re-fetch + attachment churn)
                if logo_url and (not rec or not rec.logo):
                    logo_b64 = self._download_image_b64(logo_url)
                    if logo_b64:
                        vals["logo"] = logo_b64

                if rec:
                    rec.write(vals)
                    updated += 1
                else:
                    Brand.create(vals)
                    created += 1

                # Commit per brand: keeps progress and shortens ir.attachment lock windows
                self.env.cr.commit()

            self._log(wizard, f"Brands page {page}/{end}: created={created} updated={updated}")
            self.env.cr.commit()

        self._log(wizard, f"Brands done: created={created} updated={updated}")
        return created + updated

    # ------------------------------------------------------------------ products
    @api.model
    def _extract_price_entries(self, prices_payload):
        """Flatten prices[] of {size_name: {vetution: {...}}} into list of vetution dicts."""
        entries = []
        for item in prices_payload or []:
            if not isinstance(item, dict):
                continue
            for _size_key, payload in item.items():
                if not isinstance(payload, dict):
                    continue
                vet = payload.get("vetution") or {}
                if vet:
                    entries.append(vet)
        return entries

    @api.model
    def _safe_html(self, html):
        """Sanitize source HTML so Odoo's Html field parser cannot choke on it."""
        body = mild_sanitize_html(html)
        if not body:
            return ""
        # Nested quotes (font-family: "Open Sans") break attribute parsing → strip all attrs
        if '"' in body and re.search(r"<\w+\s", body):
            body = re.sub(r"<(\w+)(\s[^>]*)?>", r"<\1>", body)
            body = re.sub(r"</(\w+)(\s[^>]*)?>", r"</\1>", body)
        return body

    @api.model
    def _apply_content_blocks(self, template, other_blocks):
        Content = self.env["vetution.content.block"]
        template.vetution_content_ids.unlink()
        canonical = {fname: [] for fname in CANONICAL_HTML_FIELDS}
        seq = 10
        for block in other_blocks or []:
            if not isinstance(block, dict) or not block:
                continue
            label = next(iter(block.keys()))
            raw_html = block.get(label) or ""
            body = self._safe_html(raw_html)
            field_name = canonical_field_for_label(label)
            is_mapped = bool(field_name)
            Content.create(
                {
                    "product_tmpl_id": template.id,
                    "sequence": seq,
                    "label": label,
                    "body_html": body,
                    "is_mapped": is_mapped,
                }
            )
            if field_name:
                canonical[field_name].append(body)
            seq += 10

        vals = {fname: False for fname in CANONICAL_HTML_FIELDS}
        for fname, parts in canonical.items():
            if parts:
                vals[fname] = "<br/>".join(p for p in parts if p)
        if vals.get("vetution_description"):
            vals["website_description"] = vals["vetution_description"]
        template.write(vals)

    @api.model
    def _ensure_pack_size_line(self, template, size_names):
        attr = self._get_pack_size_attribute()
        AttrValue = self.env["product.attribute.value"]
        value_ids = []
        for name in size_names:
            if not name:
                continue
            pav = AttrValue.search(
                [("attribute_id", "=", attr.id), ("name", "=", name)],
                limit=1,
            )
            if not pav:
                pav = AttrValue.create({"attribute_id": attr.id, "name": name})
            value_ids.append(pav.id)
        if not value_ids:
            return

        line = template.attribute_line_ids.filtered(lambda l: l.attribute_id == attr)
        if line:
            # Add any missing values (keep existing)
            line.write({"value_ids": [(4, vid) for vid in value_ids if vid not in line.value_ids.ids]})
        else:
            template.write(
                {
                    "attribute_line_ids": [
                        (
                            0,
                            0,
                            {
                                "attribute_id": attr.id,
                                "value_ids": [(6, 0, value_ids)],
                            },
                        )
                    ]
                }
            )

    @api.model
    def _apply_variants(self, template, price_entries, import_prices=False):
        size_names = []
        for entry in price_entries:
            name = entry.get("name")
            if name and name not in size_names:
                size_names.append(name)

        if not size_names:
            return 0

        self._ensure_pack_size_line(template, size_names)
        template.invalidate_recordset()
        variants_updated = 0
        for entry in price_entries:
            size_id = entry.get("drug_size_id")
            size_name = entry.get("name") or ""
            variant = self._find_variant_for_size(template, size_name, size_id)
            if not variant:
                _logger.warning(
                    "No variant matched for template %s size %s / id %s",
                    template.id,
                    size_name,
                    size_id,
                )
                continue

            vals = {
                "vetution_size_id": size_id or False,
                "vetution_size_name": size_name or False,
                "vetution_out_of_stock": bool(entry.get("out_of_stock")),
                "vetution_expire_date": self._parse_expire_date(entry.get("expire_date")),
                "vetution_image_url": entry.get("image") or False,
            }
            old_price = float(entry.get("old_price") or 0)
            if old_price > 0:
                vals["vetution_old_price"] = old_price

            img_b64 = False
            if entry.get("image") and not variant.image_1920:
                img_b64 = self._download_image_b64(entry.get("image"))
            if img_b64:
                vals["image_1920"] = img_b64

            price = float(entry.get("price") or 0)
            show_price = bool(entry.get("show"))  # per-size show flag
            if import_prices and price > 0 and show_price:
                vals["lst_price"] = price
            # Never write 0 over existing prices (handled by omitting list_price)

            variant.write(vals)
            variants_updated += 1
        return variants_updated

    @api.model
    def _upsert_product(self, list_item, detail, wizard=None, options=None):
        options = options or {}
        import_prices = bool(options.get("import_prices"))
        publish = bool(options.get("publish_products"))
        only_missing = bool(options.get("only_missing"))

        Template = self.env["product.template"]
        Brand = self.env["vetution.brand"]
        PublicCateg = self.env["product.public.category"]

        vetution_id = detail.get("id") or list_item.get("id")
        existing = Template.search([("vetution_id", "=", vetution_id)], limit=1)
        if only_missing and existing:
            return existing, "skipped"

        brand_payload = detail.get("brand") or list_item.get("brand") or {}
        brand = Brand.browse()
        if brand_payload.get("id"):
            brand = Brand.search([("vetution_id", "=", brand_payload["id"])], limit=1)
            if not brand and brand_payload.get("slug"):
                brand = Brand.search([("slug", "=", brand_payload["slug"])], limit=1)

        species_ids = []
        for sp in detail.get("species") or []:
            species_ids.append(self._upsert_species(sp["id"], sp["name"]).id)

        ingredient_ids = []
        for ing in detail.get("ingredients") or list_item.get("ingredients") or []:
            ingredient_ids.append(self._upsert_ingredient(ing["id"], ing["name"]).id)

        tag_ids = []
        for tag in detail.get("tags") or []:
            tag_ids.append(self._upsert_tag(tag.get("name")).id)

        country_ids = self._map_countries(
            detail.get("countries") or list_item.get("countries"),
            wizard=wizard,
        ).ids

        categ_ids = []
        for sub in detail.get("sub_categories") or list_item.get("sub_categories") or []:
            child = PublicCateg.search([("vetution_id", "=", sub["id"])], limit=1)
            if not child:
                child = PublicCateg.create(
                    {
                        "name": sub.get("name") or sub.get("slug"),
                        "vetution_id": sub["id"],
                        "vetution_slug": sub.get("slug"),
                    }
                )
            categ_ids.append(child.id)
            # nice-to-have: also link parent
            if child.parent_id and child.parent_id.id not in categ_ids:
                categ_ids.append(child.parent_id.id)

        cold_chain = list_item.get("cold_chain", detail.get("cold_chain", 0))
        meta_title = detail.get("meta_title") or False
        meta_description = detail.get("meta_description") or False

        vals = {
            "name": detail.get("name") or list_item.get("name"),
            "vetution_id": vetution_id,
            "vetution_slug": detail.get("slug") or list_item.get("slug"),
            "vetution_brand_id": brand.id or False,
            "vetution_species_ids": [(6, 0, species_ids)],
            "vetution_ingredient_ids": [(6, 0, ingredient_ids)],
            "product_tag_ids": [(6, 0, tag_ids)],
            "vetution_country_ids": [(6, 0, country_ids)],
            "public_categ_ids": [(6, 0, categ_ids)],
            "vetution_meta_title": meta_title,
            "vetution_meta_description": meta_description,
            "vetution_show_price": bool(detail.get("show_price") if "show_price" in detail else list_item.get("show_price")),
            "vetution_rate": float(detail.get("rate") or list_item.get("rate") or 0),
            "vetution_rates_count": int(detail.get("rates_count") or list_item.get("rates_count") or 0),
            "vetution_cold_chain": bool(cold_chain),
            "vetution_raw_json": json.dumps(detail, ensure_ascii=False, separators=(",", ":")),
            "vetution_synced_on": fields.Datetime.now(),
        }
        if meta_title:
            vals["website_meta_title"] = meta_title
        if meta_description:
            vals["website_meta_description"] = meta_description

        if existing:
            existing.write(vals)
            template = existing
            status = "updated"
        else:
            create_vals = dict(vals)
            create_vals.update(
                {
                    "type": "consu",
                    "is_storable": True,
                    "sale_ok": True,
                    "purchase_ok": True,
                    "is_published": bool(publish),
                    "categ_id": self._get_vetution_internal_category().id,
                }
            )
            # Do not set list_price on create (defaults to 1.0 in Odoo — leave default;
            # never force 0 from API)
            template = Template.create(create_vals)
            status = "created"

        if publish and not template.is_published:
            template.is_published = True

        self._apply_content_blocks(template, detail.get("other") or [])

        price_entries = self._extract_price_entries(detail.get("prices") or list_item.get("prices"))
        self._apply_variants(template, price_entries, import_prices=import_prices)

        # Template image from first size image
        first_image_url = next((e.get("image") for e in price_entries if e.get("image")), None)
        if first_image_url and (status == "created" or not template.image_1920):
            img = self._download_image_b64(first_image_url)
            if img:
                template.image_1920 = img

        return template, status

    @api.model
    def sync_products(self, wizard=None, page_from=None, page_to=None, slug=None, options=None):
        options = options or {}
        created = updated = skipped = errors = 0

        if slug:
            try:
                detail = self._vetution_http_get(f"drugs/{slug}")
                detail_data = detail.get("data") or detail
                list_stub = {
                    "id": detail_data.get("id"),
                    "slug": slug,
                    "cold_chain": detail_data.get("cold_chain", 0),
                }
                _tmpl, status = self._upsert_product(
                    list_stub, detail_data, wizard=wizard, options=options
                )
                if status == "created":
                    created += 1
                elif status == "updated":
                    updated += 1
                else:
                    skipped += 1
            except Exception as err:  # noqa: BLE001
                errors += 1
                self._log(wizard, f"ERROR product {slug}: {err}")
                _logger.exception("Product sync failed for %s", slug)
            self._log(
                wizard,
                f"Products (slug={slug}): created={created} updated={updated} errors={errors}",
            )
            return {
                "created": created,
                "updated": updated,
                "skipped": skipped,
                "errors": errors,
            }

        first = self._vetution_http_get("drugs", params={"page": 1})
        items, meta = self._unwrap_list_page(first)
        last_page = int(meta.get("last_page") or 1)
        start = max(1, int(page_from or 1))
        end = min(last_page, int(page_to or last_page))
        processed = 0

        for page in range(start, end + 1):
            if page == 1 and start == 1:
                page_items = items
            else:
                payload = self._vetution_http_get("drugs", params={"page": page})
                page_items, _m = self._unwrap_list_page(payload)

            for stub in page_items:
                product_slug = stub.get("slug")
                try:
                    detail_payload = self._vetution_http_get(f"drugs/{product_slug}")
                    detail_data = detail_payload.get("data") or detail_payload
                    _tmpl, status = self._upsert_product(
                        stub, detail_data, wizard=wizard, options=options
                    )
                    if status == "created":
                        created += 1
                    elif status == "updated":
                        updated += 1
                    else:
                        skipped += 1
                except Exception as err:  # noqa: BLE001
                    errors += 1
                    self._log(wizard, f"ERROR product {product_slug}: {err}")
                    _logger.exception("Product sync failed for %s", product_slug)

                processed += 1
                if processed % COMMIT_EVERY == 0:
                    self.env.cr.commit()
                    self._log(
                        wizard,
                        f"Progress: {processed} products (page {page}/{end}) "
                        f"created={created} updated={updated} errors={errors}",
                    )

            self._log(
                wizard,
                f"Products page {page}/{end}: created={created} updated={updated} "
                f"skipped={skipped} errors={errors}",
            )
            self.env.cr.commit()

        result = {
            "created": created,
            "updated": updated,
            "skipped": skipped,
            "errors": errors,
            "processed": processed,
        }
        self._log(wizard, f"Products done: {result}")
        return result

    @api.model
    def sync_cross_links(self, wizard=None):
        Template = self.env["product.template"]
        templates = Template.search([("vetution_id", "!=", False), ("vetution_raw_json", "!=", False)])
        linked = 0
        missing = 0
        # Build id → template map once
        id_map = {t.vetution_id: t for t in Template.search([("vetution_id", "!=", False)])}

        for idx, tmpl in enumerate(templates, start=1):
            try:
                detail = json.loads(tmpl.vetution_raw_json)
            except json.JSONDecodeError:
                missing += 1
                continue
            similar_ids = []
            for stub in detail.get("similars") or []:
                target = id_map.get(stub.get("id"))
                if target and target.id != tmpl.id:
                    similar_ids.append(target.id)
                else:
                    missing += 1
            alt_ids = []
            for stub in detail.get("alternatives") or []:
                target = id_map.get(stub.get("id"))
                if target and target.id != tmpl.id:
                    alt_ids.append(target.id)
                else:
                    missing += 1
            tmpl.write(
                {
                    "vetution_similar_ids": [(6, 0, similar_ids)],
                    "vetution_alternative_ids": [(6, 0, alt_ids)],
                }
            )
            linked += 1
            if idx % COMMIT_EVERY == 0:
                self.env.cr.commit()
                self._log(wizard, f"Cross-links progress: {idx}/{len(templates)}")

        self.env.cr.commit()
        self._log(wizard, f"Cross-links done: templates={linked} unresolved refs={missing}")
        return {"templates": linked, "missing_refs": missing}

    @api.model
    def sync_taxonomy(self, wizard=None, brand_page_from=None, brand_page_to=None):
        self.sync_species(wizard=wizard)
        self.env.cr.commit()
        self.sync_categories(wizard=wizard)
        self.env.cr.commit()
        self.sync_brands(wizard=wizard, page_from=brand_page_from, page_to=brand_page_to)
        self.env.cr.commit()

    @api.model
    def sync_full(self, wizard=None, options=None):
        options = options or {}
        self.sync_taxonomy(
            wizard=wizard,
            brand_page_from=options.get("brand_page_from"),
            brand_page_to=options.get("brand_page_to"),
        )
        self.sync_products(
            wizard=wizard,
            page_from=options.get("page_from"),
            page_to=options.get("page_to"),
            slug=options.get("slug"),
            options=options,
        )
        self.sync_cross_links(wizard=wizard)
        self._log(wizard, "Full sync finished")
