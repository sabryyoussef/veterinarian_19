# -*- coding: utf-8 -*-
"""Shadow availability + suggested-price assessment (Phase 15A — no commercial side effects)."""

from __future__ import annotations

import logging
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

CIRCUIT_PARAM = "petspot_fulfillment_vetution.refresh_fail_count"
CIRCUIT_OPEN_UNTIL = "petspot_fulfillment_vetution.circuit_open_until"


class PetspotVetutionShadowAssessment(models.Model):
    _name = "petspot.vetution.shadow.assessment"
    _description = "Vetution Shadow Assessment"
    _inherit = ["mail.thread"]
    _order = "id desc"

    name = fields.Char(required=True, default="Assessment")
    active = fields.Boolean(default=True)
    inquiry_id = fields.Many2one(
        "petspot.availability.inquiry",
        required=True,
        ondelete="cascade",
        index=True,
        tracking=True,
    )
    case_id = fields.Many2one(
        "petspot.fulfillment.case",
        related="inquiry_id.case_id",
        store=True,
        index=True,
    )
    product_id = fields.Many2one("product.product", index=True)
    snapshot_id = fields.Many2one(
        "petspot.vetution.supplier.snapshot", ondelete="restrict", index=True
    )
    policy_id = fields.Many2one("petspot.vetution.landed.cost.policy")
    policy_version = fields.Char()

    landed_cost_incomplete = fields.Boolean(default=False)
    missing_cost_components = fields.Char()
    component_supplier_cost = fields.Float()
    component_delivery = fields.Float()
    component_payment_fee = fields.Float()
    component_packaging = fields.Float()
    component_nonrecoverable_tax = fields.Float()
    component_risk_allowance = fields.Float()
    sell_formula = fields.Char()
    landed_formula = fields.Char()
    price_review_required = fields.Boolean(default=False)
    on_automation_allowlist = fields.Boolean(default=False)
    availability_wording = fields.Char()
    gate_block_auto_quotation = fields.Boolean()
    gate_block_odoo_price_update = fields.Boolean()
    gate_block_shopify_publish = fields.Boolean()
    gate_block_supplier_purchase = fields.Boolean()
    eligible_future_automation = fields.Boolean()
    quotation_validity_hours = fields.Float()

    state = fields.Selection(
        [
            ("ok", "Actionable suggestion"),
            ("review", "Mapping / policy review"),
            ("stale", "Stale"),
            ("unavailable", "Unavailable"),
            ("blocked", "Blocked by guards"),
            ("sync_failed", "Sync failed"),
        ],
        required=True,
        default="review",
        tracking=True,
        index=True,
    )
    resolution_method = fields.Selection(
        [
            ("vetution_size_id", "Odoo vetution_size_id"),
            ("configured_mapping", "Confirmed mapping review"),
            ("barcode", "Unique barcode / vendor code"),
            ("missing", "Missing"),
            ("ambiguous", "Ambiguous"),
        ],
        default="missing",
    )
    resolution_confidence = fields.Selection(
        [
            ("exact", "Exact"),
            ("configured", "Configured"),
            ("barcode", "Barcode"),
            ("ambiguous", "Ambiguous"),
            ("missing", "Missing"),
        ],
        default="missing",
    )
    vetution_drug_id = fields.Integer()
    vetution_size_id = fields.Integer()
    drug_slug = fields.Char()

    availability_normalized = fields.Selection(
        related="snapshot_id.availability_normalized", store=True
    )
    source_sync_at = fields.Datetime(related="snapshot_id.source_sync_at", store=True)
    assessed_at = fields.Datetime(required=True, default=fields.Datetime.now)
    data_age_hours = fields.Float()
    is_fresh = fields.Boolean()

    supplier_cost = fields.Float()
    landed_cost = fields.Float()
    suggested_price = fields.Float()
    current_odoo_price = fields.Float()
    current_shopify_price = fields.Float()
    price_delta_amount = fields.Float()
    price_delta_percent = fields.Float()
    expected_gross_profit = fields.Float()
    expected_gross_margin_percent = fields.Float()
    eta_days = fields.Integer()
    payload_hash = fields.Char(index=True)
    blockers = fields.Text()
    recommended_next_action = fields.Char()
    mapping_review_id = fields.Many2one("petspot.vetution.mapping.review")
    refresh_attempted = fields.Boolean()
    refresh_succeeded = fields.Boolean()
    note = fields.Text()
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company
    )

    # ------------------------------------------------------------------ resolve
    @api.model
    def _resolve_mapping(self, inquiry):
        """Return dict: product, offer, method, confidence, review_reason|False."""
        product = inquiry.product_id
        if not product:
            return {
                "product": False,
                "offer": False,
                "method": "missing",
                "confidence": "missing",
                "review_reason": "missing_size_id",
                "note": "Inquiry has no Odoo product.",
            }

        Offer = self.env["vetution.supplier.offer"]
        MappingReview = self.env["petspot.vetution.mapping.review"]

        # 1) Exact vetution_size_id on variant
        size_id = product.vetution_size_id
        if size_id:
            offers = Offer.search(
                [
                    ("offer_type", "=", "vetution"),
                    ("vetution_size_id", "=", size_id),
                ]
            )
            if len(offers) > 1:
                # Prefer offer already linked to this product
                linked = offers.filtered(lambda o: o.product_id == product)
                if len(linked) == 1:
                    offers = linked
                else:
                    return {
                        "product": product,
                        "offer": False,
                        "method": "ambiguous",
                        "confidence": "ambiguous",
                        "review_reason": "ambiguous",
                        "note": f"Multiple primary offers for size {size_id}.",
                    }
            if len(offers) == 1:
                offer = offers
                if offer.product_id and offer.product_id != product:
                    return {
                        "product": product,
                        "offer": False,
                        "method": "ambiguous",
                        "confidence": "ambiguous",
                        "review_reason": "pack_mismatch",
                        "note": "Offer linked to a different Odoo product.",
                    }
                return {
                    "product": product,
                    "offer": offer,
                    "method": "vetution_size_id",
                    "confidence": "exact",
                    "review_reason": False,
                    "note": False,
                }
            # size set but no offer
            return {
                "product": product,
                "offer": False,
                "method": "missing",
                "confidence": "missing",
                "review_reason": "inactive_offer",
                "note": f"No Vetution offer for size {size_id}.",
            }

        # 2) Confirmed configured mapping review (already applied size — covered above)
        #    Pending configured proposal does not auto-resolve.
        confirmed = MappingReview.search(
            [
                ("product_id", "=", product.id),
                ("state", "=", "confirmed"),
            ],
            order="confirmed_at desc, id desc",
            limit=1,
        )
        if confirmed and confirmed.proposed_vetution_size_id:
            # If product still lacks size, treat as needs re-apply
            return {
                "product": product,
                "offer": False,
                "method": "configured_mapping",
                "confidence": "configured",
                "review_reason": "missing_size_id",
                "note": "Confirmed mapping exists but product.vetution_size_id is empty — re-apply.",
            }

        # 3) Unique barcode → unique offer/product with that barcode and size
        if product.barcode:
            twins = self.env["product.product"].search(
                [("barcode", "=", product.barcode), ("vetution_size_id", "!=", False)]
            )
            if len(twins) == 1 and twins.id != product.id:
                # Do not silently steal another product's mapping
                pass
            elif len(twins) == 1 and twins == product:
                pass  # already handled by size path
            elif product.barcode:
                offers_by_code = Offer.search(
                    [
                        ("offer_type", "=", "vetution"),
                        ("product_id.barcode", "=", product.barcode),
                    ]
                )
                if len(offers_by_code) == 1 and offers_by_code.vetution_size_id:
                    return {
                        "product": product,
                        "offer": offers_by_code,
                        "method": "barcode",
                        "confidence": "barcode",
                        "review_reason": False,
                        "note": "Resolved via unique barcode → offer.",
                    }
                if len(offers_by_code) > 1:
                    return {
                        "product": product,
                        "offer": False,
                        "method": "ambiguous",
                        "confidence": "ambiguous",
                        "review_reason": "ambiguous",
                        "note": "Multiple offers share this barcode.",
                    }

        # Never title match
        tmpl = product.product_tmpl_id
        vet_id = getattr(tmpl, "vetution_id", False) or False
        note = "Missing vetution_size_id."
        if vet_id:
            note += f" Template has vetution_id={vet_id} but size is unresolved."
        return {
            "product": product,
            "offer": False,
            "method": "missing",
            "confidence": "missing",
            "review_reason": "missing_size_id" if not vet_id else "missing_size_id",
            "note": note,
        }

    # ------------------------------------------------------------------ freshness / refresh
    @api.model
    def _circuit_is_open(self, policy):
        ICP = self.env["ir.config_parameter"].sudo()
        until = ICP.get_param(CIRCUIT_OPEN_UNTIL)
        if not until:
            return False
        try:
            dt = fields.Datetime.to_datetime(until)
        except Exception:  # noqa: BLE001
            return False
        return bool(dt and dt > fields.Datetime.now())

    @api.model
    def _circuit_record_failure(self, policy):
        ICP = self.env["ir.config_parameter"].sudo()
        count = int(ICP.get_param(CIRCUIT_PARAM) or 0) + 1
        ICP.set_param(CIRCUIT_PARAM, str(count))
        threshold = policy.circuit_breaker_failures or 5
        if count >= threshold:
            open_until = fields.Datetime.now() + timedelta(
                minutes=policy.circuit_breaker_cooldown_minutes or 30
            )
            ICP.set_param(CIRCUIT_OPEN_UNTIL, fields.Datetime.to_string(open_until))
            _logger.warning(
                "Vetution refresh circuit open until %s after %s failures",
                open_until,
                count,
            )

    @api.model
    def _circuit_record_success(self):
        ICP = self.env["ir.config_parameter"].sudo()
        ICP.set_param(CIRCUIT_PARAM, "0")
        ICP.set_param(CIRCUIT_OPEN_UNTIL, "")

    def _offer_age_hours(self, offer, connection):
        """Age from this offer's own sync markers only (not global sync logs)."""
        ts = offer.last_commercial_sync_at or offer.last_seen_at
        if not ts:
            return 9999.0
        age = fields.Datetime.now() - ts
        return age.total_seconds() / 3600.0

    def _maybe_refresh_offer(self, inquiry, offer, policy, connection):
        """Optional rate-limited slug refresh. Returns (offer, attempted, succeeded, error)."""
        if not policy.allow_on_demand_refresh:
            return offer, False, False, "refresh_disabled"
        if self._circuit_is_open(policy):
            return offer, False, False, "circuit_open"
        slug = offer.drug_slug or False
        if not slug:
            tmpl = inquiry.product_id.product_tmpl_id if inquiry.product_id else False
            slug = getattr(tmpl, "vetution_slug", False) or False
        if not slug:
            return offer, False, False, "no_slug"

        Lock = self.env["petspot.vetution.refresh.lock"]
        acquired, lock = Lock.try_acquire(
            connection,
            slug,
            inquiry=inquiry,
            lock_seconds=policy.refresh_lock_seconds or 120,
        )
        if not acquired:
            return offer, True, False, "refresh_locked_by_peer"

        Sync = self.env["vetution.commercial.sync"]
        last_err = False
        success = False
        retries = max(int(policy.refresh_max_retries or 1), 1)
        for attempt in range(retries):
            try:
                Sync.sync_slugs(connection, [slug], sync_type="selected", dry_run=False)
                success = True
                self._circuit_record_success()
                break
            except Exception as err:  # noqa: BLE001
                last_err = str(err)[:200]
                _logger.warning(
                    "Vetution on-demand refresh attempt %s failed for %s: %s",
                    attempt + 1,
                    slug,
                    last_err,
                )
        lock.release(success=success, error=last_err)
        if not success:
            self._circuit_record_failure(policy)
            return offer, True, False, last_err or "refresh_failed"

        # Reload offer
        size_id = offer.vetution_size_id or inquiry.product_id.vetution_size_id
        fresh = self.env["vetution.supplier.offer"].search(
            [
                ("offer_type", "=", "vetution"),
                ("vetution_size_id", "=", size_id),
            ],
            limit=1,
        )
        return (fresh or offer), True, True, False

    # ------------------------------------------------------------------ shopify price (read-only)
    @api.model
    def _read_shopify_price(self, product):
        if not product:
            return 0.0
        # Prefer mapped shopify sync check / lst_price — never write
        if "shopify.variant.map" in self.env:
            mapping = self.env["shopify.variant.map"].sudo().search(
                [("product_id", "=", product.id)], limit=1
            )
            if mapping and hasattr(mapping, "shopify_price") and mapping.shopify_price:
                return float(mapping.shopify_price)
        # Fallback: Odoo sales price is what connector would export
        return float(product.lst_price or product.list_price or 0.0)

    # ------------------------------------------------------------------ assess
    @api.model
    def assess_inquiry(self, inquiry, force_refresh=False):
        """Create or update active shadow assessment. Never creates SO/RFQ/messages."""
        inquiry.ensure_one()
        policy = self.env["petspot.vetution.landed.cost.policy"].get_active_policy(
            inquiry.company_id
        )
        if policy.allow_price_publish or policy.allow_auto_quotation or policy.allow_customer_message:
            raise UserError(
                "Phase 15A policy flags must keep publish/quote/message disabled."
            )

        connection = self.env["vetution.connection"].sudo().search(
            [("active", "=", True)], limit=1
        )
        if not connection:
            raise UserError("No active Vetution connection on this database.")

        resolved = self._resolve_mapping(inquiry)
        product = resolved["product"]
        offer = resolved["offer"]
        assessed_at = fields.Datetime.now()

        # Mapping failure path
        if not offer:
            review = False
            if product and resolved.get("review_reason"):
                review = self.env["petspot.vetution.mapping.review"].ensure_pending(
                    product,
                    resolved["review_reason"],
                    inquiry=inquiry,
                    shopify_variant_id=inquiry.shopify_variant_id,
                    note=resolved.get("note"),
                )
            vals = {
                "name": f"ASS/{inquiry.name}",
                "inquiry_id": inquiry.id,
                "product_id": product.id if product else False,
                "policy_id": policy.id,
                "policy_version": policy.version,
                "state": "review",
                "resolution_method": resolved["method"],
                "resolution_confidence": resolved["confidence"],
                "assessed_at": assessed_at,
                "blockers": "mapping_review_required",
                "recommended_next_action": "open_mapping_review",
                "mapping_review_id": review.id if review else False,
                "note": resolved.get("note") or False,
                "company_id": inquiry.company_id.id,
                "current_odoo_price": float(
                    (product.list_price if product else 0.0) or 0.0
                ),
                "current_shopify_price": self._read_shopify_price(product) if product else 0.0,
            }
            return self._upsert_assessment(inquiry, vals, snapshot_vals=False)

        refresh_attempted = False
        refresh_succeeded = False
        age = self._offer_age_hours(offer, connection)
        stale_limit = policy.stale_after_hours_shadow or 12.0
        is_fresh = age <= stale_limit and not offer.is_stale

        if (not is_fresh) or force_refresh:
            offer, refresh_attempted, refresh_succeeded, refresh_err = self._maybe_refresh_offer(
                inquiry, offer, policy, connection
            )
            age = self._offer_age_hours(offer, connection)
            is_fresh = age <= stale_limit and not offer.is_stale
            if refresh_attempted and not refresh_succeeded and not is_fresh:
                snap_vals = self.env["petspot.vetution.supplier.snapshot"].build_from_offer(
                    offer,
                    resolution_confidence=resolved["confidence"],
                    inquiry=inquiry,
                    assessed_at=assessed_at,
                )
                # Force stale/sync_failed normalization
                snap_vals["availability_normalized"] = (
                    "sync_failed" if refresh_err else "stale"
                )
                vals = self._price_vals(
                    inquiry, product, offer, policy, snap_vals, resolved, assessed_at, age, False
                )
                vals.update(
                    {
                        "state": "sync_failed" if refresh_err else "stale",
                        "blockers": (vals.get("blockers") or "")
                        + ("|stale_data" if not refresh_err else f"|refresh_failed:{refresh_err}"),
                        "recommended_next_action": "manual_review",
                        "refresh_attempted": refresh_attempted,
                        "refresh_succeeded": refresh_succeeded,
                    }
                )
                return self._upsert_assessment(inquiry, vals, snapshot_vals=snap_vals)

        snap_vals = self.env["petspot.vetution.supplier.snapshot"].build_from_offer(
            offer,
            resolution_confidence=resolved["confidence"],
            inquiry=inquiry,
            assessed_at=assessed_at,
        )
        if not is_fresh:
            snap_vals["availability_normalized"] = "stale"

        vals = self._price_vals(
            inquiry, product, offer, policy, snap_vals, resolved, assessed_at, age, is_fresh
        )
        vals.update(
            {
                "refresh_attempted": refresh_attempted,
                "refresh_succeeded": refresh_succeeded,
            }
        )
        return self._upsert_assessment(inquiry, vals, snapshot_vals=snap_vals)

    @api.model
    def _price_vals(
        self, inquiry, product, offer, policy, snap_vals, resolved, assessed_at, age, is_fresh
    ):
        supplier_cost = float(snap_vals.get("purchase_price") or 0.0)
        landed_br = policy.compute_landed_cost(supplier_cost)
        sale_br = policy.compute_suggested_sale_price(
            landed_br["landed_cost"] if not landed_br["landed_cost_incomplete"] else 0.0
        )
        # Still compute a worksheet price from known supplier+verified components only
        # when incomplete: use partial landed for display but mark incomplete/block gates.
        if landed_br["landed_cost_incomplete"]:
            sale_br = policy.compute_suggested_sale_price(landed_br["landed_cost"])

        odoo_price = float(product.list_price or 0.0)
        shopify_price = self._read_shopify_price(product)
        locked = bool(getattr(product.product_tmpl_id, "vetution_sale_price_locked", False))
        ok, blockers, metrics = policy.evaluate_price_guards(
            suggested_price=sale_br["suggested_price"],
            landed_cost=landed_br["landed_cost"],
            current_odoo_price=odoo_price,
            price_locked=locked,
            landed_cost_incomplete=landed_br["landed_cost_incomplete"],
            data_age_hours=age,
            for_auto_quote=False,
        )
        gates = metrics["gates"]
        avail = snap_vals.get("availability_normalized") or "unknown"
        if not is_fresh:
            blockers = list(blockers) + ["stale_data"]
            ok = False
            avail = "stale"
            snap_vals["availability_normalized"] = "stale"

        on_allowlist = self.env["petspot.vetution.automation.allowlist"].is_product_allowed(
            product
        )
        if not on_allowlist:
            blockers = list(blockers) + ["not_on_automation_allowlist"]
            gates["eligible_future_automation"] = False

        if avail in ("out_of_stock",):
            state = "unavailable"
            next_action = "inform_unavailable_manual"
        elif avail in ("stale",):
            state = "stale"
            next_action = "refresh_or_review"
        elif avail in ("sync_failed",):
            state = "sync_failed"
            next_action = "manual_review"
        elif avail in ("unknown",):
            state = "review"
            next_action = "manual_review"
            blockers = list(blockers) + ["availability_unknown"]
            ok = False
        elif landed_br["landed_cost_incomplete"]:
            state = "blocked"
            next_action = "complete_landed_cost_inputs"
        elif gates.get("price_review_required"):
            state = "blocked"
            next_action = "price_review_required"
        elif not ok:
            state = "blocked"
            next_action = "policy_review"
        else:
            state = "ok"
            next_action = "shadow_only_no_quote"

        if offer.is_expired or snap_vals.get("offer_is_expired"):
            state = "unavailable"
            blockers = list(blockers) + ["offer_expired"]
            next_action = "inform_unavailable_manual"

        wording = False
        if avail in ("confirmed_available", "limited_stock") and state in ("ok", "blocked"):
            wording = policy.availability_wording

        eta = (
            policy.supplier_lead_time_days
            if state == "ok" and avail in ("confirmed_available", "limited_stock")
            else 0
        )

        return {
            "name": f"ASS/{inquiry.name}",
            "inquiry_id": inquiry.id,
            "product_id": product.id,
            "policy_id": policy.id,
            "policy_version": policy.version,
            "state": state,
            "resolution_method": resolved["method"],
            "resolution_confidence": resolved["confidence"],
            "vetution_drug_id": snap_vals.get("vetution_drug_id") or False,
            "vetution_size_id": snap_vals.get("vetution_size_id") or False,
            "drug_slug": snap_vals.get("drug_slug") or False,
            "assessed_at": assessed_at,
            "data_age_hours": age,
            "is_fresh": is_fresh,
            "supplier_cost": landed_br["supplier_cost"],
            "landed_cost": landed_br["landed_cost"],
            "landed_cost_incomplete": landed_br["landed_cost_incomplete"],
            "missing_cost_components": ",".join(landed_br["missing_components"]) or False,
            "component_supplier_cost": landed_br["supplier_cost"],
            "component_delivery": landed_br["supplier_delivery_allocation"],
            "component_payment_fee": landed_br["payment_fee"],
            "component_packaging": landed_br["packaging_handling"],
            "component_nonrecoverable_tax": landed_br["non_recoverable_tax"],
            "component_risk_allowance": landed_br["risk_return_allowance"],
            "landed_formula": landed_br["formula"],
            "sell_formula": sale_br.get("sell_formula") or False,
            "suggested_price": sale_br["suggested_price"],
            "current_odoo_price": odoo_price,
            "current_shopify_price": shopify_price,
            "price_delta_amount": metrics["price_delta_amount"],
            "price_delta_percent": metrics["price_delta_percent"],
            "expected_gross_profit": metrics["expected_gross_profit"],
            "expected_gross_margin_percent": metrics["expected_gross_margin_percent"],
            "eta_days": eta,
            "payload_hash": snap_vals.get("payload_hash"),
            "blockers": "|".join(dict.fromkeys(blockers)) if blockers else False,
            "recommended_next_action": next_action,
            "price_review_required": bool(gates.get("price_review_required")),
            "on_automation_allowlist": on_allowlist,
            "availability_wording": wording,
            "gate_block_auto_quotation": True,
            "gate_block_odoo_price_update": True,
            "gate_block_shopify_publish": True,
            "gate_block_supplier_purchase": True,
            "eligible_future_automation": bool(gates.get("eligible_future_automation")),
            "quotation_validity_hours": policy.quotation_validity_hours,
            "company_id": inquiry.company_id.id,
            "note": (
                "Website/API stock is a snapshot only — not a reservation. "
                "Availability wording does not promise delivery. "
                "Phase 15A does not quote, message, or publish prices."
            ),
        }

    @api.model
    def _upsert_assessment(self, inquiry, vals, snapshot_vals=False):
        """Idempotent: same inquiry + unchanged payload_hash updates active row."""
        active = self.search(
            [("inquiry_id", "=", inquiry.id), ("active", "=", True)],
            order="id desc",
            limit=1,
        )
        new_hash = (snapshot_vals or {}).get("payload_hash") or vals.get("payload_hash")

        if active and new_hash and active.payload_hash == new_hash:
            # unchanged commercial snapshot — refresh assessment metadata only
            meta = {
                k: vals[k]
                for k in (
                    "assessed_at",
                    "data_age_hours",
                    "is_fresh",
                    "current_odoo_price",
                    "current_shopify_price",
                    "price_delta_amount",
                    "price_delta_percent",
                    "expected_gross_profit",
                    "expected_gross_margin_percent",
                    "blockers",
                    "recommended_next_action",
                    "state",
                    "refresh_attempted",
                    "refresh_succeeded",
                    "policy_version",
                    "note",
                    "landed_cost_incomplete",
                    "missing_cost_components",
                    "suggested_price",
                    "landed_cost",
                    "supplier_cost",
                    "price_review_required",
                    "on_automation_allowlist",
                    "availability_wording",
                    "eligible_future_automation",
                    "component_supplier_cost",
                    "component_delivery",
                    "component_payment_fee",
                    "component_packaging",
                    "component_nonrecoverable_tax",
                    "component_risk_allowance",
                    "sell_formula",
                    "landed_formula",
                )
                if k in vals
            }
            active.write(meta)
            inquiry.write(
                {
                    "vetution_assessment_id": active.id,
                    "vetution_assessment_state": active.state,
                }
            )
            return active

        if active:
            # Keep history: archive previous when source changed
            active.write({"active": False})

        snap = False
        if snapshot_vals:
            snap = self.env["petspot.vetution.supplier.snapshot"].create(snapshot_vals)
            vals["snapshot_id"] = snap.id
            vals["payload_hash"] = snapshot_vals.get("payload_hash")

        assessment = self.create(vals)
        if snap:
            snap.write({"assessment_id": assessment.id})
        inquiry.write(
            {
                "vetution_assessment_id": assessment.id,
                "vetution_assessment_state": assessment.state,
                "vetution_size_id_resolved": assessment.vetution_size_id,
                "vetution_resolution_method": assessment.resolution_method,
            }
        )
        return assessment
