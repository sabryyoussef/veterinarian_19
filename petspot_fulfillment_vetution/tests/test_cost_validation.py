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


    def test_supplier_shipping_missing(self):
        self.policy.supplier_shipping_mode = "unknown"
        res = LandedCostEngine(self.env, self.policy).compute(supplier_cost=13.0, context={})
        self.assertEqual(res.component_map()["supplier_shipping"].status, "unknown")
        self.assertIsNone(res.component_map()["supplier_shipping"].amount)

    def test_shipblu_missing_without_package(self):
        prev = self.policy.default_package_size_code
        self.policy.default_package_size_code = False
        res = LandedCostEngine(self.env, self.policy).compute(
            supplier_cost=13.0,
            context={
                "requested_fulfillment": "shipblu_delivery",
                "destination_governorate": "Giza",
            },
        )
        self.assertEqual(res.component_map()["shipblu_shipping"].status, "unknown")
        self.policy.default_package_size_code = prev

    def test_packaging_missing(self):
        self.policy.default_packaging_type = False
        res = LandedCostEngine(self.env, self.policy).compute(
            supplier_cost=13.0, context={"requested_fulfillment": "store_pickup"}
        )
        self.assertEqual(res.component_map()["packaging"].status, "unknown")

    def test_packaging_verified(self):
        Pkg = self.env["petspot.vetution.packaging.cost"]
        row = Pkg.search(
            [("policy_id", "=", self.policy.id), ("packaging_type", "=", "small_box")], limit=1
        )
        if row:
            row.write({"amount": 7.0, "status": "configured"})
        else:
            Pkg.create({
                "policy_id": self.policy.id,
                "packaging_type": "small_box",
                "amount": 7.0,
                "status": "configured",
            })
        res = LandedCostEngine(self.env, self.policy).compute(
            supplier_cost=13.0,
            context={"requested_fulfillment": "store_pickup", "packaging_type": "small_box"},
        )
        self.assertEqual(res.component_map()["packaging"].amount, 7.0)

    def test_tax_exclusive_configured(self):
        self.policy.write({
            "tax_mode": "exclusive",
            "non_recoverable_tax_status": "configured",
            "non_recoverable_tax_rate": 15.0,
        })
        res = LandedCostEngine(self.env, self.policy).compute(supplier_cost=100.0, context={})
        self.assertAlmostEqual(res.component_map()["tax"].amount, 15.0)
        self.policy.write({"tax_mode": "unknown", "non_recoverable_tax_status": "unknown"})

    def test_tax_inclusive_no_double_count(self):
        self.policy.write({
            "tax_mode": "inclusive",
            "non_recoverable_tax_status": "configured",
            "non_recoverable_tax_rate": 15.0,
        })
        res = LandedCostEngine(self.env, self.policy).compute(supplier_cost=100.0, context={})
        self.assertEqual(res.component_map()["tax"].amount, 0.0)
        self.policy.write({"tax_mode": "unknown", "non_recoverable_tax_status": "unknown"})

    def test_return_risk_missing(self):
        self.policy.risk_return_allowance_status = "unknown"
        res = LandedCostEngine(self.env, self.policy).compute(supplier_cost=13.0, context={})
        self.assertEqual(res.component_map()["return_risk"].status, "unknown")

    def test_handling_missing(self):
        self.policy.handling_status = "unknown"
        res = LandedCostEngine(self.env, self.policy).compute(supplier_cost=13.0, context={})
        self.assertEqual(res.component_map()["handling"].status, "unknown")

    def test_handling_fixed(self):
        self.policy.write({"handling_status": "configured", "handling_amount": 12.0})
        res = LandedCostEngine(self.env, self.policy).compute(supplier_cost=13.0, context={})
        self.assertEqual(res.component_map()["handling"].amount, 12.0)
        self.policy.handling_status = "unknown"

    def test_na_does_not_reduce_completeness_unfairly(self):
        """Store pickup: ShipBlu+COD are N/A and count as known."""
        res = LandedCostEngine(self.env, self.policy).compute(
            supplier_cost=13.0, context={"requested_fulfillment": "store_pickup"}
        )
        self.assertNotIn("shipblu_shipping", res.missing_keys)
        self.assertNotIn("cod_commission", res.missing_keys)

    def test_critical_missing_blocks_high_confidence(self):
        res = LandedCostEngine(self.env, self.policy).compute(supplier_cost=13.0, context={})
        self.assertEqual(res.pricing_confidence_percent, 40.0)
        self.assertEqual(res.decision_code, "INSUFFICIENT_COST_DATA")

    def test_complete_store_pickup_scenario(self):
        Pkg = self.env["petspot.vetution.packaging.cost"]
        row = Pkg.search(
            [("policy_id", "=", self.policy.id), ("packaging_type", "=", "small_box")], limit=1
        )
        if row:
            row.write({"amount": 5.0, "status": "configured"})
        else:
            Pkg.create({
                "policy_id": self.policy.id,
                "packaging_type": "small_box",
                "amount": 5.0,
                "status": "configured",
            })
        Fee = self.env["petspot.vetution.payment.fee"]
        fee = Fee.search(
            [("policy_id", "=", self.policy.id), ("payment_method", "=", "bank_transfer")],
            limit=1,
        )
        if fee:
            fee.write({"status": "verified_zero", "percent": 0.0, "fixed_amount": 0.0})
        else:
            Fee.create({
                "policy_id": self.policy.id,
                "payment_method": "bank_transfer",
                "status": "verified_zero",
            })
        self.policy.write({
            "supplier_shipping_mode": "included",
            "tax_mode": "exempt",
            "risk_return_allowance_status": "verified_zero",
            "handling_status": "verified_zero",
        })
        res = LandedCostEngine(self.env, self.policy).compute(
            supplier_cost=13.0,
            context={
                "requested_fulfillment": "store_pickup",
                "packaging_type": "small_box",
                "payment_method": "bank_transfer",
            },
        )
        self.assertFalse(res.landed_cost_incomplete)
        self.assertEqual(res.completeness_percent, 100.0)
        self.assertEqual(res.decision_code, "READY_FOR_AUTO_QUOTE")
        # restore unknowns for other tests
        self.policy.write({
            "supplier_shipping_mode": "unknown",
            "tax_mode": "unknown",
            "risk_return_allowance_status": "unknown",
            "handling_status": "unknown",
        })

    def test_margin_and_profit_floors_and_rounding(self):
        sale = self.policy.compute_suggested_sale_price(13.0)
        self.assertEqual(sale["suggested_price"], 65.0)  # max(17.33, 63)=63 -> 65
        sale2 = self.policy.compute_suggested_sale_price(200.0)
        # margin floor 200/0.75=266.67, profit 250 -> 266.67 -> nearest 5 = 265 or 270?
        # round(266.67/5)*5 = round(53.334)*5 = 53*5 = 265
        self.assertEqual(sale2["suggested_price"], 265.0)
        margin = (sale2["suggested_price"] - 200.0) / sale2["suggested_price"] * 100
        self.assertGreaterEqual(margin, 20.0 - 1e-6)

    def test_zero_side_effects_locks(self):
        self.assertFalse(self.policy.allow_auto_quotation)
        self.assertFalse(self.policy.allow_price_publish)
        self.assertFalse(self.policy.allow_customer_message)
        self.assertFalse(self.policy.allow_supplier_po)


    def test_delivery_charge_not_in_product_landed(self):
        """Giza→Giza prepaid: ShipBlu 95 recovered via 118 charge; product excludes full ShipBlu."""
        self.policy.write({
            "customer_delivery_charge_amount": 118.0,
            "customer_delivery_charge_status": "configured",
        })
        fake = MagicMock()
        fake.base_fee = 95.0
        fake.size_surcharge = 0.0
        fake.pickup_surcharge = 0.0
        fake.discount = 0.0
        fake.cod_fee = 0.0
        fake.pricing_source = "contract"
        fake.notes = []
        fake.to_dict.return_value = {"base_fee": 95.0}
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
                    "payment_method": "paymob",
                },
            )
        self.assertEqual(res.component_map()["shipblu_shipping"].amount, 95.0)
        self.assertEqual(res.customer_delivery_charge, 118.0)
        self.assertAlmostEqual(res.delivery_profit_or_subsidy, 23.0)
        self.assertEqual(res.delivery_shortfall, 0.0)
        # Product landed must NOT include 95
        self.assertLess(res.product_landed_cost, 95.0)
        self.assertIn("APPROVED_PROVISIONAL_ESTIMATE", " ".join(res.notes))

    def test_delivery_shortfall_when_shipblu_exceeds_charge(self):
        self.policy.write({
            "customer_delivery_charge_amount": 118.0,
            "customer_delivery_charge_status": "configured",
        })
        fake = MagicMock()
        fake.base_fee = 196.0  # Giza→North Coast
        fake.size_surcharge = 0.0
        fake.pickup_surcharge = 0.0
        fake.discount = 0.0
        fake.cod_fee = 0.0
        fake.pricing_source = "contract"
        fake.notes = []
        fake.to_dict.return_value = {"base_fee": 196.0}
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
                    "destination_governorate": "North Coast",
                    "package_size_code": "small",
                    "payment_method": "bank_transfer",
                },
            )
        self.assertAlmostEqual(res.delivery_profit_or_subsidy, 118.0 - 196.0)
        self.assertAlmostEqual(res.delivery_shortfall, 78.0)
        # Shortfall included in product landed; full 196 is not
        self.assertGreaterEqual(res.product_landed_cost, 13.0 + 78.0 - 1e-6)
        self.assertLess(res.product_landed_cost, 13.0 + 196.0)

    def test_giza_pickup_delivery_revenue_zero(self):
        res = LandedCostEngine(self.env, self.policy).compute(
            supplier_cost=13.0,
            context={"requested_fulfillment": "store_pickup"},
        )
        self.assertEqual(res.component_map()["shipblu_shipping"].status, "not_applicable")
        self.assertEqual(res.component_map()["cod_commission"].status, "not_applicable")
        self.assertEqual(res.customer_delivery_charge, 0.0)
        self.assertEqual(res.delivery_shortfall, 0.0)
