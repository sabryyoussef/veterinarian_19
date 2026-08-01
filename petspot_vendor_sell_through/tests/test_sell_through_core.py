# -*- coding: utf-8 -*-
from odoo import fields
from odoo.tests import tagged

from .common import VstCommon


@tagged("post_install", "-at_install", "petspot_vendor_sell_through")
class TestVstCore(VstCommon):
    def test_01_full_pack_sale(self):
        """One bill, one receipt, one full-pack (box) sale."""
        po, receipt, bill = self._create_po_receive_bill(qty_boxes=1.0, price=580.50)
        self.assertEqual(len(bill.vst_layer_ids), 1)
        self.assertAlmostEqual(bill.vst_layer_ids.received_qty_base, 6.0, places=2)
        picking, _move = self._deliver(self.product, 6.0)
        bill._vst_run_rebuild("uat rebuild")
        self._assert_money(bill.vst_eligible_amount, 580.50)
        self.assertEqual(picking.state, "done")

    def test_02_box_sold_as_individual_chews(self):
        """8 individual Chews from Box-of-6 purchase cost."""
        _po, _r, bill = self._create_po_receive_bill(qty_boxes=30.0, price=580.50)
        # 30 boxes × 6 = 180 Chews; unit cost 580.50/6 = 96.75
        self.assertAlmostEqual(sum(bill.vst_layer_ids.mapped("received_qty_base")), 180.0, places=2)
        self.assertAlmostEqual(bill.vst_layer_ids[0].unit_cost_base, 96.75, places=2)
        self._deliver(self.product, 8.0)
        bill._vst_run_rebuild("uat rebuild")
        self._assert_money(bill.vst_eligible_amount, 774.00)

    def test_03_partial_sale_and_suggested_payment(self):
        _po, _r, bill = self._create_po_receive_bill(qty_boxes=10.0, price=580.50)
        self._deliver(self.product, 5 * 6)  # 5 boxes as chews
        bill._vst_run_rebuild("uat rebuild")
        self._assert_money(bill.vst_eligible_amount, 5 * 580.50)
        self.assertGreater(bill.vst_suggested_payment, 0.0)
        self.assertLessEqual(bill.vst_suggested_payment, bill.amount_residual)

    def test_04_second_sale_increases_eligible(self):
        _po, _r, bill = self._create_po_receive_bill(qty_boxes=10.0, price=580.50)
        self._deliver(self.product, 6.0)
        bill._vst_run_rebuild("uat rebuild")
        first = bill.vst_eligible_amount
        self._deliver(self.product, 6.0)
        bill._vst_run_rebuild("uat rebuild")
        self._assert_money(bill.vst_eligible_amount, first + 580.50)

    def test_05_existing_payment_reduces_suggestion(self):
        _po, _r, bill = self._create_po_receive_bill(qty_boxes=5.0, price=580.50)
        self._deliver(self.product, 6.0)
        bill._vst_run_rebuild("uat rebuild")
        eligible = bill.vst_eligible_amount
        # Simulate partial payment by registering via wizard confirm_post in txn
        journal = self.env["account.journal"].search(
            [("type", "in", ("bank", "cash")), ("company_id", "=", self.company.id)], limit=1
        )
        wiz = self.env["petspot.vendor.sell.through.payment.wizard"].create(
            {
                "move_id": bill.id,
                "amount": min(eligible, bill.amount_residual) / 2.0,
                "journal_id": journal.id,
                "confirm_post": True,
            }
        )
        wiz.action_open_standard_payment()
        bill.invalidate_recordset()
        bill._vst_run_rebuild("uat rebuild")
        self.assertLess(bill.vst_suggested_payment, eligible)
        self.assertAlmostEqual(
            bill.vst_suggested_payment,
            max(0.0, bill.vst_eligible_amount - bill.vst_already_paid),
            places=2,
        )

    def test_06_payment_never_exceeds_residual(self):
        _po, _r, bill = self._create_po_receive_bill(qty_boxes=2.0, price=580.50)
        self._deliver(self.product, 12.0)
        bill._vst_run_rebuild("uat rebuild")
        self.assertLessEqual(bill.vst_suggested_payment, bill.amount_residual)

    def test_17_assigned_delivery_not_counted(self):
        _po, _r, bill = self._create_po_receive_bill(qty_boxes=2.0, price=580.50)
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": self.picking_type_out.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "partner_id": self.customer.id,
            }
        )
        self.env["stock.move"].create(
            {
                "description_picking": self.product.display_name,
                "product_id": self.product.id,
                "product_uom_qty": 6.0,
                "product_uom": self.product.uom_id.id,
                "picking_id": picking.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
            }
        )
        picking.action_confirm()
        picking.action_assign()
        self.assertEqual(picking.state, "assigned")
        bill._vst_run_rebuild("uat rebuild")
        self._assert_money(bill.vst_eligible_amount, 0.0)

    def test_18_cancelled_delivery_not_counted(self):
        _po, _r, bill = self._create_po_receive_bill(qty_boxes=2.0, price=580.50)
        picking, move = self._deliver(self.product, 6.0)
        # Create another assigned then cancel without validate
        p2 = self.env["stock.picking"].create(
            {
                "picking_type_id": self.picking_type_out.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "partner_id": self.customer.id,
            }
        )
        self.env["stock.move"].create(
            {
                "description_picking": self.product.display_name,
                "product_id": self.product.id,
                "product_uom_qty": 6.0,
                "product_uom": self.product.uom_id.id,
                "picking_id": p2.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
            }
        )
        p2.action_confirm()
        p2.action_assign()
        p2.action_cancel()
        bill._vst_run_rebuild("uat rebuild")
        self._assert_money(bill.vst_eligible_amount, 580.50)

    def test_19_invoice_without_delivery_is_counted(self):
        """Posted customer invoice without done delivery → invoice commercial allocation."""
        _po, _r, bill = self._create_po_receive_bill(qty_boxes=1.0, price=580.50)
        so = self.env["sale.order"].create(
            {
                "partner_id": self.customer.id,
                "order_line": [
                    (
                        0,
                        0,
                        {
                            "product_id": self.product.id,
                            "product_uom_qty": 6.0,
                            "price_unit": 200.0,
                        },
                    )
                ],
            }
        )
        so.action_confirm()
        # Cancel delivery so stock allocator does not count
        for picking in so.picking_ids:
            if picking.state not in ("done", "cancel"):
                picking.action_cancel()
        inv = so._create_invoices()
        inv.action_post()
        bill._vst_run_rebuild("uat rebuild")
        self._assert_money(bill.vst_eligible_amount, 580.50)
        alloc = self.env["petspot.vendor.sell.through.allocation"].search(
            [("vendor_bill_id", "=", bill.id), ("source_kind", "=", "invoice"), ("active", "=", True)]
        )
        self.assertTrue(alloc)
        self.assertAlmostEqual(sum(alloc.mapped("qty_base")), 6.0, places=2)

    def test_23_24_legacy_estimated_vs_approved(self):
        _po, _r, bill = self._create_po_receive_bill(qty_boxes=1.0, price=580.50)
        line = bill.invoice_line_ids.filtered(lambda l: l.product_id)[:1]
        wiz = self.env["petspot.vendor.sell.through.legacy.wizard"].create(
            {
                "vendor_bill_id": bill.id,
                "vendor_bill_line_id": line.id,
                "qty": 6.0,
                "uom_id": self.uom_chew.id,
                "evidence_ref": "VST-UAT-EST-1",
                "reason": "Invoice-only estimate",
                "approve": False,
            }
        )
        wiz.action_confirm()
        bill._vst_run_rebuild("uat rebuild")
        self._assert_money(bill.vst_eligible_amount, 0.0)
        wiz2 = self.env["petspot.vendor.sell.through.legacy.wizard"].create(
            {
                "vendor_bill_id": bill.id,
                "vendor_bill_line_id": line.id,
                "qty": 6.0,
                "uom_id": self.uom_chew.id,
                "evidence_ref": "VST-UAT-APR-1",
                "reason": "Manager approved historical sale",
                "approve": True,
            }
        )
        wiz2.action_confirm()
        bill._vst_run_rebuild("uat rebuild")
        self.assertGreater(bill.vst_eligible_amount, 0.0)

    def test_26_rebuild_idempotent(self):
        _po, _r, bill = self._create_po_receive_bill(qty_boxes=2.0, price=580.50)
        self._deliver(self.product, 6.0)
        bill._vst_run_rebuild("uat rebuild")
        layers1 = len(bill.vst_layer_ids)
        allocs1 = self.env["petspot.vendor.sell.through.allocation"].search_count(
            [("vendor_bill_id", "=", bill.id), ("active", "=", True)]
        )
        eligible1 = bill.vst_eligible_amount
        bill._vst_run_rebuild("uat rebuild")
        bill._vst_run_rebuild("uat rebuild")
        self.assertEqual(len(bill.vst_layer_ids), layers1)
        allocs2 = self.env["petspot.vendor.sell.through.allocation"].search_count(
            [("vendor_bill_id", "=", bill.id), ("active", "=", True)]
        )
        self.assertEqual(allocs1, allocs2)
        self._assert_money(bill.vst_eligible_amount, eligible1)
