# -*- coding: utf-8 -*-
"""Payment Trust tests (Phase 15B) — only trusted signals ever accepted."""

import hashlib
import hmac
import json

from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install", "petspot_fulfillment_vetution")
class TestPaymentTrust(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Trust = cls.env["petspot.vetution.payment.trust"]
        cls.ICP = cls.env["ir.config_parameter"].sudo()
        cls.partner = cls.env["res.partner"].create({"name": "Payment Trust Customer"})
        cls.product = cls.env["product.product"].create(
            {"name": "PayTrust Product", "type": "consu", "list_price": 100.0}
        )
        cls.so = cls.env["sale.order"].create(
            {
                "partner_id": cls.partner.id,
                "order_line": [
                    (0, 0, {"product_id": cls.product.id, "product_uom_qty": 1, "price_unit": 100.0})
                ],
            }
        )
        cls.case = cls.env["petspot.fulfillment.case"].create(
            {
                "name": "FF-PAYTRUST-1",
                "partner_id": cls.partner.id,
                "sale_order_id": cls.so.id,
                "delivery_method": "store_pickup",
            }
        )

    def test_register_shopify_paid_matches_order_total(self):
        rec = self.Trust.register_shopify_paid(self.case, 100.0, "EGP", "shop-order-1")
        self.assertEqual(rec.state, "accepted")
        self.assertEqual(rec.source, "shopify_paid")

    def test_wrong_amount_rejected(self):
        rec = self.Trust.register_shopify_paid(self.case, 50.0, "EGP", "shop-order-wrong-amt")
        self.assertEqual(rec.state, "rejected")
        self.assertIn("amount_mismatch", rec.reject_reason or "")

    def test_wrong_currency_rejected(self):
        rec = self.Trust.register_shopify_paid(self.case, 100.0, "USD", "shop-order-wrong-cur")
        self.assertEqual(rec.state, "rejected")
        self.assertIn("currency_mismatch", rec.reject_reason or "")

    def test_duplicate_reference_marked_duplicate(self):
        first = self.Trust.register_shopify_paid(self.case, 100.0, "EGP", "shop-order-dup")
        self.assertEqual(first.state, "accepted")
        second = self.Trust.register_shopify_paid(self.case, 100.0, "EGP", "shop-order-dup")
        self.assertEqual(second.state, "duplicate")
        self.assertIn(f"duplicate_of_id_{first.id}", second.reject_reason or "")

    def test_duplicate_accepted_constraint_blocks_direct_create(self):
        self.Trust.create(
            {
                "name": "PAY/manual/dup-guard",
                "case_id": self.case.id,
                "source": "cash_pickup",
                "amount": 100.0,
                "reference": "manual-dup-guard",
                "state": "accepted",
            }
        )
        with self.assertRaises(ValidationError):
            self.Trust.create(
                {
                    "name": "PAY/manual/dup-guard-2",
                    "case_id": self.case.id,
                    "source": "cash_pickup",
                    "amount": 100.0,
                    "reference": "manual-dup-guard",
                    "state": "accepted",
                }
            )

    def test_cash_pickup_approval_accepted(self):
        rec = self.Trust.register_cash_pickup_approval(self.case, self.env.user)
        self.assertEqual(rec.state, "accepted")
        self.assertEqual(rec.source, "cash_pickup")
        self.assertEqual(self.case.payment_status, "manual_paid")

    def test_cod_policy_accepted(self):
        case2 = self.env["petspot.fulfillment.case"].create(
            {
                "name": "FF-PAYTRUST-COD",
                "partner_id": self.partner.id,
                "sale_order_id": self.so.id,
                "delivery_method": "shipblu_delivery",
            }
        )
        rec = self.Trust.register_cod_policy(case2)
        self.assertEqual(rec.state, "accepted")
        self.assertEqual(rec.source, "cod_policy")

    def test_paymob_callback_unsigned_without_secret_rejected(self):
        self.ICP.set_param("petspot_fulfillment_vetution.paymob_hmac_secret", "")
        rec = self.Trust.register_paymob_callback(
            {"order_id": "pm-1", "amount": 100.0, "currency": "EGP"}, signature=False
        )
        self.assertEqual(rec.state, "rejected")
        self.assertEqual(rec.reject_reason, "hmac_verification_failed")

    def test_paymob_callback_synthetic_mock_signed_accepted_without_secret(self):
        self.ICP.set_param("petspot_fulfillment_vetution.paymob_hmac_secret", "")
        rec = self.Trust.register_paymob_callback(
            {
                "order_id": "pm-synthetic-1",
                "amount": 50.0,
                "currency": "EGP",
                "synthetic_mock_signed": True,
            },
            signature=False,
        )
        self.assertEqual(rec.state, "accepted")

    def test_paymob_callback_verified_with_hmac_secret(self):
        secret = "test-secret-key"
        self.ICP.set_param("petspot_fulfillment_vetution.paymob_hmac_secret", secret)
        payload = {"order_id": "pm-verified-1", "amount": 42.0, "currency": "EGP"}
        payload_hash = hashlib.sha256(
            json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        signature = hmac.new(
            secret.encode("utf-8"), payload_hash.encode("utf-8"), hashlib.sha512
        ).hexdigest()
        rec = self.Trust.register_paymob_callback(payload, signature=signature)
        self.assertEqual(rec.state, "accepted")
        self.ICP.set_param("petspot_fulfillment_vetution.paymob_hmac_secret", "")

    def test_paymob_callback_wrong_signature_rejected(self):
        secret = "test-secret-key-2"
        self.ICP.set_param("petspot_fulfillment_vetution.paymob_hmac_secret", secret)
        payload = {"order_id": "pm-wrong-sig", "amount": 42.0, "currency": "EGP"}
        rec = self.Trust.register_paymob_callback(payload, signature="totally-wrong")
        self.assertEqual(rec.state, "rejected")
        self.ICP.set_param("petspot_fulfillment_vetution.paymob_hmac_secret", "")
