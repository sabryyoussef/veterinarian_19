# -*- coding: utf-8 -*-

from odoo.tests import tagged

from .common import VetutionSupplierCommon, SAMPLE_DRUG


@tagged("post_install", "-at_install", "vetution_supplier")
class TestSupplierinfo(VetutionSupplierCommon):
    def test_mirror_primary_only_no_duplicates(self):
        metrics = {}
        self.Sync.process_drug(self.connection, SAMPLE_DRUG, metrics, dry_run=False)
        self.Sync.process_drug(self.connection, SAMPLE_DRUG, {}, dry_run=False)
        infos = self.env["product.supplierinfo"].search(
            [
                ("vetution_origin", "=", "vetution_supplier"),
                ("product_id", "=", self.variant.id),
            ]
        )
        self.assertEqual(len(infos), 1)
        self.assertAlmostEqual(infos.price, 1959)
        self.assertEqual(infos.partner_id, self.partner)
        # Marketplace must not create supplierinfo
        vendor_infos = self.env["product.supplierinfo"].search(
            [("product_code", "=", "75"), ("vetution_origin", "=", "vetution_supplier")]
        )
        # vendor_drug_size_id 75 should not be used as product_code for marketplace
        # Primary uses vetution_size_id 585
        self.assertFalse(
            self.env["product.supplierinfo"].search(
                [
                    ("vetution_origin", "=", "vetution_supplier"),
                    ("product_code", "=", "75"),
                ]
            )
        )

    def test_no_stock_quant_change(self):
        Quant = self.env["stock.quant"]
        before_count = Quant.search_count([])
        before_sum = sum(Quant.search([]).mapped("quantity"))
        before_qty_available = self.variant.qty_available
        self.Sync.process_drug(self.connection, SAMPLE_DRUG, {}, dry_run=False)
        after_count = Quant.search_count([])
        after_sum = sum(Quant.search([]).mapped("quantity"))
        self.assertEqual(before_count, after_count)
        self.assertEqual(before_sum, after_sum)
        self.assertEqual(before_qty_available, self.variant.qty_available)
        # list_price untouched
        self.assertEqual(self.variant.list_price, 1.0)
