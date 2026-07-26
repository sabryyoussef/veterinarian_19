# -*- coding: utf-8 -*-

from odoo.exceptions import AccessError
from odoo.tests import tagged

from .common import VetutionSupplierCommon, SAMPLE_DRUG


@tagged("post_install", "-at_install", "vetution_supplier")
class TestSecurity(VetutionSupplierCommon):
    def test_public_cannot_read_offers(self):
        public = self.env.ref("base.public_user")
        self.Sync.process_drug(self.connection, SAMPLE_DRUG, {}, dry_run=False)
        with self.assertRaises(AccessError):
            self.Offer.with_user(public).search([])

    def test_purchase_user_can_read_offer_cost(self):
        self.Sync.process_drug(self.connection, SAMPLE_DRUG, {}, dry_run=False)
        Purchase = self.env.ref("purchase.group_purchase_user")
        # Use admin who also has purchase — validates read ACL path.
        admin = self.env.ref("base.user_admin")
        self.assertTrue(admin.has_group("purchase.group_purchase_user") or admin.has_group("base.group_system"))
        offers = self.Offer.with_user(admin).search(
            [("vetution_size_id", "=", 900585), ("offer_type", "=", "vetution")],
            limit=1,
        )
        self.assertTrue(offers)
        self.assertEqual(offers.effective_cost, 1959)
        # Confirm ACL row exists for purchase users
        access = self.env["ir.model.access"].search(
            [
                ("model_id.model", "=", "vetution.supplier.offer"),
                ("group_id", "=", Purchase.id),
                ("perm_read", "=", True),
            ],
            limit=1,
        )
        self.assertTrue(access)

    def test_connection_acl_system_only(self):
        """No ACL grants for portal/public on vetution.connection."""
        Access = self.env["ir.model.access"]
        bad = Access.search(
            [
                ("model_id.model", "=", "vetution.connection"),
                ("group_id", "in", [
                    self.env.ref("base.group_portal").id,
                    self.env.ref("base.group_public").id,
                    self.env.ref("purchase.group_purchase_user").id,
                ]),
            ]
        )
        self.assertFalse(bad)
        good = Access.search(
            [
                ("model_id.model", "=", "vetution.connection"),
                ("group_id", "=", self.env.ref("base.group_system").id),
            ]
        )
        self.assertTrue(good)
