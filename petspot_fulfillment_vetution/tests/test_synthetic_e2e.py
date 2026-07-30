# -*- coding: utf-8 -*-
"""Synthetic E2E workflow tests — TEST fixtures only, all live writes mocked/locked."""

from datetime import timedelta
from unittest.mock import MagicMock, patch

from odoo import fields
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.petspot_fulfillment_vetution.services.landed_cost_engine import LandedCostEngine
from odoo.addons.petspot_fulfillment_vetution.services.chatwoot_transport import ChatwootTransport


@tagged("post_install", "-at_install", "petspot_fulfillment_vetution", "petspot_ff_e2e")
class TestSyntheticWorkflowE2E(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.policy = cls.env.ref(
            "petspot_fulfillment_vetution.landed_cost_policy_synthetic_test",
            raise_if_not_found=False,
        )
        if not cls.policy:
            cls.policy = cls.env["petspot.vetution.landed.cost.policy"].search(
                [("name", "=", "TEST-SYNTHETIC-E2E-NOT-FOR-COMMERCE")], limit=1
            )
        if not cls.policy:
            # XML may use noupdate; create minimal synthetic fixture for this test DB
            cls.policy = cls.env["petspot.vetution.landed.cost.policy"].create({
                "name": "TEST-SYNTHETIC-E2E-NOT-FOR-COMMERCE",
                "version": "TEST-SYNTHETIC-E2E",
                "is_synthetic_test": True,
                "active": True,
                "policy_environment": "test_only",
            })
        # Activate synthetic flags for this test DB transaction only
        cls.policy.write(
            {
                "active": True,
                "allow_auto_quotation": True,
                "allow_customer_message": True,
                "allow_supplier_po": True,
                "is_synthetic_test": True,
                "max_auto_delivery_subsidy": 0.0,
            }
        )
        # Deactivate other policies to avoid get_active_policy ambiguity
        others = cls.env["petspot.vetution.landed.cost.policy"].search(
            [("id", "!=", cls.policy.id), ("active", "=", True)]
        )
        others.write({"active": False})

        Product = cls.env["product.product"]
        cls.product = Product.search([("default_code", "=", "SHP-472-1065")], limit=1)
        if not cls.product:
            cls.product = Product.create(
                {
                    "name": "Synthetic SHP-472-1065",
                    "default_code": "SHP-472-1065",
                    "list_price": 85.0,
                    "type": "consu",
                }
            )
        else:
            # Keep current price within ±10% of synthetic recommended (~EGP 90).
            cls.product.list_price = 85.0
        if not cls.product.vetution_size_id:
            cls.product.vetution_size_id = 3975

        cls.env["ir.config_parameter"].sudo().set_param(
            "petspot_fulfillment_vetution.synthetic_policy_allowed_dbs",
            cls.env.cr.dbname,
        )
        cls.env["ir.config_parameter"].sudo().set_param(
            "petspot_fulfillment_vetution.chatwoot_transport", "mock"
        )
        cls.env["ir.config_parameter"].sudo().set_param(
            "petspot_fulfillment_vetution.shopify_publish_transport", "mock"
        )
        cls.env["ir.config_parameter"].sudo().set_param(
            "petspot_fulfillment_vetution.shipblu_create_transport", "mock"
        )

        # Ensure offer
        Offer = cls.env["vetution.supplier.offer"]
        offer = Offer.search([("vetution_size_id", "=", 3975)], limit=1)
        if not offer:
            offer = Offer.create(
                {
                    "name": "SYN offer 3975",
                    "offer_type": "vetution",
                    "vetution_size_id": 3975,
                    "product_id": cls.product.id,
                    "effective_cost": 13.0,
                    "supplier_price": 13.0,
                }
            )
        else:
            offer.write({"effective_cost": 13.0, "product_id": cls.product.id})
        cls.offer = offer

        # Allowlist exact mapping
        Allow = cls.env["petspot.vetution.automation.allowlist"]
        if not Allow.is_product_allowed(cls.product):
            try:
                Allow.add_exact_mapping(
                    cls.product,
                    proof_note="SYNTHETIC E2E: SHP-472-1065 ↔ size 3975 exact",
                )
            except Exception:
                Allow.create(
                    {
                        "name": "ALLOW/SHP-472-1065",
                        "product_id": cls.product.id,
                        "vetution_size_id": 3975,
                        "proof_note": "SYNTHETIC E2E exact size",
                    }
                )

        cls.partner = cls.env["res.partner"].create({"name": "Synthetic E2E Customer", "phone": "+201000000001"})

    def setUp(self):
        super().setUp()
        if not self.policy:
            self.skipTest("synthetic policy missing")

    def _fake_shipblu(self, base=95.0, cod=0.0):
        fake = MagicMock()
        fake.base_fee = base
        fake.size_surcharge = 0.0
        fake.pickup_surcharge = 0.0
        fake.discount = 0.0
        fake.cod_fee = cod
        fake.pricing_source = "contract"
        fake.notes = []
        fake.to_dict.return_value = {"base_fee": base}
        return fake

    def _make_inquiry(self, fulfillment="store_pickup", sku="SHP-472-1065"):
        return self.env["petspot.availability.inquiry"].create(
            {
                "phone": self.partner.phone,
                "partner_id": self.partner.id,
                "product_id": self.product.id,
                "default_code": sku,
                "requested_qty": 1.0,
                "requested_fulfillment": fulfillment,
                "channel": "manual",
                "conversation_id": f"syn-conv-{fields.Datetime.now()}",
                "message_id": f"syn-msg-{fields.Datetime.now()}",
            }
        )

    def test_north_coast_delivery_subsidy_requires_review(self):
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
                    "packaging_type": "small_box",
                },
            )
        self.assertEqual(res.delivery_decision_code, "DELIVERY_PRICE_REVIEW_REQUIRED")
        self.assertGreater(res.delivery_subsidy, 0.0)
        self.assertEqual(res.proposed_delivery_charge, 196.0)
        # Product price unaffected by subsidy
        self.assertLess(res.product_landed_cost, 100.0)

    def test_giza_giza_prepaid_passes_delivery_gate(self):
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
                    "payment_method": "paymob",
                    "packaging_type": "small_box",
                    "estimated_collect_amount": 100.0,
                },
            )
        self.assertNotEqual(res.delivery_decision_code, "DELIVERY_PRICE_REVIEW_REQUIRED")
        self.assertEqual(res.delivery_subsidy, 0.0)
        self.assertEqual(res.customer_delivery_charge, 118.0)

    def test_pickup_path_e2e_synthetic(self):
        inquiry = self._make_inquiry("store_pickup")
        # Landed worksheet
        res = LandedCostEngine(self.env, self.policy).compute(
            supplier_cost=13.0,
            context={
                "requested_fulfillment": "store_pickup",
                "payment_method": "bank_transfer",
                "packaging_type": "envelope",
            },
        )
        self.assertEqual(res.customer_delivery_charge, 0.0)
        self.assertEqual(res.product_decision_code, "PRODUCT_PRICE_READY")

        # Fake assessment record for auto-quote
        Assess = self.env["petspot.vetution.shadow.assessment"]
        assessment = Assess.create(
            {
                "name": f"ASS/{inquiry.name}",
                "inquiry_id": inquiry.id,
                "product_id": self.product.id,
                "policy_id": self.policy.id,
                "state": "ok",
                "is_fresh": True,
                "data_age_hours": 0.5,
                "assessed_at": fields.Datetime.now(),
                "supplier_cost": 13.0,
                "product_landed_cost": res.product_landed_cost,
                "recommended_product_price": res.recommended_product_price,
                "suggested_price": res.recommended_product_price,
                "customer_delivery_charge": 0.0,
                "order_total": res.order_total,
                "product_decision_code": "PRODUCT_PRICE_READY",
                "delivery_decision_code": "ORDER_ECONOMICS_READY",
                "company_id": self.env.company.id,
            }
        )
        aq = self.env["petspot.vetution.auto.quote"].run_for_inquiry(
            inquiry, assessment=assessment, force_policy=self.policy
        )
        self.assertIn(aq.state, ("quoted", "blocked", "eligible"))
        if aq.state == "quoted":
            aq.action_accept()
            self.assertTrue(aq.accepted_price_locked)

        msg = ChatwootTransport(self.env, force_mock=True).send_template(
            inquiry=inquiry,
            template_code="quotation_ready",
            idempotency_key=f"qready/{inquiry.id}",
            context={
                "product_price": res.recommended_product_price,
                "delivery_charge": 0,
                "order_total": res.order_total,
                "valid_hours": 2,
            },
        )
        self.assertEqual(msg.state, "sent")
        self.assertEqual(msg.transport, "mock")

        pay = self.env["petspot.vetution.payment.event"].ingest_trusted_payment(
            source="cash_pickup",
            external_ref=f"cash-{inquiry.id}",
            amount=res.order_total or 65.0,
            inquiry=inquiry,
            signature_ok=True,
        )
        self.assertEqual(pay.state, "accepted")

        # Duplicate payment
        dup = self.env["petspot.vetution.payment.event"].ingest_trusted_payment(
            source="cash_pickup",
            external_ref=f"cash-{inquiry.id}",
            amount=res.order_total or 65.0,
            inquiry=inquiry,
        )
        self.assertEqual(dup.state, "duplicate")

        # Case + Giza receipt
        Case = self.env["petspot.fulfillment.case"]
        case = Case.search([("inquiry_id", "=", inquiry.id)], limit=1)
        if not case and hasattr(Case, "bind_inquiry_case"):
            case = Case.bind_inquiry_case(inquiry)
        if not case:
            case = Case.create(
                {
                    "name": f"FF-SYN/{inquiry.id}",
                    "inquiry_id": inquiry.id,
                    "delivery_method": "store_pickup",
                    "payment_status": "paid",
                    "partner_id": self.partner.id,
                }
            )
        receipt = self.env["petspot.vetution.giza.receipt"].receive_for_case(case)
        self.assertEqual(receipt.state, "pickup_ready")
        receipt.action_notify_pickup_once()
        self.assertTrue(receipt.pickup_notified)
        # second notify idempotent
        receipt.action_notify_pickup_once()
        receipt.action_confirm_handover()
        self.assertEqual(receipt.state, "handed_over")

        # No AWB on pickup
        awb = self.env["petspot.vetution.shipblu.mock.awb"].create_for_case(case)
        self.assertEqual(awb.state, "blocked")
        self.assertIn("store_pickup_no_awb", awb.block_reason or "")

    def test_delivery_path_mock_awb(self):
        inquiry = self._make_inquiry("shipblu_delivery")
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
                    "payment_method": "paymob",
                    "packaging_type": "small_box",
                    "estimated_collect_amount": 100.0,
                },
            )
        assessment = self.env["petspot.vetution.shadow.assessment"].create(
            {
                "name": f"ASS/{inquiry.id}",
                "inquiry_id": inquiry.id,
                "product_id": self.product.id,
                "policy_id": self.policy.id,
                "state": "ok",
                "is_fresh": True,
                "data_age_hours": 0.2,
                "assessed_at": fields.Datetime.now(),
                "recommended_product_price": res.recommended_product_price,
                "customer_delivery_charge": 118.0,
                "delivery_margin": res.delivery_margin,
                "delivery_decision_code": res.delivery_decision_code,
                "product_decision_code": "PRODUCT_PRICE_READY",
                "company_id": self.env.company.id,
            }
        )
        Case = self.env["petspot.fulfillment.case"]
        case = Case.create(
            {
                "name": f"FF-DEL/{inquiry.id}",
                "inquiry_id": inquiry.id,
                "delivery_method": "shipblu_delivery",
                "payment_status": "paid",
                "partner_id": self.partner.id,
            }
        )
        # Without package verify → blocked
        blocked = self.env["petspot.vetution.shipblu.mock.awb"].create_for_case(
            case, package_size_verified=False, assessment=assessment
        )
        self.assertEqual(blocked.state, "blocked")
        # With verify flag (still mock — no live create)
        blocked.unlink()
        awb = self.env["petspot.vetution.shipblu.mock.awb"].create_for_case(
            case, package_size_verified=True, assessment=assessment
        )
        self.assertEqual(awb.state, "mocked_created")
        awb.action_simulate_tracking_sync()
        awb.action_simulate_delivered()
        self.assertEqual(awb.state, "delivered")
        # Duplicate AWB prevented
        again = self.env["petspot.vetution.shipblu.mock.awb"].create_for_case(
            case, package_size_verified=True, assessment=assessment
        )
        self.assertEqual(again.id, awb.id)

    def test_paymob_unsigned_rejected(self):
        ev = self.env["petspot.vetution.payment.event"].ingest_trusted_payment(
            source="paymob_callback",
            external_ref="paymob-unsigned-1",
            amount=100.0,
            signature_ok=False,
        )
        self.assertEqual(ev.state, "rejected")
        self.assertEqual(ev.reject_reason, "unsigned_or_invalid_paymob_signature")

    def test_wrong_amount_rejected(self):
        ev = self.env["petspot.vetution.payment.event"].ingest_trusted_payment(
            source="shopify_paid",
            external_ref="shopify-amt-1",
            amount=50.0,
            expected_amount=183.0,
            signature_ok=True,
        )
        self.assertEqual(ev.state, "rejected")
        self.assertEqual(ev.reject_reason, "wrong_amount")

    def test_price_publish_blocked_without_flag(self):
        from odoo.exceptions import UserError

        self.assertFalse(self.policy.allow_price_publish)
        ICP = self.env["ir.config_parameter"].sudo()
        ICP.set_param("petspot_fulfillment_vetution.shopify_publish_transport", "mock")
        q = self.env["petspot.vetution.price.publish.queue"].enqueue(
            self.product, float(self.product.list_price or 85.0) + 5.0
        )
        self.assertTrue(q.id)
        if q.state == "pending":
            q.approve()
        if q.state == "approved":
            q.publish_mock()
            self.assertEqual(q.state, "published")
        # Live Shopify transport must remain unimplemented / blocked
        ICP.set_param("petspot_fulfillment_vetution.shopify_publish_transport", "live")
        try:
            q2 = self.env["petspot.vetution.price.publish.queue"].create(
                {
                    "name": "PRICE/live-block",
                    "product_id": self.product.id,
                    "suggested_price": 99.0,
                    "current_price": 85.0,
                    "state": "approved",
                    "idempotency_key": f"pub-live-block:{self.product.id}",
                }
            )
            with self.assertRaises(UserError):
                q2.publish_mock()
        finally:
            ICP.set_param("petspot_fulfillment_vetution.shopify_publish_transport", "mock")

    def test_ops_health_capture(self):
        snap = self.env["petspot.vetution.ops.health"].capture()
        self.assertTrue(snap.id)
        self.assertTrue(snap.shp139_blocked)

    def test_mapping_shp139_stays_blocked(self):
        p139 = self.env["product.product"].search([("default_code", "=", "SHP-139-144")], limit=1)
        if not p139:
            self.skipTest("SHP-139-144 not in DB")
        self.assertFalse(
            self.env["petspot.vetution.automation.allowlist"].is_product_allowed(p139)
        )

    def test_stale_blocks_auto_quote(self):
        inquiry = self._make_inquiry()
        assessment = self.env["petspot.vetution.shadow.assessment"].create(
            {
                "name": "stale",
                "inquiry_id": inquiry.id,
                "product_id": self.product.id,
                "policy_id": self.policy.id,
                "state": "stale",
                "is_fresh": False,
                "data_age_hours": 5.0,
                "assessed_at": fields.Datetime.now() - timedelta(hours=5),
                "company_id": self.env.company.id,
            }
        )
        aq = self.env["petspot.vetution.auto.quote"].run_for_inquiry(
            inquiry, assessment=assessment, force_policy=self.policy
        )
        self.assertEqual(aq.state, "blocked")
        self.assertIn("stale", aq.block_reason or "")

    def test_locks_default_off_on_non_synthetic_seed(self):
        real = self.env["petspot.vetution.landed.cost.policy"].search(
            [("is_synthetic_test", "=", False)], limit=1
        )
        if not real:
            self.skipTest("no non-synthetic policy")
        # After our setUpClass we may have deactivated — check field defaults conceptually
        self.assertFalse(real.allow_price_publish or False)

    def test_message_templates_seeded(self):
        codes = self.env["petspot.vetution.message.template"].search([]).mapped("key")
        for needed in (
            "supplier_available",
            "quotation_ready",
            "delivery_charge_revision",
            "tracking_issued",
            "ready_for_pickup",
        ):
            self.assertIn(needed, codes)
