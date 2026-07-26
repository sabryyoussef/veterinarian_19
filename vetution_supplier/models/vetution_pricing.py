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

# Phase 4 multi-variant pilot caps
MULTI_PILOT_MAX_TEMPLATES = 30
MULTI_PILOT_MAX_VARIANTS = 100

# Hard review reasons that quarantine an offer from any pricing.
HARD_REVIEW_REASONS = {
    "duplicate_size_id_in_payload",
    "conflict_qty_pos",
    "qty_negative",
    "missing_variant_mapping",
    "not_seen_in_full_sync",
}


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

    # ================================================================
    # Phase 4 — multi-variant (Pack Size) pricing via price_extra
    # ================================================================

    @api.model
    def _variant_primary_offer(self, connection, variant):
        return self.env["vetution.supplier.offer"].search(
            [
                ("connection_id", "=", connection.id),
                ("offer_type", "=", "vetution"),
                ("product_id", "=", variant.id),
            ],
            limit=1,
            order="id",
        )

    @api.model
    def _variant_eligibility(self, connection, template, variant):
        """Evaluate a single variant against the Phase 4 eligibility criteria.

        Returns dict: eligible(bool), reasons(list), flags(list), offer, cost, breakdown.
        """
        reasons = []
        flags = []
        offer = self._variant_primary_offer(connection, variant)
        min_exp = connection.minimum_expiry_days or 90
        if not offer:
            return {
                "eligible": False, "reasons": ["no_primary_offer"], "flags": flags,
                "offer": offer, "cost": 0.0, "breakdown": None,
            }
        if not variant.vetution_size_id or offer.vetution_size_id != variant.vetution_size_id:
            reasons.append("size_mapping_mismatch")
        cost = offer.effective_cost or 0.0
        if cost <= 0:
            reasons.append("no_cost")
        if offer.is_stale:
            reasons.append("stale")
        if not offer.show:
            reasons.append("not_shown")
        if not offer.show_price:
            reasons.append("price_hidden")
        if offer.availability_state not in ("available", "limited"):
            reasons.append(f"avail_{offer.availability_state}")
        if offer.is_expired:
            reasons.append("expired")
        if offer.expiry_is_exact:
            if (offer.days_to_expiry or 0) < min_exp:
                reasons.append(f"expiry_lt_{min_exp}d")
        else:
            flags.append("expiry_unknown")
        if offer.needs_review:
            reasons.append("needs_review")
            r = offer.review_reason or ""
            if any(h in r for h in HARD_REVIEW_REASONS):
                reasons.append("hard_review")
        if template.vetution_sale_price_locked:
            reasons.append("template_price_locked")
        # Supplierinfo consistency (integration-owned row for this variant)
        si = self.env["product.supplierinfo"].search(
            [
                ("product_id", "=", variant.id),
                ("partner_id", "=", connection.supplier_partner_id.id),
            ],
            limit=1,
        )
        if not si:
            flags.append("no_supplierinfo")
        breakdown = connection.compute_sale_price(cost) if cost > 0 else None
        return {
            "eligible": len(reasons) == 0,
            "reasons": reasons,
            "flags": flags,
            "offer": offer,
            "cost": cost,
            "breakdown": breakdown,
        }

    @api.model
    def _template_is_pack_size_multi(self, template):
        """True only when the sole variant-generating attribute is Pack Size with 1:1 PTAV."""
        lines = template.attribute_line_ids
        if len(lines) != 1:
            return False
        if lines.attribute_id.name != "Pack Size":
            return False
        for v in template.product_variant_ids:
            ptavs = v.product_template_attribute_value_ids.filtered(
                lambda p: p.product_tmpl_id == template
            )
            if len(ptavs) != 1:
                return False
        return True

    @api.model
    def _variant_ptav(self, template, variant):
        return variant.product_template_attribute_value_ids.filtered(
            lambda p: p.product_tmpl_id == template
        )[:1]

    @api.model
    def activate_multi_template(self, connection, template, dry_run=False, block_ineligible=True):
        """Activate variant-level selling prices for a multi-variant (Pack Size) template.

        Uses native price_extra: template.list_price = cheapest eligible variant price
        (anchor), each other eligible variant's PTAV.price_extra = variant_price - anchor.
        Ineligible variants are archived (active=False) so they cannot be sold at a
        copied/fallback price. All changes are logged for rollback.
        """
        template.ensure_one()
        connection.ensure_one()
        Log = self.env["vetution.price.change.log"]
        logs = Log

        if template.vetution_sale_price_locked:
            return Log.create({
                "name": f"SKIP locked {template.display_name}",
                "connection_id": connection.id, "product_tmpl_id": template.id,
                "dry_run": dry_run, "skipped": True, "skip_reason": "sale_price_locked",
                "is_multi_variant": True, "change_kind": "template_base",
                "old_list_price": template.list_price,
            })
        if not self._template_is_pack_size_multi(template):
            return Log.create({
                "name": f"SKIP not-pack-size-multi {template.display_name}",
                "connection_id": connection.id, "product_tmpl_id": template.id,
                "dry_run": dry_run, "skipped": True,
                "skip_reason": "not_single_pack_size_attribute",
                "is_multi_variant": True, "change_kind": "template_base",
                "old_list_price": template.list_price,
            })

        variants = template.product_variant_ids
        evals = {v.id: self._variant_eligibility(connection, template, v) for v in variants}
        eligible = [v for v in variants if evals[v.id]["eligible"]]
        ineligible = [v for v in variants if not evals[v.id]["eligible"]]

        if not eligible:
            return Log.create({
                "name": f"SKIP no-eligible-variant {template.display_name}",
                "connection_id": connection.id, "product_tmpl_id": template.id,
                "dry_run": dry_run, "skipped": True, "skip_reason": "no_eligible_variant",
                "is_multi_variant": True, "change_kind": "template_base",
                "old_list_price": template.list_price,
            })

        # Anchor = cheapest eligible selling price (monotonic in cost).
        eligible_sorted = sorted(eligible, key=lambda v: evals[v.id]["breakdown"]["selling_price"])
        anchor = eligible_sorted[0]
        anchor_price = evals[anchor.id]["breakdown"]["selling_price"]
        old_list_price = template.list_price
        allowed, change_reason = self._change_allowed(connection, old_list_price, anchor_price)
        placeholder = float(old_list_price or 0) <= PLACEHOLDER_MAX
        if not allowed:
            return Log.create({
                "name": f"SKIP change-limit {template.display_name}",
                "connection_id": connection.id, "product_tmpl_id": template.id,
                "product_id": anchor.id, "dry_run": dry_run, "skipped": True,
                "skip_reason": change_reason, "is_multi_variant": True,
                "change_kind": "template_base", "old_list_price": old_list_price,
                "new_list_price": anchor_price, "placeholder_replacement": placeholder,
            })

        # 1) Template base (anchor)
        anchor_bd = evals[anchor.id]["breakdown"]
        profit = anchor_price - anchor_bd["supplier_cost"]
        logs |= Log.create({
            "name": f"{'DRY ' if dry_run else ''}BASE {template.display_name} @ {anchor_price}",
            "connection_id": connection.id, "product_tmpl_id": template.id,
            "product_id": anchor.id, "offer_id": evals[anchor.id]["offer"].id,
            "dry_run": dry_run, "skipped": False, "is_multi_variant": True,
            "is_base_anchor": True, "change_kind": "template_base",
            "placeholder_replacement": placeholder,
            "old_list_price": old_list_price, "new_list_price": anchor_price,
            "supplier_cost": anchor_bd["supplier_cost"],
            "markup_price": anchor_bd["markup_price"],
            "minimum_margin_price": anchor_bd["minimum_margin_price"],
            "minimum_profit_price": anchor_bd["minimum_profit_price"],
            "candidate": anchor_bd["candidate"],
            "markup_percent": anchor_bd["markup_percent"],
            "min_margin_percent": anchor_bd["min_margin_percent"],
            "min_profit_amount": anchor_bd["min_profit_amount"],
            "rounding": anchor_bd["rounding"],
            "gross_profit": profit,
            "gross_margin_percent": (profit / anchor_price * 100.0) if anchor_price else 0.0,
            "eligibility_flags": ",".join(evals[anchor.id]["flags"]) or False,
            "note": change_reason,
        })

        if not dry_run:
            template.with_context(vetution_price_activation=True).write({
                "list_price": anchor_price,
                "vetution_price_activated": True,
                "vetution_last_activated_cost": anchor_bd["supplier_cost"],
                "vetution_last_sale_price": anchor_price,
                "vetution_last_price_activation_at": fields.Datetime.now(),
            })
            evals[anchor.id]["offer"].write({"preview_sale_price": anchor_price})

        # 2) Per eligible variant price_extra
        for v in eligible:
            ptav = self._variant_ptav(template, v)
            bd = evals[v.id]["breakdown"]
            v_price = bd["selling_price"]
            new_extra = v_price - anchor_price
            old_extra = ptav.price_extra if ptav else 0.0
            v_profit = v_price - bd["supplier_cost"]
            logs |= Log.create({
                "name": f"{'DRY ' if dry_run else ''}EXTRA {v.display_name} +{new_extra}",
                "connection_id": connection.id, "product_tmpl_id": template.id,
                "product_id": v.id, "offer_id": evals[v.id]["offer"].id,
                "ptav_id": ptav.id if ptav else False,
                "dry_run": dry_run, "skipped": False, "is_multi_variant": True,
                "is_base_anchor": (v.id == anchor.id),
                "change_kind": "variant_extra",
                "old_list_price": anchor_price, "new_list_price": v_price,
                "old_price_extra": old_extra, "new_price_extra": new_extra,
                "supplier_cost": bd["supplier_cost"],
                "markup_price": bd["markup_price"],
                "minimum_margin_price": bd["minimum_margin_price"],
                "minimum_profit_price": bd["minimum_profit_price"],
                "candidate": bd["candidate"],
                "markup_percent": bd["markup_percent"],
                "min_margin_percent": bd["min_margin_percent"],
                "min_profit_amount": bd["min_profit_amount"],
                "rounding": bd["rounding"],
                "gross_profit": v_profit,
                "gross_margin_percent": (v_profit / v_price * 100.0) if v_price else 0.0,
                "eligibility_flags": ",".join(evals[v.id]["flags"]) or False,
            })
            if not dry_run and ptav:
                ptav.write({"price_extra": new_extra})
                v.with_context(vetution_price_activation=True).write({
                    "vetution_variant_price_activated": True,
                    "vetution_variant_price_extra": new_extra,
                    "vetution_variant_sale_price": v_price,
                })

        # 3) Block ineligible variants (archive), recorded for rollback
        for v in ineligible:
            ev = evals[v.id]
            logs |= Log.create({
                "name": f"{'DRY ' if dry_run else ''}BLOCK {v.display_name}",
                "connection_id": connection.id, "product_tmpl_id": template.id,
                "product_id": v.id, "offer_id": ev["offer"].id if ev["offer"] else False,
                "dry_run": dry_run, "skipped": False, "is_multi_variant": True,
                "change_kind": "variant_archived",
                "variant_archived": True, "variant_active_old": v.active,
                "skip_reason": ",".join(ev["reasons"]) or "ineligible",
                "eligibility_flags": ",".join(ev["flags"]) or False,
            })
            if not dry_run and block_ineligible and v.active:
                v.with_context(vetution_price_activation=True).write({
                    "active": False,
                    "vetution_variant_blocked_by_pricing": True,
                })
        return logs

    @api.model
    def select_multi_pilot_templates(self, connection, max_templates=MULTI_PILOT_MAX_TEMPLATES,
                                     max_variants=MULTI_PILOT_MAX_VARIANTS, include_mixed=True,
                                     mixed_target=10):
        """Select ≤30 pack-size multi-variant templates / ≤100 variants for the pilot.

        Reserves up to ``mixed_target`` slots for mixed templates (some variants
        ineligible) so the ineligible-blocking path is exercised on real data, then
        fills the remainder with all-eligible templates. Respects the variant budget.
        """
        connection.ensure_one()
        PT = self.env["product.template"]
        PP = self.env["product.product"]
        vet_tmpls = PT.search([("vetution_id", "!=", False)])
        grp = PP._read_group(
            [("product_tmpl_id", "in", vet_tmpls.ids)],
            groupby=["product_tmpl_id"], aggregates=["__count"],
        )
        multi_ids = [tmpl.id for tmpl, count in grp if count > 1]
        all_eligible = []
        mixed = []
        for tmpl in PT.browse(multi_ids):
            if tmpl.vetution_sale_price_locked:
                continue
            if not self._template_is_pack_size_multi(tmpl):
                continue
            variants = tmpl.product_variant_ids
            evals = [self._variant_eligibility(connection, tmpl, v)["eligible"] for v in variants]
            n_elig = sum(1 for e in evals if e)
            if n_elig == 0:
                continue
            entry = (tmpl, len(variants))
            if n_elig == len(variants):
                all_eligible.append(entry)
            else:
                mixed.append(entry)
        # Fewest variants first to fit more templates in the variant budget.
        all_eligible.sort(key=lambda e: e[1])
        mixed.sort(key=lambda e: e[1])

        chosen = []
        used_variants = 0

        def _try_add(entry):
            nonlocal used_variants
            tmpl, nvar = entry
            if len(chosen) >= max_templates:
                return False
            if used_variants + nvar > max_variants:
                return False
            chosen.append(tmpl)
            used_variants += nvar
            return True

        # Reserve slots for mixed templates first (to exercise blocking).
        if include_mixed:
            added_mixed = 0
            for entry in mixed:
                if added_mixed >= mixed_target or len(chosen) >= max_templates:
                    break
                if _try_add(entry):
                    added_mixed += 1
        # Fill remainder with all-eligible.
        for entry in all_eligible:
            if len(chosen) >= max_templates:
                break
            _try_add(entry)
        # Backfill any remaining budget with more mixed.
        if include_mixed:
            for entry in mixed:
                if len(chosen) >= max_templates:
                    break
                if entry[0] not in chosen:
                    _try_add(entry)
        return PT.browse([t.id for t in chosen]), used_variants

    @api.model
    def activate_multi_pilot(self, connection, templates=None, dry_run=False,
                             max_templates=MULTI_PILOT_MAX_TEMPLATES,
                             max_variants=MULTI_PILOT_MAX_VARIANTS):
        connection.ensure_one()
        self._assert_fresh_and_auth(connection)
        used_variants = None
        if templates is None:
            templates, used_variants = self.select_multi_pilot_templates(
                connection, max_templates=max_templates, max_variants=max_variants,
            )
        if len(templates) > max_templates:
            raise UserError(f"Multi-variant pilot limited to {max_templates} templates.")
        total_variants = sum(len(t.product_variant_ids) for t in templates)
        if total_variants > max_variants:
            raise UserError(
                f"Multi-variant pilot limited to {max_variants} variants (got {total_variants})."
            )
        logs = self.env["vetution.price.change.log"]
        for tmpl in templates:
            logs |= self.activate_multi_template(connection, tmpl, dry_run=dry_run)
        return logs

    @api.model
    def rollback_logs(self, logs):
        """Reverse applied (non-dry, non-skipped) price changes from audit logs.

        Restores template list_price, PTAV price_extra, and un-archives variants.
        """
        logs = logs.filtered(lambda l: not l.dry_run and not l.skipped)
        # Un-archive first so writes on variants succeed.
        for log in logs.filtered("variant_archived"):
            if log.product_id and log.variant_active_old and not log.product_id.active:
                log.product_id.with_context(vetution_price_activation=True).write({
                    "active": True,
                    "vetution_variant_blocked_by_pricing": False,
                })
        for log in logs.filtered(lambda l: l.change_kind == "variant_extra"):
            if log.ptav_id:
                log.ptav_id.write({"price_extra": log.old_price_extra})
            if log.product_id:
                log.product_id.with_context(vetution_price_activation=True).write({
                    "vetution_variant_price_activated": False,
                    "vetution_variant_price_extra": 0.0,
                    "vetution_variant_sale_price": 0.0,
                })
        for log in logs.filtered(lambda l: l.change_kind in ("template_base", "template_single")):
            if log.product_tmpl_id:
                log.product_tmpl_id.with_context(vetution_price_activation=True).write({
                    "list_price": log.old_list_price,
                    "vetution_price_activated": False,
                    "vetution_last_activated_cost": 0.0,
                    "vetution_last_sale_price": 0.0,
                    "vetution_last_price_activation_at": False,
                })
        return True
