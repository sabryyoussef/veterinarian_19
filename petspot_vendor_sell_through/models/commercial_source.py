# -*- coding: utf-8 -*-
"""Auditable invoice-derived commercial sale sources for Vendor Sell-Through."""

from odoo import api, fields, models


class PetspotVendorSellThroughCommercialSource(models.Model):
    _name = "petspot.vendor.sell.through.commercial.source"
    _description = "Invoice-Derived Commercial Sale Source"
    _order = "invoice_date asc, id asc"

    name = fields.Char(compute="_compute_name", store=True)
    active = fields.Boolean(default=True, index=True)
    company_id = fields.Many2one("res.company", required=True, index=True)
    supplier_id = fields.Many2one("res.partner", index=True, help="Vendor bill partner when allocated")
    vendor_bill_id = fields.Many2one("account.move", index=True)
    vendor_bill_line_id = fields.Many2one("account.move.line", index=True)
    product_id = fields.Many2one("product.product", required=True, index=True)

    customer_invoice_id = fields.Many2one("account.move", required=True, index=True)
    customer_invoice_line_id = fields.Many2one("account.move.line", required=True, index=True)
    refund_line_ids = fields.Many2many(
        "account.move.line",
        "vst_commercial_source_refund_rel",
        "source_id",
        "refund_line_id",
        string="Linked refund lines",
    )
    sale_order_line_id = fields.Many2one("sale.order.line", index=True)
    stock_move_ids = fields.Many2many(
        "stock.move",
        "vst_commercial_source_move_rel",
        "source_id",
        "move_id",
        string="Stock moves already counted",
    )

    qty_original = fields.Float(required=True, digits="Product Unit of Measure")
    uom_original_id = fields.Many2one("uom.uom", required=True)
    qty_base = fields.Float(required=True, digits="Product Unit of Measure")
    qty_bill_uom = fields.Float(digits="Product Unit of Measure")
    bill_uom_id = fields.Many2one("uom.uom")
    qty_stock_counted_base = fields.Float(digits="Product Unit of Measure", default=0.0)
    qty_invoice_only_base = fields.Float(digits="Product Unit of Measure", default=0.0)
    qty_refunded_base = fields.Float(digits="Product Unit of Measure", default=0.0)
    eligible_amount = fields.Monetary(currency_field="currency_id")
    currency_id = fields.Many2one("res.currency")

    invoice_date = fields.Date(index=True)
    cutoff_date = fields.Date(required=True, index=True)
    source_key = fields.Char(required=True, index=True)
    reason = fields.Selection(
        [
            (
                "POSTED_INVOICE_WITHOUT_DONE_CUSTOMER_DELIVERY",
                "Posted invoice without done customer delivery",
            ),
            (
                "POSTED_INVOICE_PARTIAL_DELIVERY_RESIDUAL",
                "Posted invoice residual after partial delivery",
            ),
        ],
        required=True,
        default="POSTED_INVOICE_WITHOUT_DONE_CUSTOMER_DELIVERY",
    )
    state = fields.Selection(
        [
            ("draft", "Draft / Dry-run"),
            ("applied", "Applied"),
            ("blocked_uom", "Blocked UoM"),
            ("blocked_settled_refund", "Blocked settled refund"),
            ("reversed", "Reversed"),
            ("zero", "Zero eligible"),
        ],
        default="draft",
        required=True,
        index=True,
    )
    allocation_ids = fields.One2many(
        "petspot.vendor.sell.through.allocation",
        "commercial_source_id",
        string="Allocations",
    )
    notes = fields.Text()

    _source_key_uniq = models.Constraint(
        "UNIQUE(source_key)",
        "Commercial source key must be unique.",
    )

    @api.depends("product_id", "qty_invoice_only_base", "customer_invoice_id")
    def _compute_name(self):
        for rec in self:
            inv = rec.customer_invoice_id.name or ""
            rec.name = "INV-SRC %s %s (%s)" % (
                rec.qty_invoice_only_base,
                rec.product_id.display_name or "",
                inv,
            )
