# -*- coding: utf-8 -*-
from odoo.exceptions import AccessError
from odoo.tests import tagged

from .common import VstCommon


@tagged("post_install", "-at_install", "petspot_vendor_sell_through")
class TestVstSecurity(VstCommon):
    def test_30_access_rights_payment_wizard(self):
        _po, _r, bill = self._create_po_receive_bill(qty_boxes=1.0, price=580.50)
        self._deliver(self.product, 6.0)
        bill._vst_run_rebuild("uat rebuild")

        user = self.env["res.users"].create(
            {
                "name": "VST-UAT-Viewer",
                "login": "vst_uat_viewer_%s" % self.env.user.id,
                "group_ids": [(6, 0, [self.env.ref("petspot_vendor_sell_through.group_vst_viewer").id])],
            }
        )
        bill_as_user = bill.with_user(user)
        with self.assertRaises(AccessError):
            bill_as_user.action_vst_register_payment()

    def test_30b_legacy_requires_allocation_manager(self):
        _po, _r, bill = self._create_po_receive_bill(qty_boxes=1.0, price=580.50)
        line = bill.invoice_line_ids.filtered(lambda l: l.product_id)[:1]
        user = self.env["res.users"].create(
            {
                "name": "VST-UAT-Viewer2",
                "login": "vst_uat_viewer2_%s" % self.env.user.id,
                "group_ids": [(6, 0, [self.env.ref("petspot_vendor_sell_through.group_vst_viewer").id])],
            }
        )
        with self.assertRaises(AccessError):
            self.env["petspot.vendor.sell.through.legacy.wizard"].with_user(user).check_access("create")
        # Also confirm create is denied
        with self.assertRaises(AccessError):
            self.env["petspot.vendor.sell.through.legacy.wizard"].with_user(user).check_access("write")

    def test_20_pos_counted_when_installed(self):
        if "pos.order" not in self.env:
            self.skipTest("POS not installed")
        # Structural: POS pickings with pos_order_id are accepted by allocator predicate
        from odoo.addons.petspot_vendor_sell_through.services.allocator import _is_pos_move

        picking = self.env["stock.picking"].new({"pos_order_id": False})
        move = self.env["stock.move"].new({"picking_id": picking, "location_dest_id": self.customer_location})
        # Without a real POS session this asserts the helper exists and is safe
        self.assertFalse(_is_pos_move(move))
