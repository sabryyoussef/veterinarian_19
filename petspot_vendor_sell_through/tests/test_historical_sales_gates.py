# -*- coding: utf-8 -*-
"""Regression gates for historical-sales / WH-OUT classification / equivalence rules."""

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.petspot_vendor_sell_through.services.allocator import allocate_outgoing_move
from odoo.addons.petspot_vendor_sell_through.services.product_equivalence import (
    DIFFERENT_STRENGTH_OR_PACK,
    INSUFFICIENT_EVIDENCE,
    SAFE_EXACT_DUPLICATE,
    classify_product_pair,
)
from odoo.addons.petspot_vendor_sell_through.tests.common import VstCommon


@tagged("post_install", "-at_install", "petspot_vendor_sell_through")
class TestHistoricalSalesGates(VstCommon):
    def test_vendor_destination_outgoing_excluded_from_sale_allocation(self):
        _po, _receipt, bill = self._create_po_receive_bill(qty_boxes=1.0, price=580.50)
        suppliers = self.env.ref("stock.stock_location_suppliers")
        # Mimic WH/OUT supplier-return style move (internal → vendor)
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": self.picking_type_out.id,
                "location_id": self.stock_location.id,
                "location_dest_id": suppliers.id,
                "partner_id": self.partner.id,
            }
        )
        move = self.env["stock.move"].create(
            {
                "description_picking": "Vendor-dest outgoing",
                "product_id": self.product.id,
                "product_uom_qty": 6.0,
                "product_uom": self.product.uom_id.id,
                "picking_id": picking.id,
                "location_id": self.stock_location.id,
                "location_dest_id": suppliers.id,
            }
        )
        picking.action_confirm()
        move.quantity = 6.0
        if not move.move_line_ids:
            self.env["stock.move.line"].create(
                {
                    "move_id": move.id,
                    "product_id": self.product.id,
                    "product_uom_id": self.product.uom_id.id,
                    "quantity": 6.0,
                    "location_id": self.stock_location.id,
                    "location_dest_id": suppliers.id,
                    "picking_id": picking.id,
                }
            )
        picking.button_validate()
        allocate_outgoing_move(self.env, move)
        bill._vst_run_rebuild("uat rebuild")
        sale_allocs = self.env["petspot.vendor.sell.through.allocation"].search(
            [
                ("vendor_bill_id", "=", bill.id),
                ("outgoing_move_id", "=", move.id),
                ("source_kind", "=", "system"),
                ("active", "=", True),
            ]
        )
        self.assertFalse(sale_allocs, "Vendor-destination moves must not create sale allocations")
        self.assertEqual(bill.vst_eligible_amount, 0.0)

    def test_customer_destination_outgoing_included(self):
        _po, _receipt, bill = self._create_po_receive_bill(qty_boxes=1.0, price=580.50)
        self._deliver(self.product, 6.0)
        bill._vst_run_rebuild("uat rebuild")
        self.assertGreater(bill.vst_eligible_amount, 0.0)
        allocs = self.env["petspot.vendor.sell.through.allocation"].search(
            [
                ("vendor_bill_id", "=", bill.id),
                ("source_kind", "=", "system"),
                ("active", "=", True),
            ]
        )
        self.assertTrue(allocs)
        self.assertTrue(all(a.outgoing_move_id.location_dest_id.usage == "customer" for a in allocs))

    def test_strength_pack_mismatch_rejected(self):
        p36 = self.env["product.product"].create(
            {
                "name": "Apoquel",
                "default_code": "APOQ-3.6",
                "type": "consu",
                "is_storable": True,
                "uom_id": self.uom_chew.id,
            }
        )
        p16 = self.env["product.product"].create(
            {
                "name": "Apoquel",
                "default_code": "APOQ-16",
                "type": "consu",
                "is_storable": True,
                "uom_id": self.uom_chew.id,
            }
        )
        cls, reasons = classify_product_pair(p36, p16)
        self.assertEqual(cls, DIFFERENT_STRENGTH_OR_PACK)
        self.assertTrue(reasons)

        loose = self.env["product.product"].create(
            {
                "name": "simparica trio 2.5 - 5 kg",
                "type": "consu",
                "is_storable": True,
                "uom_id": self.env.ref("uom.product_uom_unit").id,
            }
        )
        coded = self.product  # VST-UAT-SIMT-2.5-5 on Chew UoM
        cls2, _ = classify_product_pair(loose, coded)
        self.assertIn(cls2, (INSUFFICIENT_EVIDENCE, DIFFERENT_STRENGTH_OR_PACK))
        self.assertNotEqual(cls2, SAFE_EXACT_DUPLICATE)

    def test_safe_exact_duplicate_requires_barcode_and_uom(self):
        # Use new() to avoid unique barcode DB constraint while classifying equivalence
        a = self.env["product.product"].new(
            {
                "name": "Dup A",
                "default_code": "SAFE-DUP-A",
                "barcode": "VST-SAFE-BARCODE-001",
                "type": "consu",
                "is_storable": True,
                "uom_id": self.uom_chew.id,
            }
        )
        b = self.env["product.product"].new(
            {
                "name": "Dup B alias",
                "default_code": "SAFE-DUP-B",
                "barcode": "VST-SAFE-BARCODE-001",
                "type": "consu",
                "is_storable": True,
                "uom_id": self.uom_chew.id,
            }
        )
        # Codes have no conflicting strength tokens → barcode+uom qualifies
        cls, _ = classify_product_pair(a, b)
        self.assertEqual(cls, SAFE_EXACT_DUPLICATE)

    def test_legacy_cannot_exceed_billed_qty_via_rebuild_cap(self):
        _po, _receipt, bill = self._create_po_receive_bill(qty_boxes=1.0, price=580.50)
        line = bill.invoice_line_ids.filtered(lambda l: l.product_id)[:1]
        # 1 box = 6 chews billed; attempt legacy 12 chews
        wiz = self.env["petspot.vendor.sell.through.legacy.wizard"].create(
            {
                "vendor_bill_id": bill.id,
                "vendor_bill_line_id": line.id,
                "qty": 12.0,
                "uom_id": self.uom_chew.id,
                "evidence_ref": "VST-LEGACY-OVER",
                "reason": "Over-billed attempt should still be capped by metrics",
                "approve": True,
            }
        )
        wiz.action_confirm()
        bill._vst_run_rebuild("uat rebuild")
        # Payment suggestion must never exceed residual (cash safety gate)
        self.assertLessEqual(bill.vst_suggested_payment, bill.amount_residual + 0.01)

    def test_stock_then_legacy_no_double_count_payable(self):
        _po, _receipt, bill = self._create_po_receive_bill(qty_boxes=1.0, price=580.50)
        self._deliver(self.product, 6.0)
        bill._vst_run_rebuild("uat rebuild")
        stock_eligible = bill.vst_eligible_amount
        line = bill.invoice_line_ids.filtered(lambda l: l.product_id)[:1]
        # Legacy for same full qty — remaining layer free qty should be 0 so metrics stay capped
        self.env["petspot.vendor.sell.through.legacy.wizard"].create(
            {
                "vendor_bill_id": bill.id,
                "vendor_bill_line_id": line.id,
                "qty": 6.0,
                "uom_id": self.uom_chew.id,
                "evidence_ref": "VST-LEGACY-DUP",
                "reason": "Must not increase payable above stock-derived full sale",
                "approve": True,
            }
        ).action_confirm()
        bill._vst_run_rebuild("uat rebuild")
        # Suggested payment must not exceed residual (no double-pay cash out)
        self.assertLessEqual(bill.vst_suggested_payment, bill.amount_residual + 0.01)
        self.assertLessEqual(bill.vst_suggested_payment, stock_eligible + 0.01)

    def test_rebuild_idempotent_zero_drift(self):
        _po, _receipt, bill = self._create_po_receive_bill(qty_boxes=2.0, price=580.50)
        self._deliver(self.product, 6.0)
        bill._vst_run_rebuild("uat rebuild")
        snap1 = {
            "eligible": bill.vst_eligible_amount,
            "layers": bill.vst_layer_ids.ids,
            "alloc_qty": sum(
                self.env["petspot.vendor.sell.through.allocation"]
                .search([("vendor_bill_id", "=", bill.id), ("active", "=", True)])
                .mapped("qty_base")
            ),
        }
        bill._vst_run_rebuild("uat rebuild")
        bill._vst_run_rebuild("uat rebuild")
        snap2 = {
            "eligible": bill.vst_eligible_amount,
            "layers": bill.vst_layer_ids.ids,
            "alloc_qty": sum(
                self.env["petspot.vendor.sell.through.allocation"]
                .search([("vendor_bill_id", "=", bill.id), ("active", "=", True)])
                .mapped("qty_base")
            ),
        }
        self.assertAlmostEqual(snap1["eligible"], snap2["eligible"], places=2)
        self.assertEqual(len(snap1["layers"]), len(snap2["layers"]))
        self.assertAlmostEqual(snap1["alloc_qty"], snap2["alloc_qty"], places=6)

    def test_legacy_requires_evidence_fields(self):
        _po, _receipt, bill = self._create_po_receive_bill(qty_boxes=1.0, price=580.50)
        line = bill.invoice_line_ids.filtered(lambda l: l.product_id)[:1]
        with self.assertRaises(Exception):
            self.env["petspot.vendor.sell.through.legacy.wizard"].create(
                {
                    "vendor_bill_id": bill.id,
                    "vendor_bill_line_id": line.id,
                    "qty": 1.0,
                    "uom_id": self.uom_chew.id,
                    # missing evidence_ref + reason
                }
            ).action_confirm()
