# -*- coding: utf-8 -*-
"""Evidence-based product equivalence classifier for Vendor Sell-Through.

No automatic merges. Callers may only act on SAFE_EXACT_DUPLICATE.
Does not rewrite posted transactional product IDs.
"""

from __future__ import annotations

import re

SAFE_EXACT_DUPLICATE = "SAFE_EXACT_DUPLICATE"
DIFFERENT_STRENGTH_OR_PACK = "DIFFERENT_STRENGTH_OR_PACK"
INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
NOT_DUPLICATE = "NOT_DUPLICATE"

# Explicit forbidden pairs (default_code, default_code) — order-insensitive
_FORBIDDEN_CODE_PAIRS = frozenset(
    {
        frozenset({"APOQ-3.6", "APOQ-16"}),
    }
)


def _norm(s):
    return (s or "").strip().lower()


def _codes(a, b):
    return {(a.default_code or "").strip(), (b.default_code or "").strip()} - {""}


def _strength_tokens(text):
    """Extract numeric tokens that often encode strength / weight bands."""
    return set(re.findall(r"\d+(?:\.\d+)?", _norm(text)))


def classify_product_pair(product_a, product_b):
    """Classify whether two product.product records are safe exact duplicates.

    Returns (classification, reasons:list[str]).
    """
    if not product_a or not product_b:
        return NOT_DUPLICATE, ["missing product"]
    if product_a.id == product_b.id:
        return SAFE_EXACT_DUPLICATE, ["same product id"]

    reasons = []
    codes = _codes(product_a, product_b)
    code_pair = frozenset(codes)
    if len(codes) == 2 and code_pair in _FORBIDDEN_CODE_PAIRS:
        return DIFFERENT_STRENGTH_OR_PACK, ["explicitly forbidden strength pair: %s" % sorted(codes)]

    # Different coded SKUs that disagree on numeric identity → different pack/strength
    if len(codes) == 2:
        ca, cb = sorted(codes)
        ta, tb = _strength_tokens(ca), _strength_tokens(cb)
        if ta and tb and ta != tb:
            return DIFFERENT_STRENGTH_OR_PACK, [
                "default_code strength/pack tokens differ: %s vs %s" % (ca, cb)
            ]

    if product_a.uom_id != product_b.uom_id:
        reasons.append(
            "uom differs: %s vs %s" % (product_a.uom_id.display_name, product_b.uom_id.display_name)
        )

    ba, bb = product_a.barcode, product_b.barcode
    if ba and bb and ba != bb:
        return DIFFERENT_STRENGTH_OR_PACK, ["barcode differs: %s vs %s" % (ba, bb)]

    # Revolution / unlabeled loose names without code cannot be proven against REVC-*
    name_a, name_b = _norm(product_a.name), _norm(product_b.name)
    if ("revolution" in name_a or "revolution" in name_b) and not (
        product_a.default_code and product_b.default_code and ba and bb and ba == bb
    ):
        reasons.append("Revolution variant lacks matching barcode and both default_codes")

    # Name-only similarity is never enough for SAFE
    if ba and bb and ba == bb and product_a.uom_id == product_b.uom_id:
        # Still require matching strength tokens when both codes present
        if len(codes) == 2:
            ca, cb = sorted(codes)
            if _strength_tokens(ca) != _strength_tokens(cb):
                return DIFFERENT_STRENGTH_OR_PACK, ["codes disagree on strength despite shared barcode"]
        return SAFE_EXACT_DUPLICATE, ["identical barcode and uom"]

    if reasons:
        return INSUFFICIENT_EVIDENCE, reasons

    return INSUFFICIENT_EVIDENCE, [
        "no barcode equality and no contradictory coded strength proof; refuse fuzzy name merge"
    ]
