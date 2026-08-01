# -*- coding: utf-8 -*-
from odoo import fields, models


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    vst_billed_qty = fields.Float(string="Billed quantity", digits="Product Unit of Measure", copy=False)
    vst_received_qty = fields.Float(string="Received quantity", digits="Product Unit of Measure", copy=False)
    vst_sold_qty = fields.Float(string="Sold quantity", digits="Product Unit of Measure", copy=False)
    vst_return_qty = fields.Float(string="Customer-returned quantity", digits="Product Unit of Measure", copy=False)
    vst_net_sold_qty = fields.Float(string="Net sold quantity", digits="Product Unit of Measure", copy=False)
    vst_unsold_qty = fields.Float(string="Unsold quantity", digits="Product Unit of Measure", copy=False)
    vst_unit_cost = fields.Monetary(string="Unit purchase cost", currency_field="currency_id", copy=False)
    vst_sold_untaxed = fields.Monetary(string="Sold untaxed value", currency_field="currency_id", copy=False)
    vst_sold_tax = fields.Monetary(string="Proportional tax", currency_field="currency_id", copy=False)
    vst_sold_gross = fields.Monetary(string="Sold gross value", currency_field="currency_id", copy=False)
    vst_tracking_confidence = fields.Selection(
        [
            ("exact_lot", "Exact Lot"),
            ("exact_fifo", "Exact FIFO"),
            ("approved_legacy", "Approved Legacy"),
            ("estimated_legacy", "Estimated Legacy"),
            ("unallocated", "Unallocated"),
            ("blocked_uom", "Blocked UoM"),
        ],
        string="Tracking confidence",
        copy=False,
    )
    vst_source_receipts = fields.Char(string="Source receipts", copy=False)
    vst_source_sales = fields.Char(string="Source deliveries/POS sales", copy=False)
    vst_allocation_ids = fields.One2many(
        "petspot.vendor.sell.through.allocation",
        "vendor_bill_line_id",
        string="Sell-Through Allocations",
    )
    vst_layer_ids = fields.One2many(
        "petspot.vendor.sell.through.layer",
        "vendor_bill_line_id",
        string="Sell-Through Layers",
    )
