# -*- coding: utf-8 -*-
"""Label normalization for Vetution ``other`` content blocks.

Phase 2 imports this map rather than redefining it. Normalization rule:
lowercase → strip → remove trailing ``:`` → collapse internal whitespace.
"""

from __future__ import annotations

import re

# Normalized source labels → canonical product.template Html field name.
LABEL_TO_FIELD = {
    "description": "vetution_description",
    "descriptions": "vetution_description",
    "details": "vetution_description",
    "properties": "vetution_description",
    "composition": "vetution_composition",
    "ingredients": "vetution_composition",
    "ingredient": "vetution_composition",
    "ingredients & additives": "vetution_composition",
    "nutritional composition": "vetution_composition",
    "additives per kg": "vetution_composition",
    "dietary additives per kilogram": "vetution_composition",
    "dosage": "vetution_dosage",
    "dosage and administration": "vetution_dosage",
    "dosage & administration": "vetution_dosage",
    "direction for use": "vetution_dosage",
    "indication": "vetution_indications",
    "indications": "vetution_indications",
    "clinical particulars": "vetution_indications",
    "contraindications": "vetution_contraindications",
    "side effects": "vetution_side_effects",
    "precautions": "vetution_precautions",
    "safety": "vetution_precautions",
    "warnings": "vetution_warnings",
    "storage": "vetution_storage",
    "features": "vetution_features",
    "feeding guide": "vetution_feeding_guide",
    "feeding recommendations": "vetution_feeding_guide",
    "feeding recommedations": "vetution_feeding_guide",
    "analytical constituents": "vetution_analytical_constituents",
    "analytical ingredients": "vetution_analytical_constituents",
    "how to use": "vetution_how_to_use",
    "watch video": "vetution_video_html",
}

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_label(label: str | None) -> str:
    """Normalize a free-form Vetution ``other`` label for map lookup / grouping."""
    if not label:
        return ""
    text = label.lower().strip().rstrip(":").strip()
    return _WHITESPACE_RE.sub(" ", text)


def canonical_field_for_label(label: str | None) -> str | None:
    """Return the canonical Html field name, or None if the label is unmapped."""
    return LABEL_TO_FIELD.get(normalize_label(label))
