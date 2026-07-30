# -*- coding: utf-8 -*-
import uuid
from datetime import timedelta

from odoo import fields
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install", "petspot_fulfillment_vetution")
class TestVetutionShadowAssessment(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Policy = cls.env["petspot.vetution.landed.cost.policy"]
        cls.policy = cls.Policy.search([("active", "=", True)], limit=1)
        if not cls.policy:
            cls.policy = cls.Policy.create({"name": "Test Policy", "version": "t"})
        # Complete costs for baseline happy path tests
        cls.policy.write(
            {
                "pricing_method": "gross_margin",
                "target_gross_margin_percent": 25.0,
                "min_gross_margin_percent": 20.0,
                "min_gross_profit_amount": 50.0,
                "max_price_increase_percent": 10.0,
                "max_price_decrease_percent": 10.0,
                "price_rounding": 5.0,
                "rounding_mode": "nearest",
                "stale_after_hours_shadow": 12.0,
                "stale_after_hours_auto_quote": 2.0,
                "allow_on_demand_refresh": False,
                "allow_price_publish": False,
                "supplier_delivery_status": "verified_zero",
                "supplier_delivery_allocation": 0.0,
                "non_recoverable_tax_status": "verified_zero",
                "payment_fee_status": "verified_zero",
                "packaging_handling_status": "verified_zero",
                "risk_return_allowance_status": "verified_zero",
                "optional_fixed_cost_status": "verified_zero",
                "supplier_shipping_mode": "included",
                "tax_mode": "exempt",
                "handling_status": "verified_zero",
                "default_payment_method": "bank_transfer",
                "default_packaging_type": "small_box",
            }
        )
        Pkg = cls.env["petspot.vetution.packaging.cost"]
        pkg = Pkg.search([("policy_id", "=", cls.policy.id), ("packaging_type", "=", "small_box")], limit=1)
        if pkg:
            pkg.write({"amount": 0.0, "status": "verified_zero"})
        else:
            Pkg.create({"policy_id": cls.policy.id, "packaging_type": "small_box", "amount": 0.0, "status": "verified_zero"})
        Fee = cls.env["petspot.vetution.payment.fee"]
        fee = Fee.search([("policy_id", "=", cls.policy.id), ("payment_method", "=", "bank_transfer")], limit=1)
        if fee:
            fee.write({"status": "verified_zero", "percent": 0.0, "fixed_amount": 0.0})
        else:
            Fee.create({"policy_id": cls.policy.id, "payment_method": "bank_transfer", "status": "verified_zero"})

        cls.connection = cls.env["vetution.connection"].sudo().search([], limit=1)
        if not cls.connection:
            cls.connection = cls.env["vetution.connection"].sudo().create(
                {"name": "Test Vetution Conn", "state": "connected"}
            )
        cls.tmpl = cls.env["product.template"].create(
            {"name": "Shadow Test Drug", "list_price": 100.0, "type": "consu"}
        )
        cls.product = cls.tmpl.product_variant_id
        cls.product.write({"default_code": "TEST-SHADOW-001", "vetution_size_id": 991000001})
        cls.offer = cls.env["vetution.supplier.offer"].create(
            {
                "connection_id": cls.connection.id,
                "offer_type": "vetution",
                "product_id": cls.product.id,
                "vetution_drug_id": 9910001,
                "vetution_size_id": 991000001,
                "drug_slug": "shadow-test-drug",
                "size_name": "1 pcs",
                "supplier_price": 50.0,
                "supplier_user_price": 50.0,
                "effective_cost": 50.0,
                "show": True,
                "show_price": True,
                "supplier_qty": 10.0,
                "availability_state": "available",
                "last_seen_at": fields.Datetime.now(),
                "last_commercial_sync_at": fields.Datetime.now(),
                "is_stale": False,
                "active_for_procurement": True,
            }
        )
        cls.Inquiry = cls.env["petspot.availability.inquiry"]
        cls.env["petspot.vetution.automation.allowlist"].add_exact_mapping(
            cls.product,
            proof_note="Test fixture: product.vetution_size_id == offer.vetution_size_id == 991000001",
        )

    def _make_inquiry(self, product=None, **extra):
        vals = {
            "phone": "+201000000001",
            "product_id": (product or self.product).id,
            "default_code": (product or self.product).default_code,
            "requested_qty": 1.0,
            "channel": "manual",
            "requested_fulfillment": "store_pickup",
            "idempotency_key": f"test-shadow-{uuid.uuid4()}",
        }
        vals.update(extra)
        return self.Inquiry.create(vals)

    def test_exact_mapping_fresh_available(self):
        inquiry = self._make_inquiry()
        a = self.env["petspot.vetution.shadow.assessment"].assess_inquiry(inquiry)
        self.assertEqual(a.resolution_method, "vetution_size_id")
        self.assertFalse(a.landed_cost_incomplete)
        self.assertEqual(a.state, "ok")
        # 50/0.75=66.67, max with 100=100, nearest 5 = 100; margin 50%
        self.assertEqual(a.suggested_price, 100.0)
        self.assertFalse(inquiry.sale_order_id)

    def test_gross_margin_formula_and_rounding(self):
        # Isolate supplier-only path (store pickup) so ShipBlu estimate does not inflate landed
        # cost 13 -> 13/0.75=17.333, max(17.333, 63)=63 -> nearest 5 = 65
        br = self.policy.compute_landed_cost(
            13.0, context={"requested_fulfillment": "store_pickup"}
        )
        sale = self.policy.compute_suggested_sale_price(br["landed_cost"])
        self.assertAlmostEqual(sale["suggested_price"], 65.0)
        margin = (sale["suggested_price"] - br["landed_cost"]) / sale["suggested_price"] * 100
        self.assertGreaterEqual(margin, 20.0 - 1e-6)

    def test_missing_delivery_marks_incomplete(self):
        self.policy.supplier_shipping_mode = "unknown"
        inquiry = self._make_inquiry()
        a = self.env["petspot.vetution.shadow.assessment"].assess_inquiry(inquiry)
        self.assertTrue(a.landed_cost_incomplete)
        self.assertIn("supplier_shipping", a.missing_cost_components or "")
        self.assertTrue(a.gate_block_auto_quotation)
        self.policy.supplier_shipping_mode = "included"

    def test_price_change_9_vs_11(self):
        # suggested for cost 50 is 100; set list 92 -> ~8.7% increase OK path
        self.tmpl.list_price = 92.0
        inquiry = self._make_inquiry()
        a = self.env["petspot.vetution.shadow.assessment"].assess_inquiry(inquiry)
        self.assertFalse(a.price_review_required)
        # list 88 -> 100 is ~13.6% > 10%
        self.tmpl.list_price = 88.0
        a2 = self.env["petspot.vetution.shadow.assessment"].assess_inquiry(inquiry)
        self.assertTrue(a2.price_review_required)
        self.tmpl.list_price = 100.0

    def test_missing_size_routes_to_review(self):
        product = self.env["product.product"].create(
            {"name": "No Size", "default_code": "TEST-NOSIZE", "list_price": 10.0}
        )
        a = self.env["petspot.vetution.shadow.assessment"].assess_inquiry(
            self._make_inquiry(product=product)
        )
        self.assertEqual(a.state, "review")

    def test_stale_blocks(self):
        self.offer.write(
            {
                "last_commercial_sync_at": fields.Datetime.now() - timedelta(hours=62),
                "is_stale": True,
            }
        )
        a = self.env["petspot.vetution.shadow.assessment"].assess_inquiry(self._make_inquiry())
        self.assertEqual(a.state, "stale")

    def test_zero_cost_blocked(self):
        self.offer.write({"effective_cost": 0.0, "supplier_user_price": 0.0, "supplier_price": 0.0})
        a = self.env["petspot.vetution.shadow.assessment"].assess_inquiry(self._make_inquiry())
        self.assertTrue(a.suggested_price == 0 or a.landed_cost_incomplete or a.state != "ok")

    def test_idempotent_reassess(self):
        inquiry = self._make_inquiry()
        a1 = self.env["petspot.vetution.shadow.assessment"].assess_inquiry(inquiry)
        a2 = self.env["petspot.vetution.shadow.assessment"].assess_inquiry(inquiry)
        self.assertEqual(a1.id, a2.id)

    def test_no_list_price_write(self):
        old = self.tmpl.list_price
        self.env["petspot.vetution.shadow.assessment"].assess_inquiry(self._make_inquiry())
        self.assertEqual(self.tmpl.list_price, old)

    def test_concurrent_refresh_lock(self):
        Lock = self.env["petspot.vetution.refresh.lock"]
        ok1, lock1 = Lock.try_acquire(self.connection, "shadow-test-drug", lock_seconds=60)
        self.assertTrue(ok1)
        ok2, lock2 = Lock.try_acquire(self.connection, "shadow-test-drug", lock_seconds=60)
        self.assertFalse(ok2)
        lock1.release(success=True)
