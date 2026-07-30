# -*- coding: utf-8 -*-
"""Parse PetSpot Shopify availability CTA WhatsApp text."""
import re

# Stable marker from live theme snippet petspot-availability-cta.liquid
CTA_MARKER = "Request availability — pet.spot"
CTA_MARKER_ALT = (
    "Request availability - pet.spot",  # hyphen variant
    "طلب التوفر — pet.spot",
    "طلب التوفر - pet.spot",
)

_SKU_RE = re.compile(r"(?im)^\s*SKU:\s*(.+?)\s*$")
_VARIANT_ID_RE = re.compile(r"(?im)^\s*Variant ID:\s*(\d+)\s*$")
_URL_RE = re.compile(r"(?im)^\s*URL:\s*(\S+)\s*$")
_QTY_RE = re.compile(r"(?im)^\s*Requested quantity:\s*([0-9]+(?:\.[0-9]+)?)\s*$")
_PRODUCT_RE = re.compile(r"(?im)^\s*Product:\s*(.+?)\s*$")
_VARIANT_TITLE_RE = re.compile(r"(?im)^\s*Variant / pack size:\s*(.+?)\s*$")


def is_availability_cta(content):
    if not content:
        return False
    text = content.strip()
    if CTA_MARKER in text:
        return True
    for alt in CTA_MARKER_ALT:
        if alt in text:
            return True
    return False


def parse_availability_cta(content):
    """Return structured fields from CTA body. Never invent SKU/variant."""
    text = (content or "").strip()
    sku_m = _SKU_RE.search(text)
    var_m = _VARIANT_ID_RE.search(text)
    url_m = _URL_RE.search(text)
    qty_m = _QTY_RE.search(text)
    prod_m = _PRODUCT_RE.search(text)
    vtitle_m = _VARIANT_TITLE_RE.search(text)
    qty = 1.0
    if qty_m:
        try:
            qty = float(qty_m.group(1))
        except ValueError:
            qty = 1.0
    return {
        "is_cta": is_availability_cta(text),
        "sku": (sku_m.group(1).strip() if sku_m else "") or False,
        "shopify_variant_id": (var_m.group(1).strip() if var_m else "") or False,
        "product_url": (url_m.group(1).strip() if url_m else "") or False,
        "requested_qty": qty,
        "product_title": (prod_m.group(1).strip() if prod_m else "") or False,
        "variant_title": (vtitle_m.group(1).strip() if vtitle_m else "") or False,
        "sanitized_message": _sanitize_message(text),
    }


def _sanitize_message(text, max_len=2000):
    """Trim and redact obvious tokens; keep CTA fields for staff review."""
    cleaned = re.sub(r"(?i)(api[_-]?token|secret|password)\s*[:=]\s*\S+", r"\1=***", text or "")
    cleaned = cleaned.strip()
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len] + "…"
    return cleaned


def normalize_eg_phone(raw):
    """Normalize Egyptian mobile to +20XXXXXXXXXX when possible."""
    if not raw:
        return False
    s = str(raw).strip()
    s = re.sub(r"[\s\-().]", "", s)
    if s.lower().startswith("whatsapp:"):
        s = s[len("whatsapp:"):]
    if s.startswith("00"):
        s = "+" + s[2:]
    body = re.sub(r"\D", "", s[1:] if s.startswith("+") else s)
    if body.startswith("20") and len(body) >= 12:
        return "+%s" % body[:12]
    if body.startswith("0") and len(body) == 11:
        return "+20%s" % body[1:]
    if len(body) == 10 and body.startswith("1"):
        return "+20%s" % body
    if body:
        return "+%s" % body
    return False
