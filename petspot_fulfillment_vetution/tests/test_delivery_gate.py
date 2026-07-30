# -*- coding: utf-8 -*-
"""Delivery price-review gate tests (Phase 15B) — shadow only, mocked ShipBlu."""

from unittest.mock import MagicMock, patch

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.petspot_fulfillment_vetution.services.landed_cost_engine import (
    LandedCostEngine,
)


@tagged("post_install", "-at_install", "petspot_fulfillment_vetution")
class TestDeliveryGate(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.policy = cls.env["petspot.vetution.landed.cost.policy"].create(
            {
                "name": "DG Test Policy",
                "version": "dg-test",
                "supplier_shipping_mode": "included",
                "tax_mode": "exempt",
                "risk_return_allowance_status": "verified_zero",
                "handling_status": "verified_zero",
                "default_payment_method": "bank_transfer",
                "default_packaging_type": "small_box",
                "customer_delivery_charge_amount": 118.0,
                "customer_delivery_charge_status": "configured",
                "max_auto_delivery_subsidy": 0.0,
            }
        )
        Pkg = cls.env["petspot.vetution.packaging.cost"]
        Pkg.create(
            {
                "policy_id": cls.policy.id,
                "packaging_type": "small_box",
                "amount": 5.0,
                "status": "configured",
            }
        )
        Fee = cls.env["petspot.vetution.payment.fee"]
        Fee.create(
            {
                "policy_id": cls.policy.id,
                "payment_method": "bank_transfer",
                "status": "verified_zero",
            }
        )

    def _fake_shipblu(self, base):
        fake = MagicMock()
        fake.base_fee = base
        fake.size_surcharge = 0.0
        fake.pickup_surcharge = 0.0
        fake.discount = 0.0
        fake.cod_fee = 0.0
        fake.pricing_source = "contract"
        fake.notes = []
        fake.to_dict.return_value = {"base_fee": base}
        return fake

    def _require_backend(self):
        if not self.env["shipblu.backend"].sudo().search([], limit=1):
            self.skipTest("no shipblu backend configured on this DB")

    def test_giza_to_giza_passes_gate(self):
        """Giza -> Giza carrier ~95 vs 118 charge => subsidy 0, gate passes."""
        self._require_backend()
        with patch(
            "odoo.addons.petspot_shipblu_base.services.cost_engine.CostEngine.compute",
            return_value=self._fake_shipblu(95.0),
        ):
            res = LandedCostEngine(self.env, self.policy).compute(
                supplier_cost=13.0,
                context={
                    "requested_fulfillment": "shipblu_delivery",
                    "destination_governorate": "Giza",
                    "package_size_code": "small",
                    "payment_method": "bank_transfer",
                },
            )
        self.assertTrue(res.delivery_gate_passed)
        self.assertNotEqual(res.delivery_decision_code, "DELIVERY_PRICE_REVIEW_REQUIRED")
        self.assertEqual(res.delivery_subsidy, 0.0)

    def test_giza_to_north_coast_fails_gate(self):
        """Giza -> North Coast carrier 196 vs 118 charge => subsidy 78, gate FAILS."""
        self._require_backend()
        with patch(
            "odoo.addons.petspot_shipblu_base.services.cost_engine.CostEngine.compute",
            return_value=self._fake_shipblu(196.0),
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
        self.assertFalse(res.delivery_gate_passed)
        self.assertEqual(res.delivery_decision_code, "DELIVERY_PRICE_REVIEW_REQUIRED")
        self.assertAlmostEqual(res.delivery_subsidy, 78.0)
        # Break-even proposed charge = carrier + fees + max_auto_subsidy(0)
        self.assertAlmostEqual(res.proposed_delivery_charge, 196.0)

    def test_subsidy_never_added_to_product_landed(self):
        self._require_backend()
        with patch(
            "odoo.addons.petspot_shipblu_base.services.cost_engine.CostEngine.compute",
            return_value=self._fake_shipblu(196.0),
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
        # Product landed = supplier(13) + packaging(5) only — subsidy(78) excluded.
        self.assertAlmostEqual(res.product_landed_cost, 18.0)

    def test_configurable_subsidy_threshold_allows_pass(self):
        self._require_backend()
        self.policy.max_auto_delivery_subsidy = 100.0
        try:
            with patch(
                "odoo.addons.petspot_shipblu_base.services.cost_engine.CostEngine.compute",
                return_value=self._fake_shipblu(196.0),
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
            self.assertTrue(res.delivery_gate_passed)
            self.assertAlmostEqual(res.proposed_delivery_charge, 196.0 + 100.0)
        finally:
            self.policy.max_auto_delivery_subsidy = 0.0

    def test_store_pickup_never_triggers_gate(self):
        res = LandedCostEngine(self.env, self.policy).compute(
            supplier_cost=13.0, context={"requested_fulfillment": "store_pickup"}
        )
        self.assertTrue(res.delivery_gate_passed)
