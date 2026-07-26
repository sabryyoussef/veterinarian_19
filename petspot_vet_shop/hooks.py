# -*- coding: utf-8 -*-
"""Phase 5 install hooks: recompute shop state + migrate Phase 4 temporary archives."""

import json
import logging

_logger = logging.getLogger(__name__)

EVIDENCE_PATH = "/home/sabry/vetution-import/p0-data/phase5_variant_migration.json"


def _migrate_phase4_archived_variants(env):
    """Unarchive structurally valid Phase-4 pricing-blocked variants.

    Keeps commercial block via petspot_shop_* computed state (and the
    vetution_variant_blocked_by_pricing flag for audit). Does NOT unarchive
    variants that lack a size mapping / offer and look corrupt.
    """
    PP = env["product.product"].with_context(active_test=False)
    blocked = PP.search([
        ("vetution_variant_blocked_by_pricing", "=", True),
        ("active", "=", False),
        ("product_tmpl_id.vetution_id", "!=", False),
    ])
    unarchived = []
    kept_inactive = []
    for v in blocked:
        # Structurally valid = has size id and a primary offer (even if OOS/unknown)
        has_size = bool(v.vetution_size_id)
        offer = env["vetution.supplier.offer"].search([
            ("product_id", "=", v.id),
            ("offer_type", "=", "vetution"),
        ], limit=1)
        if has_size and offer:
            v.with_context(petspot_shop_migration=True).write({"active": True})
            # Clear the Phase-4 archive flag meaning; commercial block is computed.
            # Keep vetution_variant_blocked_by_pricing as historical audit marker
            # until shop state confirms block — then clear it so future pricing
            # activation does not re-archive.
            v.vetution_variant_blocked_by_pricing = False
            unarchived.append({
                "variant_id": v.id,
                "tmpl_id": v.product_tmpl_id.id,
                "slug": v.product_tmpl_id.vetution_slug,
                "size_id": v.vetution_size_id,
                "offer_avail": offer.availability_state,
            })
        else:
            kept_inactive.append({
                "variant_id": v.id,
                "tmpl_id": v.product_tmpl_id.id,
                "slug": v.product_tmpl_id.vetution_slug,
                "size_id": v.vetution_size_id,
                "reason": "missing_size_or_offer",
            })
    evidence = {
        "unarchived": unarchived,
        "kept_inactive": kept_inactive,
        "unarchived_count": len(unarchived),
        "kept_inactive_count": len(kept_inactive),
    }
    try:
        with open(EVIDENCE_PATH, "w", encoding="utf-8") as fh:
            json.dump(evidence, fh, indent=2, default=str)
    except OSError:
        _logger.exception("Could not write migration evidence")
    _logger.info(
        "petspot_vet_shop migration: unarchived=%s kept_inactive=%s",
        len(unarchived), len(kept_inactive),
    )
    return evidence


def post_init_hook(env):
    _migrate_phase4_archived_variants(env)
    # Recompute commercial state for Vetution variants (batch)
    PP = env["product.product"].with_context(active_test=False)
    variants = PP.search([("product_tmpl_id.vetution_id", "!=", False)])
    # Process in chunks to limit memory
    for offset in range(0, len(variants), 500):
        chunk = variants[offset:offset + 500]
        chunk._compute_petspot_shop_state()
        chunk.mapped("product_tmpl_id")._compute_petspot_shop_has_sellable()
    # Transaction is managed by the module install.
