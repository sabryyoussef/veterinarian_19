# -*- coding: utf-8 -*-
"""Cost-validation scenarios — shadow only, no transactional side effects."""

import uuid
from unittest.mock import MagicMock, patch

from odoo import fields
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.petspot_fulfillment_vetution.services.landed_cost_engine import LandedCostEngine


@tagged("post_install", "-at_install", "petspot_fulfillment_vetution")
class TestCostValidation(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.policy = cls.env["petspot.vetution.landed.cost.policy"].search(
            [("active", "=", True)], limit=1
        )
        if not cls.policy:
            cls.policy = cls.env["petspot.vetution.landed.cost.policy"].create(
                {"name": "CV", "version": "t"}
            )
        cls.policy.write(
            {
                "supplier_shipping_mode": "unknown",
                "tax_mode": "unknown",
                "handling_status": "unknown",
                "risk_return_allowance_status": "unknown",
                "default_payment_method": "unknown",
                "default_packaging_type": False,
                "default_origin_governorate": "Giza",
                "default_destination_governorate": "Giza",
                "default_package_size_code": "small",
                "allow_auto_quotation": False,
                "allow_price_publish": False,
            }
        )

    def test_payment_unknown_keeps_cod_unknown(self):
        res = LandedCostEngine(self.env, self.policy).compute(
            supplier_cost=13.0,
            context={
                "requested_fulfillment": "shipblu_delivery",
                "destination_governorate": "Giza",
                "package_size_code": "small",
                "payment_method": "unknown",
            },
        )
        self.assertEqual(res.component_map()["cod_commission"].status, "unknown")
        self.assertEqual(res.component_map()["payment_gateway_fee"].status, "unknown")

    def test_store_pickup_shipblu_na_completeness(self):
        res = LandedCostEngine(self.env, self.policy).compute(
            supplier_cost=13.0,
            context={"requested_fulfillment": "store_pickup"},
        )
        self.assertEqual(res.component_map()["shipblu_shipping"].status, "not_applicable")
        # N/A counts toward completeness
        self.assertGreaterEqual(res.completeness_percent, 33.0)
        self.assertIn("supplier_shipping", res.missing_keys)

    def test_supplier_shipping_included(self):
        self.policy.supplier_shipping_mode = "included"
        res = LandedCostEngine(self.env, self.policy).compute(
            supplier_cost=13.0, context={"requested_fulfillment": "store_pickup"}
        )
        self.assertEqual(res.component_map()["supplier_shipping"].status, "verified_zero")
        self.policy.supplier_shipping_mode = "unknown"

    def test_tax_conflicted_path_marked_unknown_when_mode_unknown(self):
        self.policy.tax_mode = "unknown"
        res = LandedCostEngine(self.env, self.policy).compute(supplier_cost=13.0, context={})
        self.assertEqual(res.component_map()["tax"].status, "unknown")

    def test_double_fee_prevention_cod(self):
        """COD uses cod_commission; payment_gateway_fee must be N/A."""
        fake = MagicMock()
        fake.base_fee = 95.0
        fake.size_surcharge = 0.0
        fake.pickup_surcharge = 0.0
        fake.discount = 0.0
        fake.cod_fee = 0.33
        fake.pricing_source = "contract"
        fake.notes = []
        fake.to_dict.return_value = {"base_fee": 95.0, "cod_fee": 0.33}
        if not self.env["shipblu.backend"].sudo().search([], limit=1):
            self.skipTest("no shipblu backend")
        with patch(
            "odoo.addons.petspot_shipblu_base.services.cost_engine.CostEngine.compute",
            return_value=fake,
        ):
            res = LandedCostEngine(self.env, self.policy).compute(
                supplier_cost=13.0,
                context={
                    "requested_fulfillment": "shipblu_delivery",
                    "destination_governorate": "Giza",
                    "package_size_code": "small",
                    "payment_method": "cod",
                    "estimated_collect_amount": 65.0,
                },
            )
        self.assertEqual(res.component_map()["payment_gateway_fee"].status, "not_applicable")
        self.assertEqual(res.component_map()["cod_commission"].status, "estimated")

    def test_pricing_formula_uses_landed(self):
        # With incomplete costs, suggested still from partial landed worksheet
        br = self.policy.compute_landed_cost(
            13.0, context={"requested_fulfillment": "store_pickup"}
        )
        sale = self.policy.compute_suggested_sale_price(br["landed_cost"])
        # profit floor 13+50=63 -> 65
        self.assertEqual(sale["suggested_price"], 65.0)
        self.assertTrue(br["landed_cost_incomplete"])

    def test_mapping_review_sku_no_side_effects(self):
        product = self.env["product.product"].create(
            {"name": "No Map", "default_code": f"TEST-NOMAP-{uuid.uuid4().hex[:6]}", "list_price": 10}
        )
        inq = self.env["petspot.availability.inquiry"].create(
            {
                "phone": "+201000000077",
                "product_id": product.id,
                "default_code": product.default_code,
                "channel": "manual",
                "idempotency_key": f"cv-{uuid.uuid4()}",
            }
        )
        a = self.env["petspot.vetution.shadow.assessment"].assess_inquiry(inq)
        self.assertEqual(a.state, "review")
        self.assertFalse(inq.sale_order_id)
