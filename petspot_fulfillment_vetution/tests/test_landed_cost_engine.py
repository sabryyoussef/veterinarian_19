# -*- coding: utf-8 -*-
"""Landed-cost engine tests — shadow only, mocked externals."""

import uuid
from unittest.mock import MagicMock, patch

from odoo import fields
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.petspot_fulfillment_vetution.services.landed_cost_engine import (
    LandedCostEngine,
)


@tagged("post_install", "-at_install", "petspot_fulfillment_vetution")
class TestLandedCostEngine(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.policy = cls.env["petspot.vetution.landed.cost.policy"].search(
            [("active", "=", True), ("is_synthetic_test", "=", False)], limit=1
        )
        if not cls.policy:
            cls.policy = cls.env["petspot.vetution.landed.cost.policy"].create(
                {"name": "LC Test", "version": "t"}
            )
        cls.policy.write(
            {
                "pricing_method": "gross_margin",
                "target_gross_margin_percent": 25.0,
                "min_gross_margin_percent": 20.0,
                "min_gross_profit_amount": 50.0,
                "allow_auto_quotation": False,
                "allow_price_publish": False,
                "supplier_shipping_mode": "unknown",
                "tax_mode": "unknown",
                "handling_status": "unknown",
                "risk_return_allowance_status": "unknown",
                "default_payment_method": "unknown",
                "default_packaging_type": False,
                "default_destination_governorate": False,
                "default_package_size_code": False,
            }
        )

    def _engine(self):
        return LandedCostEngine(self.env, self.policy)

    def test_supplier_cost_only_incomplete(self):
        res = self._engine().compute(supplier_cost=13.0, context={})
        self.assertTrue(res.landed_cost_incomplete)
        self.assertIn("supplier_shipping", res.missing_keys)
        self.assertLess(res.completeness_percent, 100)
        self.assertEqual(res.decision_code, "INSUFFICIENT_COST_DATA")
        self.assertEqual(res.pricing_confidence_percent, 40.0)

    def test_supplier_shipping_unknown_never_zero(self):
        self.policy.supplier_shipping_mode = "unknown"
        res = self._engine().compute(supplier_cost=13.0, context={})
        ship = res.component_map()["supplier_shipping"]
        self.assertEqual(ship.status, "unknown")
        self.assertIsNone(ship.amount)

    def test_shipblu_unavailable_without_destination(self):
        res = self._engine().compute(
            supplier_cost=13.0,
            context={"requested_fulfillment": "shipblu_delivery", "package_size_code": "1"},
        )
        self.assertEqual(res.component_map()["shipblu_shipping"].status, "unknown")

    def test_package_size_unknown_blocks_shipblu(self):
        res = self._engine().compute(
            supplier_cost=13.0,
            context={
                "requested_fulfillment": "shipblu_delivery",
                "destination_governorate": "Cairo",
            },
        )
        self.assertEqual(res.component_map()["shipblu_shipping"].status, "unknown")
        self.assertIn("package_size", res.component_map()["shipblu_shipping"].source)

    def test_store_pickup_shipblu_not_applicable(self):
        res = self._engine().compute(
            supplier_cost=13.0,
            context={"requested_fulfillment": "store_pickup"},
        )
        self.assertEqual(res.component_map()["shipblu_shipping"].status, "not_applicable")
        self.assertEqual(res.component_map()["cod_commission"].status, "not_applicable")

    def test_packaging_configured(self):
        Pkg = self.env["petspot.vetution.packaging.cost"]
        row = Pkg.search(
            [("policy_id", "=", self.policy.id), ("packaging_type", "=", "small_box")],
            limit=1,
        )
        if not row:
            row = Pkg.create(
                {
                    "policy_id": self.policy.id,
                    "packaging_type": "small_box",
                    "amount": 8.0,
                    "status": "configured",
                }
            )
        else:
            row.write({"amount": 8.0, "status": "configured"})
        self.policy.default_packaging_type = "small_box"
        res = self._engine().compute(supplier_cost=13.0, context={"packaging_type": "small_box"})
        self.assertEqual(res.component_map()["packaging"].amount, 8.0)
        self.assertEqual(res.component_map()["packaging"].status, "configured")

    def test_payment_fee_configured(self):
        Fee = self.env["petspot.vetution.payment.fee"]
        fee = Fee.search(
            [("policy_id", "=", self.policy.id), ("payment_method", "=", "paymob")],
            limit=1,
        )
        if not fee:
            fee = Fee.create(
                {
                    "policy_id": self.policy.id,
                    "payment_method": "paymob",
                    "percent": 2.5,
                    "fixed_amount": 0.0,
                    "status": "configured",
                }
            )
        else:
            fee.write({"percent": 2.5, "status": "configured"})
        res = self._engine().compute(
            supplier_cost=100.0,
            context={"payment_method": "paymob", "estimated_collect_amount": 100.0},
        )
        self.assertAlmostEqual(res.component_map()["payment_gateway_fee"].amount, 2.5)

    def test_tax_configured_exclusive(self):
        self.policy.write(
            {
                "tax_mode": "exclusive",
                "non_recoverable_tax_status": "configured",
                "non_recoverable_tax_rate": 14.0,
            }
        )
        res = self._engine().compute(supplier_cost=100.0, context={})
        self.assertAlmostEqual(res.component_map()["tax"].amount, 14.0)
        self.policy.write({"tax_mode": "unknown", "non_recoverable_tax_status": "unknown"})

    def test_return_provision_percent(self):
        self.policy.write(
            {
                "risk_return_allowance_status": "configured",
                "risk_mode": "percent",
                "risk_return_allowance_rate": 2.0,
            }
        )
        res = self._engine().compute(supplier_cost=100.0, context={})
        risk = res.component_map()["return_risk"]
        self.assertAlmostEqual(risk.amount, 2.0)
        self.assertTrue(risk.expected)

    def test_handling_configured(self):
        self.policy.write({"handling_status": "configured", "handling_amount": 15.0})
        res = self._engine().compute(supplier_cost=13.0, context={})
        self.assertEqual(res.component_map()["handling"].amount, 15.0)
        self.policy.handling_status = "unknown"

    def _complete_policy_store_pickup(self):
        """Configure all components known without ShipBlu."""
        Pkg = self.env["petspot.vetution.packaging.cost"]
        row = Pkg.search(
            [("policy_id", "=", self.policy.id), ("packaging_type", "=", "small_box")],
            limit=1,
        )
        if row:
            row.write({"amount": 5.0, "status": "configured"})
        else:
            Pkg.create(
                {
                    "policy_id": self.policy.id,
                    "packaging_type": "small_box",
                    "amount": 5.0,
                    "status": "configured",
                }
            )
        Fee = self.env["petspot.vetution.payment.fee"]
        fee = Fee.search(
            [("policy_id", "=", self.policy.id), ("payment_method", "=", "bank_transfer")],
            limit=1,
        )
        if fee:
            fee.write({"percent": 0.0, "fixed_amount": 0.0, "status": "verified_zero"})
        else:
            Fee.create(
                {
                    "policy_id": self.policy.id,
                    "payment_method": "bank_transfer",
                    "status": "verified_zero",
                }
            )
        self.policy.write(
            {
                "supplier_shipping_mode": "included",
                "tax_mode": "exempt",
                "risk_return_allowance_status": "verified_zero",
                "handling_status": "verified_zero",
                "default_packaging_type": "small_box",
                "default_payment_method": "bank_transfer",
            }
        )

    def test_complete_landed_cost(self):
        self._complete_policy_store_pickup()
        res = self._engine().compute(
            supplier_cost=13.0,
            context={
                "requested_fulfillment": "store_pickup",
                "packaging_type": "small_box",
                "payment_method": "bank_transfer",
            },
        )
        self.assertFalse(res.landed_cost_incomplete)
        self.assertEqual(res.completeness_percent, 100.0)
        self.assertAlmostEqual(res.landed_cost, 18.0)  # 13 + 5 packaging
        self.assertEqual(res.decision_code, "READY_FOR_AUTO_QUOTE")
        self.assertEqual(res.pricing_confidence_percent, 100.0)

    def test_incomplete_landed_cost(self):
        self.policy.write(
            {
                "supplier_shipping_mode": "unknown",
                "tax_mode": "unknown",
                "handling_status": "unknown",
                "risk_return_allowance_status": "unknown",
            }
        )
        res = self._engine().compute(supplier_cost=13.0, context={})
        self.assertTrue(res.landed_cost_incomplete)
        self.assertLess(res.completeness_percent, 100)

    def test_pricing_confidence_one_estimate(self):
        self._complete_policy_store_pickup()
        # Force one estimate by mocking shipblu path with delivery
        fake_bd = MagicMock()
        fake_bd.base_fee = 40.0
        fake_bd.size_surcharge = 5.0
        fake_bd.pickup_surcharge = 0.0
        fake_bd.discount = 0.0
        fake_bd.cod_fee = 0.0
        fake_bd.pricing_source = "manual"
        fake_bd.notes = []
        fake_bd.to_dict.return_value = {"base_fee": 40.0, "total": 45.0}

        with patch(
            "odoo.addons.petspot_shipblu_base.services.cost_engine.CostEngine.compute",
            return_value=fake_bd,
        ):
            # Need a backend
            if "shipblu.backend" in self.env and self.env["shipblu.backend"].sudo().search([], limit=1):
                res = self._engine().compute(
                    supplier_cost=13.0,
                    context={
                        "requested_fulfillment": "shipblu_delivery",
                        "destination_governorate": "Cairo",
                        "package_size_code": "1",
                        "payment_method": "bank_transfer",
                        "packaging_type": "small_box",
                    },
                )
                self.assertIn("shipblu_shipping", res.estimate_keys)
                self.assertEqual(res.pricing_confidence_percent, 80.0)
                self.assertEqual(res.pricing_confidence_label, "One estimate")

    def test_decision_matrix_and_report(self):
        res = self._engine().compute(supplier_cost=13.0, context={})
        lines = res.report_lines()
        self.assertTrue(any("Supplier Cost" in x for x in lines))
        self.assertTrue(any("Completeness" in x for x in lines))
        self.assertTrue(any("Decision" in x for x in lines))
        self.assertIn(res.decision_code, {
            "INSUFFICIENT_COST_DATA",
            "BLOCK_PRICE_PUBLISH",
            "SHADOW_ONLY",
            "READY_FOR_MANUAL_REVIEW",
            "READY_FOR_AUTO_QUOTE",
        })

    def test_shadow_assessment_uses_engine_no_side_effects(self):
        """Inquiry assessment remains shadow — no SO."""
        self._complete_policy_store_pickup()
        connection = self.env["vetution.connection"].sudo().search([], limit=1)
        if not connection:
            connection = self.env["vetution.connection"].sudo().create(
                {"name": "LC Conn", "state": "connected"}
            )
        tmpl = self.env["product.template"].create(
            {"name": "LC Prod", "list_price": 100.0, "type": "consu"}
        )
        product = tmpl.product_variant_id
        product.write({"default_code": "TEST-LC-001", "vetution_size_id": 991000101})
        self.env["vetution.supplier.offer"].create(
            {
                "connection_id": connection.id,
                "offer_type": "vetution",
                "product_id": product.id,
                "vetution_drug_id": 9910101,
                "vetution_size_id": 991000101,
                "drug_slug": "lc-test",
                "effective_cost": 13.0,
                "supplier_user_price": 13.0,
                "show": True,
                "show_price": True,
                "supplier_qty": 5,
                "availability_state": "available",
                "last_commercial_sync_at": fields.Datetime.now(),
                "is_stale": False,
            }
        )
        self.env["petspot.vetution.automation.allowlist"].add_exact_mapping(
            product, proof_note="test exact size"
        )
        inquiry = self.env["petspot.availability.inquiry"].create(
            {
                "phone": "+201000000099",
                "product_id": product.id,
                "default_code": product.default_code,
                "channel": "manual",
                "requested_fulfillment": "store_pickup",
                "idempotency_key": f"lc-{uuid.uuid4()}",
            }
        )
        a = self.env["petspot.vetution.shadow.assessment"].assess_inquiry(inquiry)
        self.assertFalse(a.landed_cost_incomplete)
        self.assertTrue(a.completeness_percent >= 100)
        self.assertTrue(a.gate_block_auto_quotation)
        self.assertTrue(a.gate_block_odoo_price_update)
        self.assertTrue(a.gate_block_shopify_publish)
        self.assertTrue(a.gate_block_supplier_purchase)
        self.assertFalse(inquiry.sale_order_id)
        self.assertTrue(a.landed_cost_report)
