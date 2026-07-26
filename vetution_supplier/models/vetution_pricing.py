# -*- coding: utf-8 -*-
"""Controlled selling-price activation for Vetution supplier offers."""

from __future__ import annotations

import logging
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

PLACEHOLDER_MAX = 1.01
PILOT_MAX_TEMPLATES = 50


class VetutionPricing(models.AbstractModel):
    _name = "vetution.pricing"
    _description = "Vetution Selling Price Activation"

    @api.model
    def _assert_fresh_and_auth(self, connection):
        connection.ensure_one()
        # Auth
        self.env["vetution.commercial.sync"].assert_authentication(connection)
        # Freshness: latest full commercial sync within stale_after_hours
        log = self.env["vetution.sync.log"].search(
            [
                ("connection_id", "=", connection.id),
                ("sync_type", "=", "full_commercial"),
                ("state", "=", "done"),
            ],
            order="id desc",
            limit=1,
        )
        if not log or not log.ended_at:
            raise UserError("No successful full commercial sync found. Abort pricing.")
        age = fields.Datetime.now() - log.ended_at
        max_age = timedelta(hours=connection.stale_after_hours or 12)
        if age > max_age:
            raise UserError(
                f"Commercial data is stale (last full sync ended {log.ended_at}, "
                f"age {age}, threshold {max_age}). Abort pricing."
            )
        return log

    @api.model
    def select_pilot_templates(self, connection, limit=PILOT_MAX_TEMPLATES):
        """Select ≤50 eligible single-variant templates for the pricing pilot.

        Criteria:
        - exactly one product variant
        - that variant has a primary offer active_for_procurement
        - not sale-price locked
        - offer not stale / not needs_review (except expiry_unknown alone is OK)
        - effective_cost > 0
        Diversify by brand and include Phase 0 pilot slugs when eligible.
        """
        connection.ensure_one()
        Offer = self.env["vetution.supplier.offer"]
        from odoo.addons.vetution_supplier.models.vetution_commercial_sync import (
            PILOT_SLUGS,
        )

        offers = Offer.search(
            [
                ("connection_id", "=", connection.id),
                ("offer_type", "=", "vetution"),
                ("active_for_procurement", "=", True),
                ("effective_cost", ">", 0),
                ("product_id", "!=", False),
                ("product_tmpl_id", "!=", False),
                ("is_stale", "=", False),
            ]
        )
        # Drop hard review flags (keep expiry_unknown)
        def _hard_review(o):
            reason = o.review_reason or ""
            hard = {
                "duplicate_size_id_in_payload",
                "conflict_qty_pos",
                "qty_negative",
                "missing_variant_mapping",
                "not_seen_in_full_sync",
            }
            return any(h in reason for h in hard)

        offers = offers.filtered(lambda o: not _hard_review(o))
        # Template must not be locked and must have exactly 1 variant
        candidates = []
        seen_tmpl = set()
        # Prefer UAT pilot slugs first
        ordered = sorted(
            offers,
            key=lambda o: (
                0 if o.drug_slug in PILOT_SLUGS else 1,
                o.product_tmpl_id.vetution_brand_id.id
                if o.product_tmpl_id.vetution_brand_id
                else 0,
                o.effective_cost,
            ),
        )
        brands_used = {}
        for o in ordered:
            tmpl = o.product_tmpl_id
            if tmpl.id in seen_tmpl:
                continue
            if tmpl.vetution_sale_price_locked:
                continue
            variants = tmpl.product_variant_ids
            if len(variants) != 1:
                continue
            if o.product_id != variants[0]:
                continue
            brand = tmpl.vetution_brand_id.id if tmpl.vetution_brand_id else 0
            # Cap per brand to keep diversity (max 4)
            if brands_used.get(brand, 0) >= 4 and len(candidates) < limit:
                # still allow if we don't have enough yet and brand is common
                if len(candidates) > limit // 2:
                    continue
            candidates.append(tmpl)
            seen_tmpl.add(tmpl.id)
            brands_used[brand] = brands_used.get(brand, 0) + 1
            if len(candidates) >= limit:
                break
        return self.env["product.template"].browse([t.id for t in candidates])

    @api.model
    def _change_allowed(self, connection, old_price, new_price):
        """Placeholder prices (≤1.01) bypass the max-change guard."""
        old = float(old_price or 0.0)
        new = float(new_price or 0.0)
        if old <= PLACEHOLDER_MAX:
            return True, "placeholder_bypass"
        if old <= 0:
            return True, "zero_old"
        pct = abs(new - old) / old * 100.0
        max_pct = connection.max_auto_price_change_percent or 0.0
        if pct > max_pct:
            return False, f"change_{pct:.1f}%_exceeds_{max_pct}%"
        return True, "within_limit"

    @api.model
    def activate_template_price(self, connection, template, dry_run=False):
        """Activate selling price for a single-variant eligible template."""
        template.ensure_one()
        connection.ensure_one()
        Log = self.env["vetution.price.change.log"]
        if template.vetution_sale_price_locked:
            return Log.create(
                {
                    "name": f"SKIP locked {template.display_name}",
                    "connection_id": connection.id,
                    "product_tmpl_id": template.id,
                    "dry_run": dry_run,
                    "skipped": True,
                    "skip_reason": "sale_price_locked",
                    "old_list_price": template.list_price,
                }
            )
        variant = template.product_variant_id
        offer = self.env["vetution.supplier.offer"].search(
            [
                ("connection_id", "=", connection.id),
                ("product_id", "=", variant.id),
                ("offer_type", "=", "vetution"),
                ("active_for_procurement", "=", True),
                ("effective_cost", ">", 0),
            ],
            limit=1,
        )
        if not offer:
            return Log.create(
                {
                    "name": f"SKIP no eligible offer {template.display_name}",
                    "connection_id": connection.id,
                    "product_tmpl_id": template.id,
                    "product_id": variant.id,
                    "dry_run": dry_run,
                    "skipped": True,
                    "skip_reason": "no_eligible_offer",
                    "old_list_price": template.list_price,
                }
            )
        breakdown = connection.compute_sale_price(offer.effective_cost)
        new_price = breakdown["selling_price"]
        old_price = template.list_price
        allowed, reason = self._change_allowed(connection, old_price, new_price)
        placeholder = float(old_price or 0) <= PLACEHOLDER_MAX
        if not allowed:
            return Log.create(
                {
                    "name": f"SKIP change limit {template.display_name}",
                    "connection_id": connection.id,
                    "product_tmpl_id": template.id,
                    "product_id": variant.id,
                    "offer_id": offer.id,
                    "dry_run": dry_run,
                    "skipped": True,
                    "skip_reason": reason,
                    "old_list_price": old_price,
                    "new_list_price": new_price,
                    "supplier_cost": breakdown["supplier_cost"],
                    "placeholder_replacement": placeholder,
                }
            )
        profit = new_price - breakdown["supplier_cost"]
        margin = (profit / new_price * 100.0) if new_price else 0.0
        vals_log = {
            "name": f"{'DRY ' if dry_run else ''}ACTIVATE {template.display_name}",
            "connection_id": connection.id,
            "product_tmpl_id": template.id,
            "product_id": variant.id,
            "offer_id": offer.id,
            "dry_run": dry_run,
            "skipped": False,
            "placeholder_replacement": placeholder,
            "old_list_price": old_price,
            "new_list_price": new_price,
            "supplier_cost": breakdown["supplier_cost"],
            "markup_price": breakdown["markup_price"],
            "minimum_margin_price": breakdown["minimum_margin_price"],
            "minimum_profit_price": breakdown["minimum_profit_price"],
            "candidate": breakdown["candidate"],
            "markup_percent": breakdown["markup_percent"],
            "min_margin_percent": breakdown["min_margin_percent"],
            "min_profit_amount": breakdown["min_profit_amount"],
            "rounding": breakdown["rounding"],
            "gross_profit": profit,
            "gross_margin_percent": margin,
            "note": reason,
        }
        log = Log.create(vals_log)
        if not dry_run:
            template.with_context(vetution_price_activation=True).write(
                {
                    "list_price": new_price,
                    "vetution_price_activated": True,
                    "vetution_last_activated_cost": breakdown["supplier_cost"],
                    "vetution_last_sale_price": new_price,
                    "vetution_last_price_activation_at": fields.Datetime.now(),
                }
            )
            offer.write({"preview_sale_price": new_price})
        return log

    @api.model
    def activate_pilot(self, connection, templates=None, dry_run=False, limit=PILOT_MAX_TEMPLATES):
        """Run controlled pilot activation for ≤50 templates."""
        connection.ensure_one()
        self._assert_fresh_and_auth(connection)
        if templates is None:
            templates = self.select_pilot_templates(connection, limit=limit)
        else:
            templates = templates[:limit]
        if len(templates) > limit:
            raise UserError(f"Pilot limited to {limit} templates.")
        logs = self.env["vetution.price.change.log"]
        for tmpl in templates:
            logs |= self.activate_template_price(connection, tmpl, dry_run=dry_run)
        return logs
