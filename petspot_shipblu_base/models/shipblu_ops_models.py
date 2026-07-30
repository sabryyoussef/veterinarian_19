# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ShipBluPricingRule(models.Model):
    _name = "shipblu.pricing.rule"
    _description = "ShipBlu Pricing Rule"
    _order = "sequence, id"

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    backend_id = fields.Many2one("shipblu.backend", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="backend_id.company_id", store=True, index=True)
    active = fields.Boolean(default=True)
    origin_governorate = fields.Char(required=True, help="e.g. Giza")
    destination_governorate = fields.Char(required=True, help="e.g. Alexandria / Delta / Canal Cities")
    origin_zone_id = fields.Integer(string="Origin Zone ID (optional)")
    destination_zone_id = fields.Integer(string="Destination Zone ID (optional)")
    base_price = fields.Float(required=True, digits=(16, 2))
    currency_id = fields.Many2one(
        "res.currency",
        default=lambda self: self.env.company.currency_id,
    )
    tax_included = fields.Boolean(
        default=False,
        help="Reference prices exclude tax by default.",
    )
    min_weight = fields.Float(string="Min Weight (kg)", default=0.0)
    max_weight = fields.Float(string="Max Weight (kg)", default=0.0, help="0 = no max")
    date_from = fields.Date()
    date_to = fields.Date()
    source = fields.Selection(
        [
            ("manual", "Manual"),
            ("contract", "Contract"),
            ("api", "API"),
            ("imported", "Imported sheet"),
        ],
        default="manual",
        required=True,
    )
    note = fields.Char()


class ShipBluVolumeDiscount(models.Model):
    _name = "shipblu.volume.discount"
    _description = "ShipBlu Monthly Volume Discount Tier"
    _order = "min_shipments"

    name = fields.Char(compute="_compute_name", store=True)
    backend_id = fields.Many2one("shipblu.backend", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="backend_id.company_id", store=True)
    active = fields.Boolean(default=True)
    min_shipments = fields.Integer(required=True)
    max_shipments = fields.Integer(required=True)
    discount_percent = fields.Float(required=True, digits=(16, 2))

    @api.depends("min_shipments", "max_shipments", "discount_percent")
    def _compute_name(self):
        for rec in self:
            rec.name = f"{rec.min_shipments}–{rec.max_shipments}: {rec.discount_percent}%"

    @api.constrains("min_shipments", "max_shipments", "backend_id", "active")
    def _check_range_and_overlap(self):
        from odoo.exceptions import ValidationError

        for rec in self:
            if rec.min_shipments > rec.max_shipments:
                raise ValidationError("Volume discount min must be <= max.")
            if not rec.active:
                continue
            others = self.search(
                [
                    ("id", "!=", rec.id),
                    ("backend_id", "=", rec.backend_id.id),
                    ("active", "=", True),
                    ("min_shipments", "<=", rec.max_shipments),
                    ("max_shipments", ">=", rec.min_shipments),
                ]
            )
            if others:
                raise ValidationError(
                    "Overlapping volume discount tiers are not allowed "
                    f"({rec.min_shipments}-{rec.max_shipments} overlaps "
                    f"{others[0].min_shipments}-{others[0].max_shipments})."
                )

class ShipBluPackageSize(models.Model):
    _name = "shipblu.package.size"
    _description = "ShipBlu Package Size Mapping"
    _order = "sequence, shipblu_size_id"

    name = fields.Char(required=True)
    code = fields.Selection(
        [
            ("small", "Small"),
            ("medium", "Medium"),
            ("large", "Large"),
            ("xlarge", "Extra Large"),
        ],
        required=True,
    )
    sequence = fields.Integer(default=10)
    backend_id = fields.Many2one("shipblu.backend", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="backend_id.company_id", store=True)
    active = fields.Boolean(default=True)
    shipblu_size_id = fields.Integer(
        string="ShipBlu Package Size ID",
        required=True,
        help="Official package_size integer used in API payloads. Never guess.",
    )
    surcharge_percent = fields.Float(
        string="Surcharge %",
        default=0.0,
        help="Applied on base shipping price (Large 10%, XL 15%).",
    )
    note = fields.Char()

    _shipblu_package_size_uniq = models.Constraint(
        "unique(backend_id, shipblu_size_id)",
        "Package size ID must be unique per backend.",
    )


class ShipBluSlaRule(models.Model):
    _name = "shipblu.sla.rule"
    _description = "ShipBlu Delivery SLA Rule"
    _order = "sequence, id"

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    backend_id = fields.Many2one("shipblu.backend", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="backend_id.company_id", store=True)
    active = fields.Boolean(default=True)
    region = fields.Char(required=True, help="Cairo / Giza / Alexandria / Delta / Canal Cities / Assiut / North Coast")
    days_min = fields.Integer(default=1, required=True)
    days_max = fields.Integer(default=1, required=True)
    note = fields.Char()


class ShipBluSettlement(models.Model):
    _name = "shipblu.settlement"
    _description = "ShipBlu Settlement"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "period_end desc, id desc"

    name = fields.Char(required=True, default="New")
    backend_id = fields.Many2one("shipblu.backend", required=True, ondelete="restrict", index=True)
    company_id = fields.Many2one(related="backend_id.company_id", store=True, index=True)
    period_start = fields.Date(required=True)
    period_end = fields.Date(required=True)
    statement_date = fields.Date()
    planned_transfer_date = fields.Date()
    transfer_method = fields.Selection(
        [
            ("bank", "Bank"),
            ("wallet", "Wallet"),
            ("other", "Other"),
        ],
        default="bank",
    )
    bank_account = fields.Char()
    wallet_account = fields.Char()
    gross_cod = fields.Float(digits=(16, 2))
    shipping_fees = fields.Float(digits=(16, 2))
    cod_commission = fields.Float(digits=(16, 2))
    service_fees = fields.Float(digits=(16, 2))
    return_fees = fields.Float(digits=(16, 2))
    transfer_fee = fields.Float(digits=(16, 2))
    tax = fields.Float(digits=(16, 2))
    discounts = fields.Float(digits=(16, 2))
    adjustments = fields.Float(digits=(16, 2))
    net_settlement = fields.Float(digits=(16, 2), compute="_compute_net", store=True)
    status = fields.Selection(
        [
            ("draft", "Draft"),
            ("expected", "Expected"),
            ("statement", "Statement received"),
            ("transferred", "Transferred"),
            ("reconciled", "Reconciled"),
            ("deferred", "Deferred"),
            ("cancelled", "Cancelled"),
        ],
        default="draft",
        tracking=True,
        required=True,
    )
    shipblu_external_ref = fields.Char(index=True)
    statement_attachment_id = fields.Many2one("ir.attachment", copy=False)
    reconciliation_state = fields.Selection(
        [
            ("open", "Open"),
            ("partial", "Partial"),
            ("done", "Done"),
            ("mismatch", "Mismatch"),
        ],
        default="open",
        tracking=True,
    )
    notes = fields.Text()
    account_missing_warning = fields.Boolean(
        compute="_compute_account_warning",
        help="True when bank/wallet details missing before Saturday deadline.",
    )

    @api.depends(
        "gross_cod",
        "shipping_fees",
        "cod_commission",
        "service_fees",
        "return_fees",
        "transfer_fee",
        "tax",
        "discounts",
        "adjustments",
    )
    def _compute_net(self):
        for rec in self:
            rec.net_settlement = (
                float(rec.gross_cod or 0.0)
                - float(rec.shipping_fees or 0.0)
                - float(rec.cod_commission or 0.0)
                - float(rec.service_fees or 0.0)
                - float(rec.return_fees or 0.0)
                - float(rec.transfer_fee or 0.0)
                - float(rec.tax or 0.0)
                + float(rec.discounts or 0.0)
                + float(rec.adjustments or 0.0)
            )

    @api.depends("bank_account", "wallet_account", "transfer_method", "backend_id")
    def _compute_account_warning(self):
        for rec in self:
            if rec.transfer_method == "bank":
                rec.account_missing_warning = not bool(rec.bank_account or rec.backend_id.settlement_bank_account)
            elif rec.transfer_method == "wallet":
                rec.account_missing_warning = not bool(rec.wallet_account or rec.backend_id.settlement_wallet)
            else:
                rec.account_missing_warning = False

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = self.env["ir.sequence"].next_by_code("shipblu.settlement") or "SET/NEW"
            backend = self.env["shipblu.backend"].browse(vals.get("backend_id"))
            if backend and "transfer_fee" not in vals:
                vals["transfer_fee"] = backend.settlement_transfer_fee
        return super().create(vals_list)
