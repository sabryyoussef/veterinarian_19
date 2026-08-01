# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import float_is_zero


class PetspotVendorSellThroughLegacyWizard(models.TransientModel):
    _name = "petspot.vendor.sell.through.legacy.wizard"
    _description = "Legacy Sell-Through Allocation Wizard"

    vendor_bill_id = fields.Many2one("account.move", required=True)
    vendor_bill_line_id = fields.Many2one(
        "account.move.line",
        required=True,
        domain="[('move_id', '=', vendor_bill_id), ('display_type', 'not in', ('line_section', 'line_note')), ('product_id', '!=', False)]",
    )
    product_id = fields.Many2one(related="vendor_bill_line_id.product_id", readonly=True)
    qty = fields.Float(string="Historically sold quantity", required=True)
    uom_id = fields.Many2one("uom.uom", string="Stock UoM", required=True)
    sale_order_ids = fields.Many2many("sale.order", string="Supporting sales orders")
    invoice_ids = fields.Many2many(
        "account.move",
        string="Supporting customer invoices",
        domain="[('move_type', '=', 'out_invoice')]",
    )
    evidence_ref = fields.Char(required=True)
    reason = fields.Text(required=True)
    approve = fields.Boolean(
        string="Mark as approved_legacy (payable)",
        help="If unchecked, creates estimated_legacy (visible, not payable).",
        default=False,
    )

    @api.onchange("vendor_bill_line_id")
    def _onchange_line(self):
        if self.vendor_bill_line_id and self.vendor_bill_line_id.product_id:
            self.uom_id = self.vendor_bill_line_id.product_id.uom_id

    def action_confirm(self):
        self.ensure_one()
        if not self.env.user.has_group("petspot_vendor_sell_through.group_vst_allocation_manager"):
            raise AccessError("Only Inventory allocation managers may create legacy allocations.")
        if self.approve and not self.env.user.has_group("petspot_vendor_sell_through.group_vst_allocation_manager"):
            raise AccessError("Approval requires Inventory allocation manager rights.")
        if float_is_zero(self.qty, precision_digits=6) or self.qty < 0:
            raise UserError("Quantity must be positive.")

        from odoo.addons.petspot_vendor_sell_through.services.uom_util import convert_qty
        from odoo.addons.petspot_vendor_sell_through.services.rebuild import recompute_bill_metrics, _tax_ratio

        line = self.vendor_bill_line_id
        bill = self.vendor_bill_id
        product = line.product_id
        base_uom = product.uom_id
        qty_base = convert_qty(self.uom_id, self.qty, base_uom, raise_if_failure=True)
        status = "approved_legacy" if self.approve else "estimated_legacy"

        Layer = self.env["petspot.vendor.sell.through.layer"]
        layer = Layer.search(
            [
                ("vendor_bill_line_id", "=", line.id),
                ("source_kind", "=", "legacy"),
                ("confidence", "=", status),
            ],
            limit=1,
        )
        factor = convert_qty(line.product_uom_id or base_uom, 1.0, base_uom, raise_if_failure=False) or 1.0
        unit_cost_base = line.price_unit / factor if factor else 0.0
        if not layer:
            layer = Layer.create(
                {
                    "name": "Legacy %s" % (bill.name,),
                    "company_id": bill.company_id.id,
                    "vendor_id": bill.partner_id.id,
                    "vendor_bill_id": bill.id,
                    "vendor_bill_line_id": line.id,
                    "purchase_order_id": line.purchase_line_id.order_id.id if line.purchase_line_id else False,
                    "purchase_line_id": line.purchase_line_id.id if line.purchase_line_id else False,
                    "product_id": product.id,
                    "purchase_uom_id": (line.product_uom_id or base_uom).id,
                    "base_uom_id": base_uom.id,
                    "received_qty_base": qty_base,
                    "unit_cost_base": unit_cost_base,
                    "unit_cost_purchase": line.price_unit,
                    "currency_id": bill.currency_id.id,
                    "tax_ratio": _tax_ratio(line),
                    "confidence": status,
                    "source_kind": "legacy",
                    "receipt_date": fields.Datetime.now(),
                }
            )
        else:
            old = layer.received_qty_base
            layer.write(
                {
                    "received_qty_base": layer.received_qty_base + qty_base,
                    "confidence": status,
                }
            )
            layer.message_post = None  # layers may not have mail.thread

        Allocation = self.env["petspot.vendor.sell.through.allocation"]
        Allocation.create(
            {
                "company_id": bill.company_id.id,
                "layer_id": layer.id,
                "product_id": product.id,
                "vendor_bill_id": bill.id,
                "vendor_bill_line_id": line.id,
                "qty_base": qty_base,
                "status": status,
                "source_kind": "legacy",
                "evidence_ref": self.evidence_ref,
                "reason": self.reason,
                "approved_by_id": self.env.user.id if self.approve else False,
                "approved_date": fields.Datetime.now() if self.approve else False,
                "previous_qty_base": 0.0,
            }
        )
        layer._recompute_allocated()
        recompute_bill_metrics(self.env, bill)
        return {"type": "ir.actions.act_window_close"}
