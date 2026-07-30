# -*- coding: utf-8 -*-
"""WorkflowEngine synthetic end-to-end + exception matrix tests (Phase 15B).

All live writes stay mocked/locked: no Chatwoot HTTP, no Shopify publish, no
live ShipBlu AWB creation. Exercises the synthetic TEST policy only, on this
explicitly allowlisted TEST database.
"""

from datetime import timedelta
from unittest.mock import MagicMock, patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.petspot_fulfillment_vetution.services.workflow_engine import WorkflowEngine
from odoo.addons.petspot_fulfillment_vetution.services.landed_cost_engine import LandedCostEngine


@tagged("post_install", "-at_install", "petspot_fulfillment_vetution", "petspot_ff_e2e")
class TestWorkflowEngineE2E(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.ICP = cls.env["ir.config_parameter"].sudo()
        cls.Policy = cls.env["petspot.vetution.landed.cost.policy"]

        cls.policy = cls.env.ref(
            "petspot_fulfillment_vetution.landed_cost_policy_synthetic_test",
            raise_if_not_found=False,
        )
        if not cls.policy:
            cls.policy = cls.Policy.search(
                [("name", "=", "TEST-SYNTHETIC-E2E-NOT-FOR-COMMERCE")], limit=1
            )
        if not cls.policy:
            raise AssertionError("synthetic TEST policy TEST-SYNTHETIC-E2E-NOT-FOR-COMMERCE missing")

        cls.policy.write(
            {
                "active": True,
                "is_synthetic_test": True,
                "allow_auto_quotation": True,
                "allow_customer_message": True,
                "allow_supplier_po": True,
                "max_auto_delivery_subsidy": 0.0,
            }
        )
        cls.others = cls.Policy.search(
            [("id", "!=", cls.policy.id), ("active", "=", True)]
        )
        cls.others.write({"active": False})

        cls.ICP.set_param(
            "petspot_fulfillment_vetution.synthetic_policy_allowed_dbs", cls.env.cr.dbname
        )
        cls.ICP.set_param("petspot_fulfillment_vetution.chatwoot_transport", "mock")
        cls.ICP.set_param("petspot_fulfillment_vetution.shipblu_create_transport", "mock")
        cls.ICP.set_param("petspot_fulfillment_vetution.shipblu_package_size_verified", "False")

        cls.partner = cls.env["res.partner"].create(
            {"name": "WFE Synthetic Customer", "phone": "+201000000055"}
        )
        cls.vendor = cls.env["res.partner"].create(
            {"name": "WFE Synthetic Vendor", "company_type": "company", "supplier_rank": 1}
        )

        cls.product = cls.env["product.product"].create(
            {
                "name": "WFE Synthetic Product",
                "default_code": "WFE-9001",
                # Within ±10% of synthetic recommended (~EGP 90) so price guards pass.
                "list_price": 85.0,
                "type": "consu",
            }
        )
        cls.product.vetution_size_id = 88888

        cls.connection = cls.env["vetution.connection"].search([("active", "=", True)], limit=1)
        if not cls.connection:
            cls.connection = cls.env["vetution.connection"].create(
                {"name": "WFE synthetic connection", "active": True}
            )

        Offer = cls.env["vetution.supplier.offer"]
        cls.offer = Offer.search([("vetution_size_id", "=", 88888)], limit=1)
        offer_vals = {
            "connection_id": cls.connection.id,
            "offer_type": "vetution",
            "vetution_size_id": 88888,
            "product_id": cls.product.id,
            "effective_cost": 13.0,
            "supplier_price": 13.0,
            "strike_price": 100.0,
            "availability_state": "available",
            "is_stale": False,
            "is_expired": False,
            "last_commercial_sync_at": fields.Datetime.now(),
            "last_seen_at": fields.Datetime.now(),
        }
        if cls.offer:
            cls.offer.write(offer_vals)
        else:
            cls.offer = Offer.create(offer_vals)

        Allow = cls.env["petspot.vetution.automation.allowlist"]
        if not Allow.is_product_allowed(cls.product):
            Allow.add_exact_mapping(cls.product, proof_note="WFE synthetic exact size 88888")

    def setUp(self):
        super().setUp()
        self.offer.write(
            {
                "effective_cost": 13.0,
                "availability_state": "available",
                "is_stale": False,
                "is_expired": False,
                "last_commercial_sync_at": fields.Datetime.now(),
            }
        )

    def _make_inquiry(self, fulfillment="store_pickup", product=None):
        product = product or self.product
        return self.env["petspot.availability.inquiry"].create(
            {
                "phone": self.partner.phone,
                "partner_id": self.partner.id,
                "product_id": product.id,
                "default_code": product.default_code,
                "requested_qty": 1.0,
                "requested_fulfillment": fulfillment,
                "channel": "manual",
                "conversation_id": f"wfe-conv-{fields.Datetime.now()}-{product.id}",
                "message_id": f"wfe-msg-{fields.Datetime.now()}-{product.id}",
            }
        )

    def _fake_shipblu(self, base=95.0):
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

    # ------------------------------------------------------------------ shadow / auto-quote
    def test_shadow_path_ok_and_eligible(self):
        inquiry = self._make_inquiry("store_pickup")
        assessment = WorkflowEngine(self.env).run_shadow_path(inquiry)
        self.assertEqual(assessment.state, "ok")
        self.assertTrue(assessment.eligible_future_automation)
        self.assertFalse(assessment.landed_cost_incomplete)

    def test_auto_quote_if_eligible_creates_ledger_and_is_idempotent(self):
        inquiry = self._make_inquiry("store_pickup")
        ledger1 = WorkflowEngine(self.env).run_auto_quote_if_eligible(inquiry)
        self.assertTrue(ledger1)
        self.assertEqual(ledger1.state, "sent")
        ledger2 = WorkflowEngine(self.env).run_auto_quote_if_eligible(inquiry)
        self.assertEqual(ledger1.id, ledger2.id)

    def test_missing_mapping_blocks_shadow(self):
        unmapped = self.env["product.product"].create(
            {"name": "WFE unmapped", "default_code": "WFE-UNMAPPED", "type": "consu"}
        )
        inquiry = self._make_inquiry("store_pickup", product=unmapped)
        assessment = WorkflowEngine(self.env).run_shadow_path(inquiry)
        self.assertEqual(assessment.state, "review")
        self.assertFalse(assessment.eligible_future_automation)

    def test_out_of_stock_blocks_eligibility(self):
        self.offer.availability_state = "out_of_stock"
        try:
            inquiry = self._make_inquiry("store_pickup")
            assessment = WorkflowEngine(self.env).run_shadow_path(inquiry)
            self.assertEqual(assessment.state, "unavailable")
            self.assertFalse(assessment.eligible_future_automation)
        finally:
            self.offer.availability_state = "available"

    def test_incomplete_real_cost_blocks_eligibility(self):
        self.policy.handling_status = "unknown"
        try:
            inquiry = self._make_inquiry("store_pickup")
            assessment = WorkflowEngine(self.env).run_shadow_path(inquiry)
            self.assertTrue(assessment.landed_cost_incomplete)
            self.assertFalse(assessment.eligible_future_automation)
        finally:
            self.policy.handling_status = "configured"

    def test_stale_offer_blocks_eligibility(self):
        self.offer.write(
            {
                "last_commercial_sync_at": fields.Datetime.now() - timedelta(hours=20),
                "last_seen_at": fields.Datetime.now() - timedelta(hours=20),
                "is_stale": True,
            }
        )
        self.policy.allow_on_demand_refresh = False
        try:
            inquiry = self._make_inquiry("store_pickup")
            assessment = WorkflowEngine(self.env).run_shadow_path(inquiry)
            self.assertIn(assessment.state, ("stale", "sync_failed"))
            self.assertFalse(assessment.eligible_future_automation)
        finally:
            self.policy.allow_on_demand_refresh = True
            self.offer.write(
                {
                    "last_commercial_sync_at": fields.Datetime.now(),
                    "last_seen_at": fields.Datetime.now(),
                    "is_stale": False,
                }
            )

    def test_north_coast_subsidy_blocks_via_engine(self):
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
                    "payment_method": "paymob",
                },
            )
        self.assertFalse(res.delivery_gate_passed)
        self.assertEqual(res.delivery_decision_code, "DELIVERY_PRICE_REVIEW_REQUIRED")

    def test_price_change_9_percent_within_band(self):
        ok, blockers, metrics = self.policy.evaluate_price_guards(
            suggested_price=109.0,
            landed_cost=60.0,
            current_odoo_price=100.0,
        )
        self.assertNotIn("excessive_price_increase", blockers)
        self.assertFalse(metrics["gates"]["price_review_required"])

    def test_price_change_11_percent_requires_review(self):
        ok, blockers, metrics = self.policy.evaluate_price_guards(
            suggested_price=111.0,
            landed_cost=60.0,
            current_odoo_price=100.0,
        )
        self.assertIn("excessive_price_increase", blockers)
        self.assertTrue(metrics["gates"]["price_review_required"])

    def test_negative_margin_blocked(self):
        ok, blockers, metrics = self.policy.evaluate_price_guards(
            suggested_price=50.0,
            landed_cost=60.0,
            current_odoo_price=50.0,
        )
        self.assertFalse(ok)
        self.assertIn("negative_margin", blockers)

    # ------------------------------------------------------------------ messaging
    def test_duplicate_cta_message_is_idempotent(self):
        inquiry = self._make_inquiry("store_pickup")
        engine = WorkflowEngine(self.env)
        first = engine.run_send_message(inquiry, "quotation_ready", {"product_price": 65.0})
        second = engine.run_send_message(inquiry, "quotation_ready", {"product_price": 65.0})
        self.assertEqual(first.id, second.id)
        self.assertEqual(first.transport, "mock")

    def test_send_message_blocked_when_flag_off(self):
        self.policy.allow_customer_message = False
        try:
            inquiry = self._make_inquiry("store_pickup")
            with self.assertRaises(UserError):
                WorkflowEngine(self.env).run_send_message(inquiry, "checking", {})
        finally:
            self.policy.allow_customer_message = True

    # ------------------------------------------------------------------ payment + case
    def _bind_case(self, inquiry, delivery_method="store_pickup"):
        Case = self.env["petspot.fulfillment.case"]
        case = Case.search([("inquiry_id", "=", inquiry.id)], limit=1)
        if not case:
            case = Case.create(
                {
                    "name": f"FF-WFE/{inquiry.id}",
                    "inquiry_id": inquiry.id,
                    "delivery_method": delivery_method,
                    "partner_id": self.partner.id,
                }
            )
            inquiry.case_id = case.id
        return case

    def test_payment_trust_cash_pickup_via_engine_and_duplicate(self):
        inquiry = self._make_inquiry("store_pickup")
        case = self._bind_case(inquiry)
        engine = WorkflowEngine(self.env)
        rec = engine.run_payment_trust(case, "cash_pickup", user=self.env.user)
        self.assertEqual(rec.state, "accepted")
        self.assertEqual(case.payment_status, "manual_paid")
        dup = engine.run_payment_trust(case, "cash_pickup", user=self.env.user)
        self.assertEqual(dup.state, "duplicate")

    def test_store_pickup_complete_requires_payment(self):
        inquiry = self._make_inquiry("store_pickup")
        case = self._bind_case(inquiry)
        with self.assertRaises(UserError):
            WorkflowEngine(self.env).run_store_pickup_complete(case)

    def test_store_pickup_complete_succeeds_after_payment(self):
        inquiry = self._make_inquiry("store_pickup")
        case = self._bind_case(inquiry)
        WorkflowEngine(self.env).run_payment_trust(case, "cash_pickup", user=self.env.user)
        result = WorkflowEngine(self.env).run_store_pickup_complete(case)
        self.assertTrue(result)

    # ------------------------------------------------------------------ draft RFQ
    def _setup_case_for_rfq(self):
        inquiry = self._make_inquiry("store_pickup")
        ledger = WorkflowEngine(self.env).run_auto_quote_if_eligible(inquiry)
        self.assertTrue(ledger)
        ledger.action_accept()
        case = ledger.case_id or self._bind_case(inquiry)
        self.env["petspot.fulfillment.line"].create(
            {
                "case_id": case.id,
                "product_id": self.product.id,
                "product_uom_qty": 1.0,
                "source": "supplier_b2b",
                "vendor_id": self.vendor.id,
            }
        )
        WorkflowEngine(self.env).run_payment_trust(case, "cash_pickup", user=self.env.user)
        return case, ledger

    def test_draft_rfq_requires_payment(self):
        inquiry = self._make_inquiry("store_pickup")
        ledger = WorkflowEngine(self.env).run_auto_quote_if_eligible(inquiry)
        ledger.action_accept()
        case = ledger.case_id or self._bind_case(inquiry)
        with self.assertRaises(UserError):
            WorkflowEngine(self.env).run_draft_rfq(case)

    def test_draft_rfq_requires_accepted_quotation(self):
        inquiry = self._make_inquiry("store_pickup")
        case = self._bind_case(inquiry)
        WorkflowEngine(self.env).run_payment_trust(case, "cash_pickup", user=self.env.user)
        with self.assertRaises(UserError):
            WorkflowEngine(self.env).run_draft_rfq(case)

    def test_draft_rfq_success_and_duplicate_guard(self):
        case, ledger = self._setup_case_for_rfq()
        WorkflowEngine(self.env).run_draft_rfq(case)
        pos = case.purchase_order_ids.filtered(lambda p: p.state in ("draft", "sent"))
        self.assertEqual(len(pos), 1)
        # Second call must not create a duplicate draft PO for the same vendor.
        WorkflowEngine(self.env).run_draft_rfq(case)
        pos_after = case.purchase_order_ids.filtered(lambda p: p.state in ("draft", "sent"))
        self.assertEqual(len(pos_after), 1)

    def test_draft_rfq_blocks_on_post_quote_supplier_price_change(self):
        case, ledger = self._setup_case_for_rfq()
        self.offer.effective_cost = 30.0  # >1% change from quoted 13.0
        try:
            # assertRaises uses a DB savepoint that rolls back writes inside the
            # block (including the exception-state transition). Assert the error
            # first, then re-run outside the savepoint so the FSM write sticks.
            with self.assertRaises(UserError) as err:
                WorkflowEngine(self.env).run_draft_rfq(case)
            self.assertIn("Supplier price changed", str(err.exception))
            try:
                WorkflowEngine(self.env).run_draft_rfq(case)
            except UserError:
                pass
            case.invalidate_recordset(["state"])
            self.assertEqual(case.state, "exception")
        finally:
            self.offer.effective_cost = 13.0

    # ------------------------------------------------------------------ synthetic receipt
    def test_synthetic_giza_receipt_completes_picking(self):
        case, ledger = self._setup_case_for_rfq()
        WorkflowEngine(self.env).run_draft_rfq(case)
        po = case.purchase_order_ids.filtered(lambda p: p.state in ("draft", "sent"))[:1]
        po.button_confirm()
        self.assertEqual(po.state, "purchase")
        receipt = WorkflowEngine(self.env).run_synthetic_giza_receipt(case)
        self.assertTrue(receipt)
        for picking in receipt:
            self.assertEqual(picking.state, "done")

    def test_synthetic_giza_receipt_requires_confirmed_po(self):
        inquiry = self._make_inquiry("store_pickup")
        case = self._bind_case(inquiry)
        with self.assertRaises(UserError):
            WorkflowEngine(self.env).run_synthetic_giza_receipt(case)

    # ------------------------------------------------------------------ mock AWB
    def test_mock_shipblu_awb_creation_and_duplicate_guard(self):
        if "shipblu.shipment" not in self.env or "shipblu.backend" not in self.env:
            self.skipTest("delivery_shipblu / petspot_shipblu_base not fully installed")
        if not self.env["shipblu.backend"].sudo().search([], limit=1):
            self.skipTest("no shipblu.backend configured on this DB")
        inquiry = self._make_inquiry("shipblu_delivery")
        so = self.env["sale.order"].create(
            {
                "partner_id": self.partner.id,
                "order_line": [
                    (0, 0, {"product_id": self.product.id, "product_uom_qty": 1, "price_unit": 85.0})
                ],
            }
        )
        case = self.env["petspot.fulfillment.case"].create(
            {
                "name": f"FF-WFE-AWB/{inquiry.id}",
                "inquiry_id": inquiry.id,
                "sale_order_id": so.id,
                "delivery_method": "shipblu_delivery",
                "partner_id": self.partner.id,
            }
        )
        engine = WorkflowEngine(self.env)
        engine.run_payment_trust(case, "cash_pickup", user=self.env.user)
        shipment = engine.run_mock_shipblu_awb(case)
        self.assertTrue(shipment.tracking_number.startswith("MOCK-"))
        with self.assertRaises(UserError):
            engine.run_mock_shipblu_awb(case)

    def test_mock_shipblu_awb_live_transport_always_blocked(self):
        self.ICP.set_param("petspot_fulfillment_vetution.shipblu_create_transport", "live")
        inquiry = self._make_inquiry("shipblu_delivery")
        case = self._bind_case(inquiry, delivery_method="shipblu_delivery")
        try:
            with self.assertRaises(UserError):
                WorkflowEngine(self.env).run_mock_shipblu_awb(case)
        finally:
            self.ICP.set_param("petspot_fulfillment_vetution.shipblu_create_transport", "mock")

    # ------------------------------------------------------------------ production safety
    def test_all_workflow_methods_blocked_on_non_synthetic_without_flags(self):
        real_policy = self.Policy.create(
            {"name": "WFE non-synthetic candidate", "version": "wfe-real"}
        )
        inquiry = self._make_inquiry("store_pickup")
        assessment = self.env["petspot.vetution.shadow.assessment"].create(
            {
                "name": f"ASS/{inquiry.name}",
                "inquiry_id": inquiry.id,
                "product_id": self.product.id,
                "policy_id": real_policy.id,
                "state": "ok",
                "company_id": self.env.company.id,
            }
        )
        inquiry.vetution_assessment_id = assessment.id
        with self.assertRaises(UserError):
            WorkflowEngine(self.env).run_send_message(inquiry, "checking", {})
