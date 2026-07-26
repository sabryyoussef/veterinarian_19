# -*- coding: utf-8 -*-
"""Phase 3 pricing formula, locks, placeholder replacement, pilot limits."""

import math
from unittest.mock import patch

from odoo.tests.common import tagged

from .common import VetutionSupplierCommon


@tagged("post_install", "-at_install", "vetution_supplier")
class TestVetutionPricing(VetutionSupplierCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.connection.write(
            {
                "default_markup_percent": 20.0,
                "fixed_markup_amount": 0.0,
                "min_gross_margin_percent": 15.0,
                "min_gross_profit_amount": 50.0,
                "price_rounding": 5.0,
                "max_auto_price_change_percent": 5000.0,
            }
        )
        cls.Pricing = cls.env["vetution.pricing"]
        # Eligible primary offer for the synthetic test product
        cls.offer = cls.Offer.create(
            {
                "connection_id": cls.connection.id,
                "offer_type": "vetution",
                "vetution_drug_id": 900419,
                "drug_slug": "test-bravecto-phase1",
                "vetution_size_id": 900585,
                "size_name": "1 Tablet | 20-40 Kg",
                "product_id": cls.variant.id,
                "supplier_price": 1959.0,
                "effective_cost": 1959.0,
                "availability_state": "available",
                "active_for_procurement": True,
                "is_stale": False,
            }
        )

    def test_formula_markup_margin_profit_rounding(self):
        # cost 100 → markup 120, margin 100/0.85≈117.65, profit 150 → max=150 → round up 150
        b = self.connection.compute_sale_price(100.0)
        self.assertAlmostEqual(b["markup_price"], 120.0)
        self.assertAlmostEqual(b["minimum_margin_price"], 100.0 / 0.85)
        self.assertAlmostEqual(b["minimum_profit_price"], 150.0)
        self.assertAlmostEqual(b["candidate"], 150.0)
        self.assertEqual(b["selling_price"], 150.0)

        # cost 200 → markup 240, margin ≈235.29, profit 250 → 250
        b2 = self.connection.compute_sale_price(200.0)
        self.assertEqual(b2["selling_price"], 250.0)

        # cost 1000 → markup 1200 wins over margin≈1176.47 and profit 1050 → round 1200
        b3 = self.connection.compute_sale_price(1000.0)
        self.assertEqual(b3["selling_price"], 1200.0)

        # cost 1959 → markup 2350.8, margin≈2304.7, profit 2009 → ceil to 5 → 2355
        b4 = self.connection.compute_sale_price(1959.0)
        expected = math.ceil(1959.0 * 1.20 / 5.0 - 1e-9) * 5.0
        self.assertEqual(b4["selling_price"], expected)

    def test_locked_price_skipped(self):
        tmpl = self.variant.product_tmpl_id
        tmpl.list_price = 1.0
        tmpl.vetution_sale_price_locked = True
        with patch.object(
            type(self.env["vetution.commercial.sync"]),
            "assert_authentication",
            lambda *a, **k: True,
        ), patch.object(
            type(self.Pricing),
            "_assert_fresh_and_auth",
            lambda *a, **k: True,
        ):
            log = self.Pricing.activate_template_price(
                self.connection, tmpl, dry_run=False
            )
        self.assertTrue(log.skipped)
        self.assertEqual(log.skip_reason, "sale_price_locked")
        self.assertEqual(tmpl.list_price, 1.0)

    def test_placeholder_replacement_and_write(self):
        tmpl = self.variant.product_tmpl_id
        tmpl.write(
            {
                "list_price": 1.0,
                "vetution_sale_price_locked": False,
                "vetution_price_activated": False,
            }
        )
        quant_before = self.env["stock.quant"].search_count([])
        published = tmpl.is_published if "is_published" in tmpl._fields else None
        po_before = self.env["purchase.order"].search_count([])

        log = self.Pricing.activate_template_price(
            self.connection, tmpl, dry_run=False
        )
        self.assertFalse(log.skipped)
        self.assertTrue(log.placeholder_replacement)
        self.assertEqual(log.old_list_price, 1.0)
        expected = self.connection.preview_sale_price(1959.0)
        self.assertEqual(tmpl.list_price, expected)
        self.assertEqual(log.new_list_price, expected)
        self.assertTrue(tmpl.vetution_price_activated)
        self.assertEqual(self.env["stock.quant"].search_count([]), quant_before)
        self.assertEqual(self.env["purchase.order"].search_count([]), po_before)
        if published is not None:
            self.assertEqual(tmpl.is_published, published)

    def test_dry_run_does_not_write(self):
        tmpl = self.variant.product_tmpl_id
        tmpl.list_price = 1.0
        tmpl.vetution_price_activated = False
        log = self.Pricing.activate_template_price(
            self.connection, tmpl, dry_run=True
        )
        self.assertFalse(log.skipped)
        self.assertTrue(log.dry_run)
        self.assertEqual(tmpl.list_price, 1.0)
        self.assertFalse(tmpl.vetution_price_activated)

    def test_max_change_blocks_non_placeholder(self):
        tmpl = self.variant.product_tmpl_id
        tmpl.list_price = 100.0
        tmpl.vetution_sale_price_locked = False
        self.connection.max_auto_price_change_percent = 10.0
        log = self.Pricing.activate_template_price(
            self.connection, tmpl, dry_run=False
        )
        self.assertTrue(log.skipped)
        self.assertIn("exceeds", log.skip_reason)
        self.assertEqual(tmpl.list_price, 100.0)
        self.connection.max_auto_price_change_percent = 5000.0

    def test_pilot_limit_and_selection(self):
        with patch.object(
            type(self.Pricing),
            "_assert_fresh_and_auth",
            lambda *a, **k: True,
        ):
            selected = self.Pricing.select_pilot_templates(self.connection, limit=50)
            self.assertLessEqual(len(selected), 50)
            logs = self.Pricing.activate_pilot(
                self.connection,
                templates=self.variant.product_tmpl_id,
                dry_run=True,
                limit=50,
            )
            self.assertEqual(len(logs), 1)
