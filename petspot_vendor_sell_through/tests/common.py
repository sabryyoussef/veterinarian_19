# -*- coding: utf-8 -*-
"""Shared helpers for Vendor Sell-Through tests (Odoo 19)."""

from odoo import fields
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install", "petspot_vendor_sell_through")
class VstCommon(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.currency = cls.company.currency_id
        cls.partner = cls.env["res.partner"].create({"name": "VST-UAT-Vendor", "supplier_rank": 1})
        cls.customer = cls.env["res.partner"].create({"name": "VST-UAT-Customer", "customer_rank": 1})

        # Odoo 19 relative UoMs: Chew (reference) + Box containing 6 Chews
        cls.uom_chew = cls.env["uom.uom"].create(
            {
                "name": "VST-UAT-Chew",
                "relative_factor": 1.0,
            }
        )
        cls.uom_box6 = cls.env["uom.uom"].create(
            {
                "name": "VST-UAT-Box6",
                "relative_uom_id": cls.uom_chew.id,
                "relative_factor": 6.0,
            }
        )

        cls.product = cls.env["product.product"].create(
            {
                "name": "VST-UAT-SIMT-2.5-5 Simparica Trio",
                "default_code": "VST-UAT-SIMT-2.5-5",
                "is_storable": True,
                "type": "consu",
                "uom_id": cls.uom_chew.id,
                "uom_ids": [(4, cls.uom_box6.id)],
                "list_price": 200.0,
                "standard_price": 96.75,
                "categ_id": cls.env.ref("product.product_category_goods").id,
            }
        )

        cls.stock_location = cls.env.ref("stock.stock_location_stock")
        cls.customer_location = cls.env.ref("stock.stock_location_customers")
        cls.picking_type_in = cls.env.ref("stock.picking_type_in")
        cls.picking_type_out = cls.env.ref("stock.picking_type_out")

        grp_view = cls.env.ref("petspot_vendor_sell_through.group_vst_viewer")
        grp_alloc = cls.env.ref("petspot_vendor_sell_through.group_vst_allocation_manager")
        grp_pay = cls.env.ref("petspot_vendor_sell_through.group_vst_payment_manager")
        cls.env.user.group_ids = [(4, grp_view.id), (4, grp_alloc.id), (4, grp_pay.id)]

    def _create_po_receive_bill(self, qty_boxes=30.0, price=580.50, product=None, partner=None):
        product = product or self.product
        partner = partner or self.partner
        po = self.env["purchase.order"].create(
            {
                "partner_id": partner.id,
                "order_line": [
                    (
                        0,
                        0,
                        {
                            "product_id": product.id,
                            "name": product.display_name,
                            "product_qty": qty_boxes,
                            "product_uom_id": self.uom_box6.id,
                            "price_unit": price,
                        },
                    )
                ],
            }
        )
        po.button_confirm()
        picking = po.picking_ids[:1]
        for move in picking.move_ids:
            move.quantity = move.product_uom_qty
        picking.button_validate()

        po.action_create_invoice()
        bill = po.invoice_ids.filtered(lambda m: m.move_type == "in_invoice")[:1]
        if not bill.invoice_date:
            bill.invoice_date = fields.Date.context_today(self.env.user)
        if bill.state != "posted":
            bill.action_post()
        bill._vst_run_rebuild("uat rebuild")
        return po, picking, bill

    def _deliver(self, product, qty_chews, lot=None):
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": self.picking_type_out.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "partner_id": self.customer.id,
            }
        )
        move = self.env["stock.move"].create(
            {
                "description_picking": product.display_name,
                "product_id": product.id,
                "product_uom_qty": qty_chews,
                "product_uom": product.uom_id.id,
                "picking_id": picking.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
            }
        )
        picking.action_confirm()
        picking.action_assign()
        if move.move_line_ids:
            for ml in move.move_line_ids:
                ml.quantity = qty_chews
                if lot:
                    ml.lot_id = lot.id
        else:
            self.env["stock.move.line"].create(
                {
                    "move_id": move.id,
                    "product_id": product.id,
                    "product_uom_id": product.uom_id.id,
                    "quantity": qty_chews,
                    "location_id": self.stock_location.id,
                    "location_dest_id": self.customer_location.id,
                    "picking_id": picking.id,
                    "lot_id": lot.id if lot else False,
                }
            )
        move.quantity = qty_chews
        picking.button_validate()
        return picking, move

    def _assert_money(self, actual, expected):
        self.assertAlmostEqual(actual, expected, places=2)
