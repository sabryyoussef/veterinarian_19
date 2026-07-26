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
        self.assertEqual(infos.product_code, "900585")
        # Marketplace vendor_drug_size_id must never become supplierinfo product_code
        self.assertFalse(
            self.env["product.supplierinfo"].search(
                [
                    ("vetution_origin", "=", "vetution_supplier"),
                    ("product_code", "=", "900075"),
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
