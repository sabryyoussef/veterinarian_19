# -*- coding: utf-8 -*-
"""Quotation Ledger tests (Phase 15B) — auto-quote gate matrix."""

from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install", "petspot_fulfillment_vetution")
class TestAutoQuoteLedger(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Ledger = cls.env["petspot.vetution.quotation.ledger"]
        cls.Assess = cls.env["petspot.vetution.shadow.assessment"]
        cls.ICP = cls.env["ir.config_parameter"].sudo()

        cls.synthetic = cls.env.ref(
            "petspot_fulfillment_vetution.landed_cost_policy_synthetic_test",
            raise_if_not_found=False,
        )
        if not cls.synthetic:
            cls.synthetic = cls.env["petspot.vetution.landed.cost.policy"].search(
                [("name", "=", "TEST-SYNTHETIC-E2E-NOT-FOR-COMMERCE")], limit=1
            )
        if not cls.synthetic:
            raise AssertionError("synthetic TEST policy missing")

        cls.non_synthetic = cls.env["petspot.vetution.landed.cost.policy"].create(
            {"name": "AQ non-synthetic policy", "version": "aq-test"}
        )

        cls.partner = cls.env["res.partner"].create({"name": "AutoQuote Customer"})
        cls.product = cls.env["product.product"].create(
            {"name": "AutoQuote Product", "type": "consu", "list_price": 65.0, "default_code": "AQL-1"}
        )

    def setUp(self):
        super().setUp()
        self.ICP.set_param("petspot_fulfillment_vetution.synthetic_policy_allowed_dbs", "")

    def _allow_synthetic_here(self):
        self.ICP.set_param(
            "petspot_fulfillment_vetution.synthetic_policy_allowed_dbs", self.env.cr.dbname
        )

    def _make_inquiry(self, code="AQL-1"):
        return self.env["petspot.availability.inquiry"].create(
            {
                "phone": "+201000000077",
                "partner_id": self.partner.id,
                "product_id": self.product.id,
                "default_code": code,
                "requested_qty": 1.0,
                "requested_fulfillment": "store_pickup",
                "channel": "manual",
                "conversation_id": f"aql-conv-{fields.Datetime.now()}",
                "message_id": f"aql-msg-{fields.Datetime.now()}",
            }
        )

    def _make_assessment(self, inquiry, policy, **overrides):
        vals = {
            "name": f"ASS/{inquiry.name}",
            "inquiry_id": inquiry.id,
            "product_id": self.product.id,
            "policy_id": policy.id,
            "state": "ok",
            "is_fresh": True,
            "data_age_hours": 0.5,
            "assessed_at": fields.Datetime.now(),
            "supplier_cost": 13.0,
            "product_landed_cost": 30.0,
            "recommended_product_price": 65.0,
            "suggested_price": 65.0,
            "customer_delivery_charge": 0.0,
            "order_total": 65.0,
            "on_automation_allowlist": True,
            "delivery_gate_passed": True,
            "resolution_confidence": "exact",
            "landed_cost_incomplete": False,
            "company_id": self.env.company.id,
        }
        vals.update(overrides)
        return self.Assess.create(vals)

    def test_blocked_on_non_synthetic_without_flags(self):
        inquiry = self._make_inquiry()
        assessment = self._make_assessment(inquiry, self.non_synthetic)
        with self.assertRaises(UserError):
            self.Ledger.create_auto_quotation(inquiry, assessment, self.non_synthetic)

    def test_blocked_on_non_synthetic_flag_true_but_icp_disabled(self):
        self.non_synthetic.allow_auto_quotation = True
        self.ICP.set_param("petspot_fulfillment_vetution.auto_quote_enabled", "False")
        inquiry = self._make_inquiry()
        assessment = self._make_assessment(inquiry, self.non_synthetic)
        with self.assertRaises(UserError):
            self.Ledger.create_auto_quotation(inquiry, assessment, self.non_synthetic)
        self.non_synthetic.allow_auto_quotation = False

    def test_blocked_synthetic_not_allowlisted(self):
        inquiry = self._make_inquiry()
        assessment = self._make_assessment(inquiry, self.synthetic)
        with self.assertRaises(UserError):
            self.Ledger.create_auto_quotation(inquiry, assessment, self.synthetic)

    def test_succeeds_synthetic_allowlisted(self):
        self._allow_synthetic_here()
        inquiry = self._make_inquiry()
        assessment = self._make_assessment(inquiry, self.synthetic)
        ledger = self.Ledger.create_auto_quotation(inquiry, assessment, self.synthetic)
        self.assertEqual(ledger.state, "sent")
        self.assertEqual(ledger.product_price, 65.0)
        self.assertEqual(ledger.order_total, 65.0)
        self.assertTrue(ledger.expires_at)

    def test_idempotent_same_assessment_returns_same_ledger(self):
        self._allow_synthetic_here()
        inquiry = self._make_inquiry()
        assessment = self._make_assessment(inquiry, self.synthetic)
        first = self.Ledger.create_auto_quotation(inquiry, assessment, self.synthetic)
        second = self.Ledger.create_auto_quotation(inquiry, assessment, self.synthetic)
        self.assertEqual(first.id, second.id)
        count = self.Ledger.search_count([("inquiry_id", "=", inquiry.id)])
        self.assertEqual(count, 1)

    def test_stale_data_blocks(self):
        self._allow_synthetic_here()
        inquiry = self._make_inquiry()
        assessment = self._make_assessment(inquiry, self.synthetic, data_age_hours=5.0)
        with self.assertRaises(UserError):
            self.Ledger.create_auto_quotation(inquiry, assessment, self.synthetic)

    def test_not_on_allowlist_blocks(self):
        self._allow_synthetic_here()
        inquiry = self._make_inquiry()
        assessment = self._make_assessment(inquiry, self.synthetic, on_automation_allowlist=False)
        with self.assertRaises(UserError):
            self.Ledger.create_auto_quotation(inquiry, assessment, self.synthetic)

    def test_delivery_gate_failed_blocks(self):
        self._allow_synthetic_here()
        inquiry = self._make_inquiry()
        assessment = self._make_assessment(
            inquiry, self.synthetic, delivery_gate_passed=False,
            delivery_decision_code="DELIVERY_PRICE_REVIEW_REQUIRED",
        )
        with self.assertRaises(UserError):
            self.Ledger.create_auto_quotation(inquiry, assessment, self.synthetic)

    def test_ambiguous_mapping_blocks(self):
        self._allow_synthetic_here()
        inquiry = self._make_inquiry()
        assessment = self._make_assessment(inquiry, self.synthetic, resolution_confidence="ambiguous")
        with self.assertRaises(UserError):
            self.Ledger.create_auto_quotation(inquiry, assessment, self.synthetic)

    def test_incomplete_landed_cost_blocks(self):
        self._allow_synthetic_here()
        inquiry = self._make_inquiry()
        assessment = self._make_assessment(inquiry, self.synthetic, landed_cost_incomplete=True)
        with self.assertRaises(UserError):
            self.Ledger.create_auto_quotation(inquiry, assessment, self.synthetic)

    def test_missing_suggested_price_blocks(self):
        self._allow_synthetic_here()
        inquiry = self._make_inquiry()
        assessment = self._make_assessment(inquiry, self.synthetic, suggested_price=0.0)
        with self.assertRaises(UserError):
            self.Ledger.create_auto_quotation(inquiry, assessment, self.synthetic)

    def test_new_assessment_supersedes_open_quote(self):
        self._allow_synthetic_here()
        inquiry = self._make_inquiry()
        assessment1 = self._make_assessment(inquiry, self.synthetic, suggested_price=65.0)
        ledger1 = self.Ledger.create_auto_quotation(inquiry, assessment1, self.synthetic)
        assessment2 = self._make_assessment(inquiry, self.synthetic, suggested_price=70.0)
        ledger2 = self.Ledger.create_auto_quotation(inquiry, assessment2, self.synthetic)
        self.assertNotEqual(ledger1.id, ledger2.id)
        self.assertEqual(ledger1.state, "superseded")
        self.assertEqual(ledger2.state, "sent")
        self.assertEqual(ledger2.version, ledger1.version + 1)

    def test_accept_locks_price_and_blocks_further_supersede(self):
        self._allow_synthetic_here()
        inquiry = self._make_inquiry()
        assessment1 = self._make_assessment(inquiry, self.synthetic, suggested_price=65.0)
        ledger1 = self.Ledger.create_auto_quotation(inquiry, assessment1, self.synthetic)
        ledger1.action_accept()
        self.assertEqual(ledger1.state, "accepted")
        self.assertTrue(ledger1.accepted_price_lock)

        assessment2 = self._make_assessment(inquiry, self.synthetic, suggested_price=80.0)
        with self.assertRaises(UserError):
            self.Ledger.create_auto_quotation(inquiry, assessment2, self.synthetic)

    def test_expired_quote_cannot_be_accepted(self):
        self._allow_synthetic_here()
        inquiry = self._make_inquiry()
        assessment = self._make_assessment(inquiry, self.synthetic)
        ledger = self.Ledger.create_auto_quotation(inquiry, assessment, self.synthetic)
        ledger.write({"expires_at": fields.Datetime.now() - timedelta(hours=1)})
        # assertRaises savepoint rolls back the expired-state write; assert the
        # error, then re-accept outside the savepoint so the write sticks.
        with self.assertRaises(UserError) as err:
            ledger.action_accept()
        self.assertIn("expired", str(err.exception).lower())
        try:
            ledger.action_accept()
        except UserError:
            pass
        ledger.invalidate_recordset(["state"])
        self.assertEqual(ledger.state, "expired")

    def test_expire_stale_cron_helper(self):
        self._allow_synthetic_here()
        inquiry = self._make_inquiry()
        assessment = self._make_assessment(inquiry, self.synthetic)
        ledger = self.Ledger.create_auto_quotation(inquiry, assessment, self.synthetic)
        ledger.expires_at = fields.Datetime.now() - timedelta(hours=1)
        expired_count = self.Ledger.expire_stale()
        self.assertGreaterEqual(expired_count, 1)
        self.assertEqual(ledger.state, "expired")
