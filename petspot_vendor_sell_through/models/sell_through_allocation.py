# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import float_compare


class PetspotVendorSellThroughAllocation(models.Model):
    _name = "petspot.vendor.sell.through.allocation"
    _description = "Vendor Sell-Through Allocation"
    _order = "id asc"

    name = fields.Char(compute="_compute_name", store=True)
    active = fields.Boolean(default=True, index=True)
    company_id = fields.Many2one("res.company", required=True, index=True)
    layer_id = fields.Many2one(
        "petspot.vendor.sell.through.layer",
        required=True,
        index=True,
        ondelete="restrict",
    )
    product_id = fields.Many2one("product.product", required=True, index=True)
    vendor_bill_id = fields.Many2one("account.move", required=True, index=True)
    vendor_bill_line_id = fields.Many2one("account.move.line", required=True, index=True)
    outgoing_move_id = fields.Many2one("stock.move", index=True)
    outgoing_move_line_id = fields.Many2one("stock.move.line", index=True)
    outgoing_picking_id = fields.Many2one("stock.picking", index=True)
    lot_id = fields.Many2one("stock.lot", index=True)
    qty_base = fields.Float(required=True, digits="Product Unit of Measure")
    status = fields.Selection(
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
        index=True,
    )
    source_kind = fields.Selection(
        [
            ("system", "System"),
            ("legacy", "Legacy"),
            ("invoice", "Invoice Commercial"),
        ],
        default="system",
        required=True,
        index=True,
    )
    commercial_source_id = fields.Many2one(
        "petspot.vendor.sell.through.commercial.source",
        index=True,
        ondelete="set null",
    )
    customer_invoice_id = fields.Many2one("account.move", index=True)
    customer_invoice_line_id = fields.Many2one("account.move.line", index=True)
    sale_order_line_id = fields.Many2one("sale.order.line", index=True)
    source_key = fields.Char(index=True)
    is_return = fields.Boolean(default=False, index=True)
    reverses_allocation_id = fields.Many2one(
        "petspot.vendor.sell.through.allocation",
        index=True,
        ondelete="restrict",
    )
    evidence_ref = fields.Char()
    reason = fields.Text()
    approved_by_id = fields.Many2one("res.users")
    approved_date = fields.Datetime()
    previous_qty_base = fields.Float(digits="Product Unit of Measure")
    partner_display_masked = fields.Char(
        compute="_compute_partner_masked",
        help="Masked customer identity for audit display",
    )

    _sql_constraints = [
        (
            "vst_alloc_qty_positive",
            "CHECK (qty_base > 0)",
            "Allocation quantity must be positive.",
        ),
    ]

    @api.depends("product_id", "qty_base", "status", "is_return")
    def _compute_name(self):
        for rec in self:
            prefix = "RET" if rec.is_return else "SOLD"
            rec.name = "%s %s %s (%s)" % (
                prefix,
                rec.qty_base,
                rec.product_id.display_name or "",
                rec.status,
            )

    def _compute_partner_masked(self):
        for rec in self:
            partner = False
            if rec.outgoing_picking_id and rec.outgoing_picking_id.partner_id:
                partner = rec.outgoing_picking_id.partner_id
            elif rec.outgoing_move_id and rec.outgoing_move_id.partner_id:
                partner = rec.outgoing_move_id.partner_id
            elif rec.customer_invoice_id and rec.customer_invoice_id.partner_id:
                partner = rec.customer_invoice_id.partner_id
            if partner and partner.name:
                rec.partner_display_masked = (partner.name[:1] + "***") if partner.name else ""
            else:
                rec.partner_display_masked = ""

    @api.constrains("outgoing_move_line_id", "qty_base", "active", "is_return")
    def _check_outgoing_not_over_allocated(self):
        for rec in self:
            if not rec.outgoing_move_line_id or not rec.active or rec.is_return:
                continue
            ml = rec.outgoing_move_line_id
            base_uom = ml.product_id.uom_id
            from odoo.addons.petspot_vendor_sell_through.services.uom_util import convert_qty

            out_qty = convert_qty(ml.product_uom_id, ml.quantity, base_uom, raise_if_failure=False)
            if out_qty is None:
                continue
            total = sum(
                self.search(
                    [
                        ("outgoing_move_line_id", "=", ml.id),
                        ("active", "=", True),
                        ("is_return", "=", False),
                    ]
                ).mapped("qty_base")
            )
            if float_compare(total, out_qty, precision_rounding=base_uom.rounding or 0.0001) > 0:
                raise ValidationError(
                    "Outgoing move line over-allocated: %s > %s" % (total, out_qty)
                )
