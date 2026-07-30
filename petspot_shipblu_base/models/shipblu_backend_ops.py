# -*- coding: utf-8 -*-
"""Operational configuration on ShipBlu backend (fees, cutoffs, controls, settlement)."""

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from odoo.addons.petspot_shipblu_base.services.cost_engine import CostEngine


class ShipBluBackendOps(models.Model):
    _inherit = "shipblu.backend"

    # --- Operational cutoffs ---
    company_timezone = fields.Char(
        string="Company Timezone",
        default="Africa/Cairo",
        required=True,
        help="Used for pickup/flyer cutoffs (not server UTC).",
    )
    pickup_cutoff_time = fields.Float(
        string="Pickup Request Cutoff",
        default=13.0,
        help="Hours as float (13.0 = 13:00). Same-day pickup eligibility.",
    )
    flyer_cutoff_time = fields.Float(
        string="Flyer Request Cutoff",
        default=10.0,
        help="Hours as float (10.0 = 10:00).",
    )
    min_shipments_per_pickup = fields.Integer(default=5, required=True)
    low_volume_pickup_surcharge = fields.Float(default=65.0, digits=(16, 2))
    max_shipment_weight_kg = fields.Float(default=10.0, digits=(16, 2))

    # --- Fees ---
    cod_commission_rate = fields.Float(string="COD Commission %", default=0.5, digits=(16, 4))
    try_and_buy_fee = fields.Float(default=40.0, digits=(16, 2))
    return_service_fee = fields.Float(default=5.0, digits=(16, 2))
    return_refusal_charge_percent = fields.Float(default=90.0, digits=(16, 2))
    inspection_fee = fields.Float(default=5.0, digits=(16, 2))
    settlement_transfer_fee = fields.Float(default=70.0, digits=(16, 2))
    large_package_surcharge_percent = fields.Float(default=10.0, digits=(16, 2))
    xlarge_package_surcharge_percent = fields.Float(default=15.0, digits=(16, 2))

    # --- Settlement ---
    settlement_weekday = fields.Selection(
        [
            ("0", "Monday"),
            ("1", "Tuesday"),
            ("2", "Wednesday"),
            ("3", "Thursday"),
            ("4", "Friday"),
            ("5", "Saturday"),
            ("6", "Sunday"),
        ],
        default="2",
        string="Settlement Weekday",
        help="0=Monday … 6=Sunday. Default Wednesday.",
    )
    settlement_bank_deadline_weekday = fields.Selection(
        [
            ("0", "Monday"),
            ("1", "Tuesday"),
            ("2", "Wednesday"),
            ("3", "Thursday"),
            ("4", "Friday"),
            ("5", "Saturday"),
            ("6", "Sunday"),
        ],
        default="5",
        string="Bank/Wallet Deadline Weekday",
        help="Default Saturday — missing details may defer settlement.",
    )
    settlement_bank_account = fields.Char()
    settlement_wallet = fields.Char()
    settlement_method = fields.Selection(
        [("bank", "Bank"), ("wallet", "Wallet"), ("other", "Other")],
        default="bank",
    )
    settlement_account_verified = fields.Boolean(
        string="Settlement Account Verified",
        default=False,
        tracking=True,
    )

    # --- Feature controls (dangerous ones default OFF) ---
    enable_pickup_automation = fields.Boolean(default=False, tracking=True)
    enable_pricing_estimation = fields.Boolean(default=True, tracking=True)
    enable_wallet_validation = fields.Boolean(default=False, tracking=True)
    enable_wallet_hard_block = fields.Boolean(
        default=False,
        help="If set with wallet validation, block create when insufficient (else warn).",
        tracking=True,
    )
    enable_sla_alerts = fields.Boolean(default=False, tracking=True)
    enable_settlement_reconciliation = fields.Boolean(default=False, tracking=True)
    enable_flyer_management = fields.Boolean(default=False, tracking=True)
    enable_coverage_blocking = fields.Boolean(default=False, tracking=True)
    enable_package_weight_blocking = fields.Boolean(default=False, tracking=True)
    enable_automatic_label_retrieval = fields.Boolean(default=False, tracking=True)
    try_and_buy_shopify_only = fields.Boolean(
        default=True,
        help="Try & Buy option only for Shopify-sourced orders unless overridden.",
    )
    try_and_buy_allow_non_shopify = fields.Boolean(
        default=False,
        help="Future override to allow Try & Buy on non-Shopify orders.",
    )

    # --- Wallet manual maintenance ---
    wallet_balance_manual = fields.Float(digits=(16, 2))
    wallet_balance_manual_at = fields.Datetime(readonly=True)
    wallet_balance_source = fields.Selection(
        [
            ("api", "API"),
            ("manual", "Manual"),
            ("unknown", "Unknown"),
        ],
        default="unknown",
        readonly=True,
    )

    # --- Relations ---
    pricing_rule_ids = fields.One2many("shipblu.pricing.rule", "backend_id")
    volume_discount_ids = fields.One2many("shipblu.volume.discount", "backend_id")
    package_size_ids = fields.One2many("shipblu.package.size", "backend_id")
    sla_rule_ids = fields.One2many("shipblu.sla.rule", "backend_id")
    settlement_ids = fields.One2many("shipblu.settlement", "backend_id")

    monthly_shipment_count = fields.Integer(compute="_compute_monthly_volume")
    active_discount_tier_id = fields.Many2one("shipblu.volume.discount", compute="_compute_monthly_volume")
    active_discount_percent = fields.Float(compute="_compute_monthly_volume")
    discount_status = fields.Selection(
        [("none", "None"), ("estimated", "Estimated"), ("gap", "Gap (no tier)")],
        compute="_compute_monthly_volume",
    )

    def _compute_monthly_volume(self):
        for rec in self:
            engine = CostEngine(rec)
            tier, count = engine.active_discount_tier()
            rec.monthly_shipment_count = count
            rec.active_discount_tier_id = tier.id if tier else False
            rec.active_discount_percent = tier.discount_percent if tier else 0.0
            if tier:
                rec.discount_status = "estimated"
            elif count:
                rec.discount_status = "gap"
            else:
                rec.discount_status = "none"

    @api.constrains("pickup_cutoff_time", "flyer_cutoff_time", "max_shipment_weight_kg", "min_shipments_per_pickup")
    def _check_ops_limits(self):
        for rec in self:
            if not (0 <= rec.pickup_cutoff_time < 24):
                raise ValidationError(_("Pickup cutoff must be between 0 and 24."))
            if not (0 <= rec.flyer_cutoff_time < 24):
                raise ValidationError(_("Flyer cutoff must be between 0 and 24."))
            if rec.max_shipment_weight_kg <= 0:
                raise ValidationError(_("Maximum shipment weight must be positive."))
            if rec.min_shipments_per_pickup < 1:
                raise ValidationError(_("Minimum shipments per pickup must be at least 1."))

    def action_set_manual_wallet_balance(self):
        self.ensure_one()
        if not self.env.user.has_group("petspot_shipblu_base.group_shipblu_accounting"):
            if not self.env.user.has_group("petspot_shipblu_base.group_shipblu_manager"):
                raise UserError(_("Only ShipBlu Accounting/Manager may set manual wallet balance."))
        self.write(
            {
                "wallet_balance_source": "manual",
                "wallet_balance_manual_at": fields.Datetime.now(),
            }
        )
        self.message_post(
            body=_("Manual wallet balance set to %(bal).2f (audit).")
            % {"bal": self.wallet_balance_manual}
        )
        return True

    def effective_wallet_balance(self):
        self.ensure_one()
        if self.wallet_balance_source == "manual":
            return float(self.wallet_balance_manual or 0.0)
        if "merchant_wallet_balance" in self._fields:
            return float(self.merchant_wallet_balance or 0.0)
        return float(self.wallet_balance_manual or 0.0)

    def get_cost_engine(self):
        self.ensure_one()
        return CostEngine(self)

    def float_time_to_str(self, value):
        hours = int(value)
        minutes = int(round((value - hours) * 60))
        if minutes == 60:
            hours += 1
            minutes = 0
        return f"{hours:02d}:{minutes:02d}"
