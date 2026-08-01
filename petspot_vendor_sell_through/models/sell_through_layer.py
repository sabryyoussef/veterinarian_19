# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import float_compare


class PetspotVendorSellThroughLayer(models.Model):
    _name = "petspot.vendor.sell.through.layer"
    _description = "Vendor Sell-Through Receipt Layer"
    _order = "receipt_date asc, id asc"

    name = fields.Char(required=True)
    company_id = fields.Many2one("res.company", required=True, index=True)
    vendor_id = fields.Many2one("res.partner", required=True, index=True)
    vendor_bill_id = fields.Many2one("account.move", required=True, index=True, ondelete="cascade")
    vendor_bill_line_id = fields.Many2one("account.move.line", required=True, index=True, ondelete="cascade")
    purchase_order_id = fields.Many2one("purchase.order", index=True)
    purchase_line_id = fields.Many2one("purchase.order.line", index=True)
    incoming_move_id = fields.Many2one("stock.move", index=True)
    incoming_move_line_id = fields.Many2one("stock.move.line", index=True)
    product_id = fields.Many2one("product.product", required=True, index=True)
    lot_id = fields.Many2one("stock.lot", index=True)
    purchase_uom_id = fields.Many2one("uom.uom", required=True)
    base_uom_id = fields.Many2one("uom.uom", required=True)
    received_qty_base = fields.Float(required=True, digits="Product Unit of Measure")
    supplier_return_qty_base = fields.Float(default=0.0, digits="Product Unit of Measure")
    allocated_sold_qty_base = fields.Float(default=0.0, digits="Product Unit of Measure")
    customer_return_qty_base = fields.Float(default=0.0, digits="Product Unit of Measure")
    remaining_qty_base = fields.Float(compute="_compute_remaining", store=True, digits="Product Unit of Measure")
    unit_cost_base = fields.Monetary(currency_field="currency_id")
    unit_cost_purchase = fields.Monetary(currency_field="currency_id")
    currency_id = fields.Many2one("res.currency", required=True)
    tax_ratio = fields.Float(help="Tax amount / untaxed for the bill line")
    confidence = fields.Selection(
        [
            ("exact_lot", "Exact Lot"),
            ("exact_fifo", "Exact FIFO"),
            ("approved_legacy", "Approved Legacy"),
            ("approved_invoice", "Approved Invoice Commercial"),
            ("estimated_legacy", "Estimated Legacy"),
            ("unallocated", "Unallocated"),
            ("blocked_uom", "Blocked UoM"),
        ],
        required=True,
        default="exact_fifo",
        index=True,
    )
    source_kind = fields.Selection(
        [("receipt", "Receipt"), ("legacy", "Legacy"), ("invoice", "Invoice Commercial")],
        default="receipt",
        required=True,
        index=True,
    )
    receipt_date = fields.Datetime(index=True)
    allocation_ids = fields.One2many("petspot.vendor.sell.through.allocation", "layer_id", string="Allocations")

    _sql_constraints = [
        (
            "vst_layer_received_positive",
            "CHECK (received_qty_base >= 0)",
            "Received quantity must be non-negative.",
        ),
    ]

    @api.depends(
        "received_qty_base",
        "supplier_return_qty_base",
        "allocated_sold_qty_base",
        "customer_return_qty_base",
    )
    def _compute_remaining(self):
        for rec in self:
            rec.remaining_qty_base = (
                rec.received_qty_base
                - rec.supplier_return_qty_base
                - rec.allocated_sold_qty_base
                + rec.customer_return_qty_base
            )

    def _recompute_allocated(self):
        Allocation = self.env["petspot.vendor.sell.through.allocation"]
        for layer in self:
            sold = sum(
                Allocation.search(
                    [("layer_id", "=", layer.id), ("active", "=", True), ("is_return", "=", False)]
                ).mapped("qty_base")
            )
            returned = sum(
                Allocation.search(
                    [("layer_id", "=", layer.id), ("active", "=", True), ("is_return", "=", True)]
                ).mapped("qty_base")
            )
            layer.write(
                {
                    "allocated_sold_qty_base": sold,
                    "customer_return_qty_base": returned,
                }
            )

    @api.constrains("allocated_sold_qty_base", "received_qty_base", "supplier_return_qty_base", "customer_return_qty_base")
    def _check_no_over_allocation(self):
        for rec in self:
            available = rec.received_qty_base - rec.supplier_return_qty_base
            net_sold = rec.allocated_sold_qty_base - rec.customer_return_qty_base
            if float_compare(net_sold, available, precision_rounding=rec.base_uom_id.rounding or 0.0001) > 0:
                raise ValidationError(
                    "Sell-through over-allocation on layer %s: net sold %s > available %s"
                    % (rec.display_name, net_sold, available)
                )
