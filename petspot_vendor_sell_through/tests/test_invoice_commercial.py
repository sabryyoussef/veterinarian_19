# -*- coding: utf-8 -*-
"""Invoice-derived commercial sell-through regression suite."""

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tools import float_compare

from .common import VstCommon
from odoo.addons.petspot_vendor_sell_through.services.invoice_commercial import (
    allocate_invoice_commercial_for_bill,
    backfill_company,
)
from odoo.addons.petspot_vendor_sell_through.services.product_equivalence import classify_product_pair
from odoo.addons.petspot_vendor_sell_through.services.uom_util import convert_qty


@tagged("post_install", "-at_install", "petspot_vendor_sell_through")
class TestVstInvoiceCommercial(VstCommon):
    def _post_customer_invoice(self, product, qty, price=200.0, cancel_delivery=True):
        so = self.env["sale.order"].create(
            {
                "partner_id": self.customer.id,
                "order_line": [
                    (
                        0,
                        0,
                        {
                            "product_id": product.id,
                            "product_uom_qty": qty,
                            "price_unit": price,
                        },
                    )
                ],
            }
        )
        so.action_confirm()
        if cancel_delivery:
            for picking in so.picking_ids.filtered(lambda p: p.state not in ("done", "cancel")):
                picking.action_cancel()
        inv = so._create_invoices()
        if not inv.invoice_date:
            inv.invoice_date = fields.Date.context_today(self.env.user)
        inv.action_post()
        return so, inv

    def test_01_invoice_cancelled_delivery_counts(self):
        _po, _r, bill = self._create_po_receive_bill(qty_boxes=1.0, price=580.50)
        self._post_customer_invoice(self.product, 6.0, cancel_delivery=True)
        bill._vst_run_rebuild("invoice commercial")
        self._assert_money(bill.vst_eligible_amount, 580.50)
        src = self.env["petspot.vendor.sell.through.commercial.source"].search(
            [("product_id", "=", self.product.id), ("state", "=", "applied")]
        )
        self.assertTrue(src)
        self.assertEqual(src.reason, "POSTED_INVOICE_WITHOUT_DONE_CUSTOMER_DELIVERY")

    def test_02_invoice_plus_delivery_counted_once(self):
        _po, _r, bill = self._create_po_receive_bill(qty_boxes=1.0, price=580.50)
        so, inv = self._post_customer_invoice(self.product, 6.0, cancel_delivery=False)
        # Validate the delivery
        picking = so.picking_ids.filtered(lambda p: p.state not in ("done", "cancel"))[:1]
        if picking:
            for move in picking.move_ids:
                move.quantity = move.product_uom_qty
            picking.button_validate()
        bill._vst_run_rebuild("dedup")
        self._assert_money(bill.vst_eligible_amount, 580.50)
        system = self.env["petspot.vendor.sell.through.allocation"].search(
            [("vendor_bill_id", "=", bill.id), ("source_kind", "=", "system"), ("active", "=", True), ("is_return", "=", False)]
        )
        invoice = self.env["petspot.vendor.sell.through.allocation"].search(
            [("vendor_bill_id", "=", bill.id), ("source_kind", "=", "invoice"), ("active", "=", True)]
        )
        self.assertAlmostEqual(sum(system.mapped("qty_base")) + sum(invoice.mapped("qty_base")), 6.0, places=2)
        # Prefer stock; invoice residual should be zero when fully delivered
        self.assertTrue(float_compare(sum(system.mapped("qty_base")), 6.0, precision_digits=2) == 0 or sum(invoice.mapped("qty_base")) == 0)

    def test_03_partial_delivery_plus_full_invoice(self):
        _po, _r, bill = self._create_po_receive_bill(qty_boxes=2.0, price=580.50)
        so = self.env["sale.order"].create(
            {
                "partner_id": self.customer.id,
                "order_line": [
                    (0, 0, {"product_id": self.product.id, "product_uom_qty": 6.0, "price_unit": 200.0})
                ],
            }
        )
        so.action_confirm()
        picking = so.picking_ids[:1]
        for move in picking.move_ids:
            # Deliver only 2 chews
            move.quantity = 2.0
            if move.move_line_ids:
                move.move_line_ids.quantity = 2.0
        res = picking.button_validate()
        if isinstance(res, dict) and res.get("res_model") == "stock.backorder.confirmation":
            wiz = self.env[res["res_model"]].with_context(**res.get("context", {})).create({})
            wiz.process()
        inv = so._create_invoices()
        inv.invoice_date = fields.Date.context_today(self.env.user)
        inv.action_post()
        bill._vst_run_rebuild("partial")
        system_qty = sum(
            self.env["petspot.vendor.sell.through.allocation"]
            .search([("vendor_bill_id", "=", bill.id), ("source_kind", "=", "system"), ("active", "=", True), ("is_return", "=", False)])
            .mapped("qty_base")
        )
        invoice_qty = sum(
            self.env["petspot.vendor.sell.through.allocation"]
            .search([("vendor_bill_id", "=", bill.id), ("source_kind", "=", "invoice"), ("active", "=", True)])
            .mapped("qty_base")
        )
        self.assertAlmostEqual(system_qty + invoice_qty, 6.0, places=2)
        self.assertGreater(invoice_qty, 0.0)

    def test_04_refund_before_payment_reduces(self):
        _po, _r, bill = self._create_po_receive_bill(qty_boxes=1.0, price=580.50)
        so, inv = self._post_customer_invoice(self.product, 6.0)
        bill._vst_run_rebuild("before refund")
        self._assert_money(bill.vst_eligible_amount, 580.50)
        refund = inv._reverse_moves(default_values_list=[{"invoice_date": fields.Date.context_today(self.env.user)}])
        refund.action_post()
        bill._vst_run_rebuild("after refund")
        self._assert_money(bill.vst_eligible_amount, 0.0)

    def test_04b_corrective_invoice_reversing_credit_note_nets(self):
        """Invoice that reverses a credit note must net to zero with that refund (APOQ-16 pattern)."""
        _po, _r, bill = self._create_po_receive_bill(qty_boxes=2.0, price=580.50)
        so, inv = self._post_customer_invoice(self.product, 6.0)
        bill._vst_run_rebuild("seed")
        refund = inv._reverse_moves(default_values_list=[{"invoice_date": fields.Date.context_today(self.env.user)}])
        refund.action_post()
        # Corrective out_invoice reversing the credit note
        corrective = refund._reverse_moves(default_values_list=[{"invoice_date": fields.Date.context_today(self.env.user)}])
        corrective.action_post()
        self.assertEqual(corrective.reversed_entry_id, refund)
        bill._vst_run_rebuild("corrective pair")
        # Original sale still stands once; refund+corrective cancel
        self._assert_money(bill.vst_eligible_amount, 580.50)

    def test_05_refund_after_settled_blocks_or_zeros_unpaid(self):
        """Unpaid invoice-derived path: refund zeros allocation. Settled payment case stays unpaid-safe."""
        _po, _r, bill = self._create_po_receive_bill(qty_boxes=1.0, price=580.50)
        so, inv = self._post_customer_invoice(self.product, 6.0)
        bill._vst_run_rebuild("seed")
        # No supplier payment posted — refund must safely clear invoice allocation
        refund = inv._reverse_moves(default_values_list=[{"invoice_date": fields.Date.context_today(self.env.user)}])
        refund.action_post()
        bill._vst_run_rebuild("refund unpaid")
        self.assertLessEqual(bill.vst_eligible_amount, 0.01)

    def test_06_strip_tablet_box_conversion(self):
        # Box6 ↔ Chew already relative; 1 box = 6 chews
        q = convert_qty(self.uom_box6, 1.0, self.uom_chew, raise_if_failure=True)
        self.assertAlmostEqual(q, 6.0, places=4)
        q2 = convert_qty(self.uom_chew, 60.0, self.uom_box6, raise_if_failure=True)
        self.assertAlmostEqual(q2, 10.0, places=4)

    def test_07_apoq16_style_sixty_base_units(self):
        """60 base units against a 3-box×100-style bill: use 10 boxes of 6 = 60 chews → 10 bill units."""
        _po, _r, bill = self._create_po_receive_bill(qty_boxes=10.0, price=580.50)
        self._post_customer_invoice(self.product, 60.0)
        bill._vst_run_rebuild("sixty")
        invoice_alloc = self.env["petspot.vendor.sell.through.allocation"].search(
            [("vendor_bill_id", "=", bill.id), ("source_kind", "=", "invoice"), ("active", "=", True)]
        )
        self.assertAlmostEqual(sum(invoice_alloc.mapped("qty_base")), 60.0, places=2)
        # Eligible = 10 * 580.50
        self._assert_money(bill.vst_eligible_amount, 5805.0)

    def test_08_different_strength_blocked(self):
        other = self.env["product.product"].create(
            {
                "name": "Apoquel 3.6 mg",
                "default_code": "APOQ-3.6",
                "is_storable": True,
                "type": "consu",
                "uom_id": self.uom_chew.id,
            }
        )
        coded = self.env["product.product"].create(
            {
                "name": "Apoquel 16 mg",
                "default_code": "APOQ-16",
                "is_storable": True,
                "type": "consu",
                "uom_id": self.uom_chew.id,
            }
        )
        result, _reasons = classify_product_pair(other, coded)
        self.assertEqual(result, "DIFFERENT_STRENGTH_OR_PACK")

    def test_09_supplier_return_excluded(self):
        _po, receipt, bill = self._create_po_receive_bill(qty_boxes=2.0, price=580.50)
        ret = self.env["stock.picking"].create(
            {
                "picking_type_id": self.picking_type_in.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.env.ref("stock.stock_location_suppliers").id,
                "partner_id": self.partner.id,
            }
        )
        move = self.env["stock.move"].create(
            {
                "description_picking": "Vendor return",
                "product_id": self.product.id,
                "product_uom_qty": 6.0,
                "product_uom": self.product.uom_id.id,
                "picking_id": ret.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.env.ref("stock.stock_location_suppliers").id,
                "purchase_line_id": _po.order_line.id,
            }
        )
        ret.action_confirm()
        move.quantity = 6.0
        if not move.move_line_ids:
            self.env["stock.move.line"].create(
                {
                    "move_id": move.id,
                    "product_id": self.product.id,
                    "product_uom_id": self.product.uom_id.id,
                    "quantity": 6.0,
                    "location_id": self.stock_location.id,
                    "location_dest_id": self.env.ref("stock.stock_location_suppliers").id,
                    "picking_id": ret.id,
                }
            )
        ret.button_validate()
        # Invoice 12 chews but only 6 remain after supplier return
        self._post_customer_invoice(self.product, 12.0)
        bill._vst_run_rebuild("supplier return cap")
        self.assertLessEqual(bill.vst_eligible_amount, 580.50 + 0.01)

    def test_10_inventory_adjustment_excluded(self):
        _po, _r, bill = self._create_po_receive_bill(qty_boxes=1.0, price=580.50)
        quant = self.env["stock.quant"].with_context(inventory_mode=True).create(
            {
                "product_id": self.product.id,
                "location_id": self.stock_location.id,
                "inventory_quantity": 0.0,
            }
        )
        quant.action_apply_inventory()
        bill._vst_run_rebuild("inv adj")
        # No customer invoice → still zero
        self._assert_money(bill.vst_eligible_amount, 0.0)

    def test_11_oldest_eligible_across_bills(self):
        _po1, _r1, bill1 = self._create_po_receive_bill(qty_boxes=1.0, price=600.0)
        _po2, _r2, bill2 = self._create_po_receive_bill(qty_boxes=1.0, price=480.0)
        self._post_customer_invoice(self.product, 6.0)
        bill1._vst_run_rebuild("fifo1")
        bill2._vst_run_rebuild("fifo2")
        self._assert_money(bill1.vst_eligible_amount, 600.0)
        self._assert_money(bill2.vst_eligible_amount, 0.0)

    def test_12_full_payment_rebuild_zero_drift(self):
        _po, _r, bill = self._create_po_receive_bill(qty_boxes=1.0, price=580.50)
        self._post_customer_invoice(self.product, 6.0)
        bill._vst_run_rebuild("pay seed")
        eligible = bill.vst_eligible_amount
        journal = self.env["account.journal"].search(
            [("type", "in", ("bank", "cash")), ("company_id", "=", self.company.id)], limit=1
        )
        self.env["account.payment.register"].with_context(active_model="account.move", active_ids=bill.ids).create(
            {"amount": bill.amount_residual, "journal_id": journal.id}
        ).action_create_payments()
        bill._vst_run_rebuild("after pay")
        bill._vst_run_rebuild("after pay 2")
        self.assertAlmostEqual(bill.vst_eligible_amount, eligible, places=2)
        self.assertAlmostEqual(bill.vst_suggested_payment, 0.0, places=2)

    def test_13_rebuild_three_times_identical(self):
        _po, _r, bill = self._create_po_receive_bill(qty_boxes=1.0, price=580.50)
        self._post_customer_invoice(self.product, 6.0)
        snaps = []
        for i in range(3):
            bill._vst_run_rebuild("idem %s" % i)
            allocs = self.env["petspot.vendor.sell.through.allocation"].search(
                [("vendor_bill_id", "=", bill.id), ("active", "=", True), ("is_return", "=", False)]
            )
            snaps.append(
                (
                    round(bill.vst_eligible_amount, 2),
                    round(sum(allocs.mapped("qty_base")), 4),
                    len(allocs),
                    tuple(sorted(allocs.mapped("source_kind"))),
                )
            )
        self.assertEqual(snaps[0], snaps[1])
        self.assertEqual(snaps[1], snaps[2])

    def test_14_backfill_rerun_no_duplicate_sources(self):
        _po, _r, bill = self._create_po_receive_bill(qty_boxes=1.0, price=580.50)
        self._post_customer_invoice(self.product, 6.0)
        r1 = allocate_invoice_commercial_for_bill(self.env, bill, dry_run=False)
        r2 = allocate_invoice_commercial_for_bill(self.env, bill, dry_run=False)
        Source = self.env["petspot.vendor.sell.through.commercial.source"]
        keys = Source.search([("product_id", "=", self.product.id)]).mapped("source_key")
        self.assertEqual(len(keys), len(set(keys)))
        self.assertAlmostEqual(r1["allocated_qty_base"], r2["allocated_qty_base"], places=4)

    def test_15_dry_run_does_not_apply_allocations(self):
        _po, _r, bill = self._create_po_receive_bill(qty_boxes=1.0, price=580.50)
        self._post_customer_invoice(self.product, 6.0)
        before = self.env["petspot.vendor.sell.through.allocation"].search_count(
            [("vendor_bill_id", "=", bill.id), ("source_kind", "=", "invoice")]
        )
        report = allocate_invoice_commercial_for_bill(self.env, bill, dry_run=True)
        after = self.env["petspot.vendor.sell.through.allocation"].search_count(
            [("vendor_bill_id", "=", bill.id), ("source_kind", "=", "invoice")]
        )
        self.assertEqual(before, after)
        self.assertGreater(report["allocated_qty_base"], 0.0)
