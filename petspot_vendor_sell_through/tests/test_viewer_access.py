# -*- coding: utf-8 -*-
"""Viewer open/read must not unlink or rebuild allocations."""

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import VstCommon


@tagged("post_install", "-at_install", "petspot_vendor_sell_through")
class TestVstViewerAccess(VstCommon):
    def _make_viewer(self):
        return self.env["res.users"].create(
            {
                "name": "VST Viewer Regression",
                "login": "vst_viewer_reg_%s" % self.env["ir.sequence"].next_by_code("base.group") or self.env.user.id,
                "group_ids": [
                    (
                        6,
                        0,
                        [
                            self.env.ref("base.group_user").id,
                            self.env.ref("account.group_account_invoice").id,
                            self.env.ref("purchase.group_purchase_user").id,
                            self.env.ref("petspot_vendor_sell_through.group_vst_viewer").id,
                        ],
                    )
                ],
            }
        )

    def test_viewer_opens_bill_without_access_error(self):
        _po, _r, bill = self._create_po_receive_bill(qty_boxes=1.0, price=580.50)
        self._deliver(self.product, 6.0)
        bill._vst_run_rebuild("seed")
        viewer = self._make_viewer()
        bill_v = bill.with_user(viewer)
        data = bill_v.read(
            [
                "name",
                "vst_eligible_amount",
                "vst_suggested_payment",
                "vst_sold_count",
                "vst_sold_line_ids",
            ]
        )
        self.assertTrue(data)
        if hasattr(bill_v, "web_read"):
            bill_v.web_read({})

    def test_viewer_reads_sold_items_and_smart_buttons(self):
        _po, _r, bill = self._create_po_receive_bill(qty_boxes=1.0, price=580.50)
        self._deliver(self.product, 6.0)
        bill._vst_run_rebuild("seed")
        viewer = self._make_viewer()
        bill_v = bill.with_user(viewer)
        self.assertTrue(bill_v.vst_sold_line_ids)
        self.assertTrue(bill_v.action_vst_open_allocations())
        self.assertTrue(bill_v.action_vst_open_receipts())
        self.assertTrue(bill_v.action_vst_open_sales())

    def test_opening_form_does_not_change_allocations(self):
        _po, _r, bill = self._create_po_receive_bill(qty_boxes=1.0, price=580.50)
        self._deliver(self.product, 6.0)
        bill._vst_run_rebuild("seed")
        Alloc = self.env["petspot.vendor.sell.through.allocation"]
        before = Alloc.search([("vendor_bill_id", "=", bill.id)])
        before_ids = before.ids
        before_wd = {a.id: a.write_date for a in before}
        viewer = self._make_viewer()
        bill.with_user(viewer).read(["vst_eligible_amount", "vst_sold_line_ids", "invoice_line_ids"])
        bill.with_user(viewer).action_vst_open_allocations()
        after = Alloc.search([("vendor_bill_id", "=", bill.id)])
        self.assertEqual(after.ids, before_ids)
        for a in after:
            self.assertEqual(a.write_date, before_wd[a.id])

    def test_payment_wizard_no_rebuild_for_payment_manager(self):
        _po, _r, bill = self._create_po_receive_bill(qty_boxes=1.0, price=580.50)
        self._deliver(self.product, 6.0)
        bill._vst_run_rebuild("seed")
        pay_user = self.env["res.users"].create(
            {
                "name": "VST Pay Mgr",
                "login": "vst_pay_mgr_%s" % id(self),
                "group_ids": [
                    (
                        6,
                        0,
                        [
                            self.env.ref("base.group_user").id,
                            self.env.ref("petspot_vendor_sell_through.group_vst_payment_manager").id,
                        ],
                    )
                ],
            }
        )
        Alloc = self.env["petspot.vendor.sell.through.allocation"]
        before_ids = Alloc.search([("vendor_bill_id", "=", bill.id)]).ids
        action = bill.with_user(pay_user).action_vst_register_payment()
        self.assertEqual(action["res_model"], "petspot.vendor.sell.through.payment.wizard")
        wiz = (
            self.env["petspot.vendor.sell.through.payment.wizard"]
            .with_user(pay_user)
            .create({"move_id": bill.id, "amount": bill.vst_suggested_payment})
        )
        self.assertFalse(wiz.confirm_post)
        after_ids = Alloc.search([("vendor_bill_id", "=", bill.id)]).ids
        self.assertEqual(after_ids, before_ids)

    def test_viewer_cannot_delete_or_rebuild(self):
        _po, _r, bill = self._create_po_receive_bill(qty_boxes=1.0, price=580.50)
        self._deliver(self.product, 6.0)
        bill._vst_run_rebuild("seed")
        viewer = self._make_viewer()
        alloc = self.env["petspot.vendor.sell.through.allocation"].search(
            [("vendor_bill_id", "=", bill.id)], limit=1
        )
        with self.assertRaises(AccessError):
            alloc.with_user(viewer).unlink()
        with self.assertRaises(AccessError):
            bill.with_user(viewer).action_vst_recompute()
        with self.assertRaises(AccessError):
            bill.with_user(viewer)._vst_run_rebuild("nope")

    def test_manager_rebuild_wizard_requires_reason_and_preserves_legacy(self):
        _po, _r, bill = self._create_po_receive_bill(qty_boxes=2.0, price=580.50)
        self._deliver(self.product, 6.0)
        bill._vst_run_rebuild("seed")
        line = bill.invoice_line_ids.filtered(lambda l: l.product_id)[:1]
        self.env["petspot.vendor.sell.through.legacy.wizard"].create(
            {
                "vendor_bill_id": bill.id,
                "vendor_bill_line_id": line.id,
                "qty": 1.0,
                "uom_id": self.uom_chew.id,
                "evidence_ref": "LEG-1",
                "reason": "history",
                "approve": True,
            }
        ).action_confirm()
        legacy = self.env["petspot.vendor.sell.through.allocation"].search(
            [("vendor_bill_id", "=", bill.id), ("status", "=", "approved_legacy")]
        )
        self.assertTrue(legacy)
        legacy_ids = legacy.ids
        action = bill.action_vst_recompute()
        self.assertEqual(action["res_model"], "petspot.vendor.sell.through.rebuild.wizard")
        wiz = self.env["petspot.vendor.sell.through.rebuild.wizard"].create(
            {"move_id": bill.id, "reason": "", "confirm": True}
        )
        with self.assertRaises(UserError):
            wiz.action_confirm_rebuild()
        wiz.write({"reason": "idempotent rebuild test", "confirm": False})
        with self.assertRaises(UserError):
            wiz.action_confirm_rebuild()
        wiz.write({"confirm": True})
        wiz.action_confirm_rebuild()
        legacy_after = self.env["petspot.vendor.sell.through.allocation"].search(
            [("vendor_bill_id", "=", bill.id), ("status", "=", "approved_legacy")]
        )
        self.assertEqual(set(legacy_after.ids), set(legacy_ids))
        # Idempotent second rebuild: no duplicate payable system qty beyond received
        bill._vst_run_rebuild("second rebuild")
        sold = sum(
            self.env["petspot.vendor.sell.through.allocation"]
            .search([("vendor_bill_id", "=", bill.id), ("active", "=", True), ("is_return", "=", False), ("status", "in", ("exact_fifo", "exact_lot"))])
            .mapped("qty_base")
        )
        self.assertAlmostEqual(sold, 6.0, places=2)

    def test_simparica_money_unchanged(self):
        _po, _r, bill = self._create_po_receive_bill(qty_boxes=30.0, price=580.50)
        self._deliver(self.product, 30.0)
        bill._vst_run_rebuild("5 boxes")
        self._assert_money(bill.vst_eligible_amount, 2902.50)
        self._deliver(self.product, 8.0)
        bill._vst_run_rebuild("8 chews")
        self._assert_money(bill.vst_eligible_amount, 3676.50)
