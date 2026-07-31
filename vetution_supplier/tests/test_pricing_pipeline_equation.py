# -*- coding: utf-8 -*-
"""Unit tests for shared pricing pipeline equation."""

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.vetution_supplier.pricing_pipeline.equation import (
    PLACEHOLDER_MAX,
    ceil_to_next_multiple_of_5,
    compute_final_sale_price,
    is_valid_landed_cost,
    shopify_price_from_odoo_reread,
)


@tagged("post_install", "-at_install", "vetution_pricing_pipeline")
class TestPricingPipelineEquation(TransactionCase):
    def test_ceil_never_rounds_down(self):
        self.assertEqual(ceil_to_next_multiple_of_5(130), 130)
        self.assertEqual(ceil_to_next_multiple_of_5(130.01), 135)
        self.assertEqual(ceil_to_next_multiple_of_5(1), 5)

    def test_le1_never_valid_landed_cost(self):
        self.assertFalse(is_valid_landed_cost(1))
        self.assertFalse(is_valid_landed_cost(1.0))
        self.assertFalse(is_valid_landed_cost(PLACEHOLDER_MAX))
        self.assertFalse(is_valid_landed_cost(0))
        self.assertTrue(is_valid_landed_cost(1.02))
        self.assertTrue(is_valid_landed_cost(80))

    def test_equation_examples_from_spec(self):
        self.assertEqual(compute_final_sale_price(80)["final_price"], 130)
        self.assertEqual(compute_final_sale_price(120)["final_price"], 170)
        self.assertEqual(compute_final_sale_price(1000)["final_price"], 1200)

    def test_rejects_le1_landed_cost(self):
        r = compute_final_sale_price(1.0)
        self.assertFalse(r["ok"])
        self.assertEqual(r["reason"], "invalid_landed_cost_le1_or_below")

    def test_ignores_le1_existing_floor(self):
        r = compute_final_sale_price(80, existing_activated_sale=1.0)
        self.assertEqual(r["final_price"], 130)
        self.assertIsNone(r["existing_floor"])

    def test_preserves_higher_activated_floor(self):
        r = compute_final_sale_price(80, existing_activated_sale=200)
        self.assertEqual(r["final_price"], 200)

    def test_never_below_landed_cost(self):
        r = compute_final_sale_price(500)
        self.assertGreaterEqual(r["final_price"], 500)
        self.assertFalse(r["below_cost"])
        self.assertTrue(r["margin_ok"])

    def test_shopify_receives_odoo_reread_only(self):
        self.assertEqual(shopify_price_from_odoo_reread(150.0), "150.00")
        self.assertIsNone(shopify_price_from_odoo_reread(1.0))
        self.assertEqual(shopify_price_from_odoo_reread(100), "100.00")

    def test_mapping_ambiguity_guard_documented(self):
        # Ambiguous mappings must not call compute_final_sale_price with guessed cost.
        self.assertFalse(is_valid_landed_cost(None))
