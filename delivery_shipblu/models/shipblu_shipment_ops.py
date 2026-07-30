# -*- coding: utf-8 -*-
"""Operational fields on shipblu.shipment (cost, package, SLA, readiness)."""

import json
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from odoo.addons.delivery_shipblu.services import cutoff_service
from odoo.addons.petspot_shipblu_base.services.cost_engine import CostEngine


class ShipBluShipmentOps(models.Model):
    _inherit = "shipblu.shipment"

    package_count = fields.Integer(default=1)
    total_weight_kg = fields.Float(string="Total Weight (kg)", digits=(16, 3))
    package_size_id = fields.Many2one("shipblu.package.size", string="Package Size")
    package_size_shipblu_id = fields.Integer(
        string="ShipBlu Package Size ID",
        help="Resolved official ID; required for live create.",
    )
    fragile = fields.Boolean(default=False)
    fragile_api_supported = fields.Boolean(
        default=False,
        help="Fragile is local-only unless official API schema supports it.",
    )
    inspection_requested = fields.Boolean(default=False)
    inspection_instructions = fields.Text()
    inspection_fee = fields.Float(digits=(16, 2))
    inspection_transmitted = fields.Boolean(
        default=False,
        help="False = local-only / manual handling.",
    )
    inspection_outcome = fields.Char()
    try_and_buy_requested = fields.Boolean(default=False)
    try_and_buy_eligible = fields.Boolean(compute="_compute_try_and_buy", store=True)
    try_and_buy_eligibility_reason = fields.Char(compute="_compute_try_and_buy", store=True)
    try_and_buy_fee = fields.Float(digits=(16, 2))
    try_and_buy_transmitted = fields.Boolean(
        default=False,
        help="Try & Buy not confirmed in official create schema — local/manual by default.",
    )
    source_platform = fields.Selection(
        [
            ("shopify", "Shopify"),
            ("odoo", "Odoo"),
            ("other", "Other"),
        ],
        compute="_compute_source_platform",
        store=True,
    )
    return_collection_amount = fields.Float(digits=(16, 2))
    shopify_origin = fields.Boolean(
        compute="_compute_source_platform",
        store=True,
        string="Shopify Origin",
    )

    weight_override = fields.Boolean(default=False)
    weight_override_reason = fields.Char()
    weight_override_user_id = fields.Many2one("res.users", readonly=True)
    weight_override_at = fields.Datetime(readonly=True)

    # Cost breakdown (estimate only — never posts accounting)
    cost_base_fee = fields.Float(digits=(16, 2))
    cost_size_surcharge = fields.Float(digits=(16, 2))
    cost_cod_fee = fields.Float(digits=(16, 2))
    cost_try_and_buy_fee = fields.Float(digits=(16, 2))
    cost_inspection_fee = fields.Float(digits=(16, 2))
    cost_return_fee = fields.Float(digits=(16, 2))
    cost_pickup_surcharge = fields.Float(digits=(16, 2))
    cost_discount = fields.Float(digits=(16, 2))
    cost_tax = fields.Float(digits=(16, 2))
    cost_total = fields.Float(digits=(16, 2))
    cost_currency = fields.Char(default="EGP")
    cost_status = fields.Selection(
        [("estimated", "Estimated"), ("confirmed", "Confirmed")],
        default="estimated",
    )
    cost_pricing_source = fields.Char()
    cost_breakdown_json = fields.Text()
    cost_notes = fields.Text()

    # Cutoffs
    pickup_cutoff_passed = fields.Boolean(compute="_compute_cutoffs")
    eligible_pickup_date = fields.Date(compute="_compute_cutoffs")
    same_day_pickup_possible = fields.Boolean(compute="_compute_cutoffs")
    flyer_cutoff_passed = fields.Boolean(compute="_compute_cutoffs")
    pickup_warning = fields.Char(compute="_compute_cutoffs")

    # Coverage / SLA
    coverage_status = fields.Selection(
        [
            ("unknown", "Unknown"),
            ("covered", "Covered"),
            ("unmapped", "Unmapped"),
            ("inactive", "Inactive"),
        ],
        default="unknown",
    )
    destination_region = fields.Char()
    sla_rule_id = fields.Many2one("shipblu.sla.rule")
    eta_start = fields.Date(string="Estimated Delivery Start")
    eta_end = fields.Date(string="Estimated Delivery End")
    sla_overdue = fields.Boolean(compute="_compute_sla_overdue", store=True)
    sla_delay_days = fields.Integer(compute="_compute_sla_overdue", store=True)

    # Label / QR / readiness
    label_status = fields.Selection(
        [
            ("none", "None"),
            ("available", "Available"),
            ("downloaded", "Downloaded"),
            ("error", "Error"),
        ],
        default="none",
    )
    label_ready = fields.Boolean(compute="_compute_readiness", store=True)
    label_print_status = fields.Selection(
        [
            ("unprinted", "Unprinted"),
            ("printed", "Printed"),
        ],
        default="unprinted",
    )
    qr_present = fields.Boolean(
        default=False,
        help="Only set when confirmed via API event or manual action.",
    )
    courier_scan_status = fields.Selection(
        [
            ("unknown", "Unknown"),
            ("not_scanned", "Not scanned"),
            ("scanned", "Scanned"),
        ],
        default="unknown",
    )
    ready_for_pickup = fields.Boolean(compute="_compute_readiness", store=True)
    ops_warnings = fields.Text(compute="_compute_ops_warnings")

    # Return / settlement links (lightweight)
    return_status = fields.Selection(
        [
            ("none", "None"),
            ("customer_refused", "Customer refused"),
            ("return_requested", "Return requested"),
            ("return_in_transit", "Return in transit"),
            ("return_delivered", "Return delivered"),
            ("return_received", "Return received"),
            ("return_closed", "Return closed"),
        ],
        default="none",
        tracking=True,
    )
    settlement_status = fields.Selection(
        [
            ("none", "None"),
            ("awaiting", "Awaiting settlement"),
            ("included", "Included in settlement"),
            ("settled", "Settled"),
        ],
        default="none",
    )

    @api.depends("creation_source", "shopify_order_id", "shopify_order_ref", "shipment_owner")
    def _compute_source_platform(self):
        for rec in self:
            shopify = bool(
                rec.creation_source == "shopify"
                or rec.shopify_order_id
                or rec.shopify_order_ref
                or rec.shipment_owner == "legacy_shopify"
            )
            rec.shopify_origin = shopify
            if shopify:
                rec.source_platform = "shopify"
            elif rec.creation_source == "odoo":
                rec.source_platform = "odoo"
            else:
                rec.source_platform = "other"

    @api.depends(
        "try_and_buy_requested",
        "shopify_origin",
        "backend_id",
        "backend_id.try_and_buy_shopify_only",
        "backend_id.try_and_buy_allow_non_shopify",
    )
    def _compute_try_and_buy(self):
        for rec in self:
            backend = rec.backend_id
            if not rec.try_and_buy_requested:
                rec.try_and_buy_eligible = False
                rec.try_and_buy_eligibility_reason = False
                continue
            if not backend:
                rec.try_and_buy_eligible = False
                rec.try_and_buy_eligibility_reason = "No backend"
                continue
            if backend.try_and_buy_shopify_only and not rec.shopify_origin:
                if backend.try_and_buy_allow_non_shopify:
                    rec.try_and_buy_eligible = True
                    rec.try_and_buy_eligibility_reason = "Allowed by non-Shopify override"
                else:
                    rec.try_and_buy_eligible = False
                    rec.try_and_buy_eligibility_reason = "Try & Buy is Shopify-only"
            else:
                rec.try_and_buy_eligible = True
                rec.try_and_buy_eligibility_reason = "Eligible"

    @api.depends("backend_id")
    def _compute_cutoffs(self):
        for rec in self:
            if not rec.backend_id:
                rec.pickup_cutoff_passed = False
                rec.eligible_pickup_date = False
                rec.same_day_pickup_possible = False
                rec.flyer_cutoff_passed = False
                rec.pickup_warning = False
                continue
            info = cutoff_service.pickup_cutoff_info(rec.backend_id)
            flyer = cutoff_service.flyer_cutoff_info(rec.backend_id)
            rec.pickup_cutoff_passed = info["pickup_cutoff_passed"]
            rec.eligible_pickup_date = info["eligible_pickup_date"]
            rec.same_day_pickup_possible = info["same_day_pickup_possible"]
            rec.flyer_cutoff_passed = flyer["flyer_cutoff_passed"]
            rec.pickup_warning = cutoff_service.pickup_warning_text(rec.backend_id)

    @api.depends("eta_end", "normalized_status", "state")
    def _compute_sla_overdue(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if not rec.eta_end or rec.state in ("done", "cancelled") or rec.normalized_status in (
                "delivered",
                "cancelled",
                "returned",
            ):
                rec.sla_overdue = False
                rec.sla_delay_days = 0
                continue
            if today > rec.eta_end:
                rec.sla_overdue = True
                rec.sla_delay_days = (today - rec.eta_end).days
            else:
                rec.sla_overdue = False
                rec.sla_delay_days = 0

    @api.depends(
        "shipblu_order_id",
        "label_attachment_id",
        "label_status",
        "package_count",
        "package_size_shipblu_id",
        "total_weight_kg",
        "cod_amount",
        "coverage_status",
        "backend_id",
    )
    def _compute_readiness(self):
        for rec in self:
            rec.label_ready = bool(
                rec.label_attachment_id or rec.label_status in ("available", "downloaded")
            )
            weight_ok = True
            if rec.backend_id and rec.backend_id.enable_package_weight_blocking:
                max_w = float(rec.backend_id.max_shipment_weight_kg or 10.0)
                weight_ok = float(rec.total_weight_kg or 0.0) <= max_w or rec.weight_override
            coverage_ok = True
            if rec.backend_id and rec.backend_id.enable_coverage_blocking:
                coverage_ok = rec.coverage_status == "covered"
            rec.ready_for_pickup = bool(
                rec.shipblu_order_id
                and rec.label_ready
                and int(rec.package_count or 0) >= 1
                and rec.package_size_shipblu_id
                and weight_ok
                and coverage_ok
            )

    @api.depends(
        "fragile",
        "inspection_requested",
        "try_and_buy_requested",
        "try_and_buy_eligible",
        "try_and_buy_eligibility_reason",
        "try_and_buy_transmitted",
        "cod_amount",
        "cost_total",
        "pickup_warning",
        "package_size_shipblu_id",
        "backend_id",
    )
    def _compute_ops_warnings(self):
        for rec in self:
            warns = []
            if rec.fragile:
                warns.append("Fragile: use extra packing and mark label clearly.")
            if rec.inspection_requested:
                warns.append(
                    "Inspection requested — merchant remains responsible for product inspection "
                    "and measurement instructions."
                )
            if rec.try_and_buy_requested and not rec.try_and_buy_eligible:
                warns.append(rec.try_and_buy_eligibility_reason or "Try & Buy not eligible")
            if rec.try_and_buy_requested and not rec.try_and_buy_transmitted:
                warns.append("Try & Buy is local-only (not transmitted to ShipBlu API).")
            if rec.cod_amount == 0 and rec.backend_id and rec.backend_id.enable_wallet_validation:
                bal = rec.backend_id.effective_wallet_balance()
                est = float(rec.cost_total or 0.0)
                if est and bal < est:
                    warns.append(
                        f"Zero-COD wallet risk: balance {bal:.2f} < estimated fees {est:.2f}."
                    )
            if rec.pickup_warning:
                warns.append(rec.pickup_warning)
            if not rec.package_size_shipblu_id:
                warns.append("Package size ID unresolved — live create blocked.")
            rec.ops_warnings = "\n".join(warns) if warns else False

    @api.constrains("package_count")
    def _check_package_count(self):
        for rec in self:
            if rec.package_count is not None and rec.package_count < 1:
                raise ValidationError(_("Package count must be at least 1."))

    def action_apply_weight_override(self):
        self.ensure_one()
        if not self.env.user.has_group("petspot_shipblu_base.group_shipblu_ops"):
            raise UserError(_("Only Operations Manager may override weight limits."))
        if not self.weight_override_reason:
            raise UserError(_("Provide a weight override reason."))
        self.write(
            {
                "weight_override": True,
                "weight_override_user_id": self.env.user.id,
                "weight_override_at": fields.Datetime.now(),
            }
        )
        self.message_post(body=_("Weight override: %s") % self.weight_override_reason)

    def action_estimate_cost(self):
        for rec in self:
            if not rec.backend_id or not rec.backend_id.enable_pricing_estimation:
                raise UserError(_("Pricing estimation is disabled on the backend."))
            engine = CostEngine(rec.backend_id)
            size = rec.package_size_id
            bd = engine.compute(
                destination_governorate=rec.destination_region or rec.zone_name,
                package_size_id=rec.package_size_shipblu_id or (size.shipblu_size_id if size else None),
                package_size_code=size.code if size else None,
                cod_amount=rec.cod_amount,
                weight_kg=rec.total_weight_kg,
                try_and_buy=bool(rec.try_and_buy_requested and rec.try_and_buy_eligible),
                inspection=rec.inspection_requested,
            )
            rec.write(
                {
                    "cost_base_fee": bd.base_fee,
                    "cost_size_surcharge": bd.size_surcharge,
                    "cost_cod_fee": bd.cod_fee,
                    "cost_try_and_buy_fee": bd.try_and_buy_fee,
                    "cost_inspection_fee": bd.inspection_fee,
                    "cost_return_fee": bd.return_fee,
                    "cost_pickup_surcharge": bd.pickup_surcharge,
                    "cost_discount": bd.discount,
                    "cost_tax": bd.tax,
                    "cost_total": bd.total,
                    "cost_currency": bd.currency,
                    "cost_status": bd.status,
                    "cost_pricing_source": bd.pricing_source,
                    "cost_breakdown_json": json.dumps(bd.to_dict()),
                    "cost_notes": "\n".join(bd.notes),
                    "try_and_buy_fee": bd.try_and_buy_fee,
                    "inspection_fee": bd.inspection_fee,
                }
            )
            rec.message_post(body=_("Cost estimate refreshed: %(total).2f %(cur)s (%(st)s)")
                             % {"total": bd.total, "cur": bd.currency, "st": bd.status})
        return True

    def action_compute_sla(self):
        for rec in self:
            if not rec.backend_id:
                continue
            region = rec.destination_region
            rule = self.env["shipblu.sla.rule"].search(
                [
                    ("backend_id", "=", rec.backend_id.id),
                    ("active", "=", True),
                    ("region", "=ilike", region or ""),
                ],
                limit=1,
            )
            if not rule:
                continue
            base = fields.Date.context_today(rec)
            rec.write(
                {
                    "sla_rule_id": rule.id,
                    "eta_start": base + timedelta(days=int(rule.days_min or 1)),
                    "eta_end": base + timedelta(days=int(rule.days_max or 1)),
                }
            )
        return True

    def action_mark_label_printed(self):
        self.write({"label_print_status": "printed"})

    def action_confirm_courier_scan(self):
        """Manual confirmation only — do not invent API scan events."""
        self.write({"courier_scan_status": "scanned", "qr_present": True})
        for rec in self:
            rec.message_post(body=_("Courier QR/scan confirmed manually."))
