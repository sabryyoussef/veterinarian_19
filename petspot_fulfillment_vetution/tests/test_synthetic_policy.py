# -*- coding: utf-8 -*-
"""Synthetic TEST policy safety-gate tests (Phase 15B)."""

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install", "petspot_fulfillment_vetution")
class TestSyntheticPolicy(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Policy = cls.env["petspot.vetution.landed.cost.policy"]
        cls.synthetic = cls.env.ref(
            "petspot_fulfillment_vetution.landed_cost_policy_synthetic_test",
            raise_if_not_found=False,
        )
        if not cls.synthetic:
            cls.synthetic = cls.Policy.search(
                [("name", "=", "TEST-SYNTHETIC-E2E-NOT-FOR-COMMERCE")], limit=1
            )
        if not cls.synthetic:
            raise AssertionError(
                "synthetic TEST policy TEST-SYNTHETIC-E2E-NOT-FOR-COMMERCE missing "
                "— data/synthetic_test_policy_data.xml not loaded?"
            )
        cls.ICP = cls.env["ir.config_parameter"].sudo()

    def _allow_here(self):
        self.ICP.set_param(
            "petspot_fulfillment_vetution.synthetic_policy_allowed_dbs",
            self.env.cr.dbname,
        )

    def _disallow_here(self):
        self.ICP.set_param("petspot_fulfillment_vetution.synthetic_policy_allowed_dbs", "")

    def test_seeded_values(self):
        p = self.synthetic
        self.assertTrue(p.is_synthetic_test)
        self.assertEqual(p.version, "TEST-SYNTHETIC-E2E")
        self.assertEqual(p.policy_environment, "test_only")
        self.assertFalse(p.allow_price_publish)
        self.assertTrue(p.allow_auto_quotation)
        self.assertTrue(p.allow_customer_message)
        self.assertTrue(p.allow_supplier_po)
        self.assertEqual(p.max_auto_delivery_subsidy, 0.0)
        self.assertEqual(p.customer_delivery_charge_amount, 118.0)
        self.assertIn("NOT FOR COMMERCE", p.fulfillment_origin_note or "")
        self.assertIn("NEVER COPY TO PRODUCTION", p.fulfillment_origin_note or "")

        pkg = self.env["petspot.vetution.packaging.cost"].search(
            [("policy_id", "=", p.id), ("packaging_type", "=", "small_box")], limit=1
        )
        self.assertEqual(pkg.amount, 10.0)
        env_pkg = self.env["petspot.vetution.packaging.cost"].search(
            [("policy_id", "=", p.id), ("packaging_type", "=", "envelope")], limit=1
        )
        self.assertEqual(env_pkg.amount, 5.0)

        fee = self.env["petspot.vetution.payment.fee"].search(
            [("policy_id", "=", p.id), ("payment_method", "=", "paymob")], limit=1
        )
        self.assertEqual(fee.percent, 3.0)
        self.assertEqual(fee.fixed_amount, 3.0)

        rule = self.env["petspot.vetution.delivery.revenue.rule"].search(
            [("policy_id", "=", p.id)], limit=1
        )
        self.assertEqual(rule.customer_charge, 118.0)

    def test_get_active_policy_excludes_synthetic_by_default(self):
        self._disallow_here()
        others = self.Policy.search(
            [("id", "!=", self.synthetic.id), ("active", "=", True), ("is_synthetic_test", "=", False)]
        )
        if not others:
            with self.assertRaises(UserError):
                self.Policy.get_active_policy(self.env.company)
        else:
            active = self.Policy.get_active_policy(self.env.company)
            self.assertFalse(active.is_synthetic_test)

    def test_get_active_policy_falls_back_to_synthetic_when_allowlisted(self):
        others = self.Policy.search(
            [("id", "!=", self.synthetic.id), ("active", "=", True), ("is_synthetic_test", "=", False)]
        )
        others.write({"active": False})
        # Fixture is inactive by default — get_active_policy must activate it
        # when the DB is allowlisted and no commercial policy is active.
        self.synthetic.write({"active": False})
        try:
            self._disallow_here()
            with self.assertRaises(UserError):
                self.Policy.get_active_policy(self.env.company)

            self._allow_here()
            active = self.Policy.get_active_policy(self.env.company)
            self.assertEqual(active.id, self.synthetic.id)
            self.assertTrue(active.active)
        finally:
            others.write({"active": True})
            self.synthetic.write({"active": False})
            self._disallow_here()

    def test_get_synthetic_test_policy_requires_allowlist(self):
        self._disallow_here()
        with self.assertRaises(UserError):
            self.Policy.get_synthetic_test_policy(self.env.company)

    def test_get_synthetic_test_policy_succeeds_when_allowlisted(self):
        self._allow_here()
        try:
            p = self.Policy.get_synthetic_test_policy(self.env.company)
            self.assertEqual(p.id, self.synthetic.id)
        finally:
            self._disallow_here()

    def test_shadow_gate_never_allows_price_publish(self):
        self.assertFalse(self.synthetic.allow_price_publish)

    def test_non_synthetic_policy_defaults_locked(self):
        real = self.Policy.create(
            {
                "name": "Non-synthetic candidate",
                "version": "v-test",
            }
        )
        self.assertFalse(real.is_synthetic_test)
        self.assertFalse(real.allow_auto_quotation)
        self.assertFalse(real.allow_customer_message)
        self.assertFalse(real.allow_supplier_po)
        self.assertFalse(real.allow_price_publish)
        self.assertEqual(real.policy_environment, "test_only")
        self.assertEqual(real.max_auto_delivery_subsidy, 0.0)
