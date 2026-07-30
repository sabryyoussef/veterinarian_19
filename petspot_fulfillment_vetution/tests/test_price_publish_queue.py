# -*- coding: utf-8 -*-
"""Price Publish Queue tests (Phase 15B) — approval-gated, mock-only publish."""

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install", "petspot_fulfillment_vetution")
class TestPricePublishQueue(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Queue = cls.env["petspot.vetution.price.publish.queue"]
        cls.ICP = cls.env["ir.config_parameter"].sudo()
        cls.product = cls.env["product.product"].create(
            {"name": "PubQ Product", "type": "consu", "list_price": 100.0, "default_code": "PUBQ-1"}
        )

    def test_enqueue_creates_pending(self):
        rec = self.Queue.enqueue(self.product, 120.0)
        self.assertEqual(rec.state, "pending")
        self.assertEqual(rec.current_price, 100.0)
        self.assertEqual(rec.suggested_price, 120.0)

    def test_locked_product_blocks(self):
        self.product.product_tmpl_id.vetution_sale_price_locked = True
        try:
            rec = self.Queue.enqueue(self.product, 130.0)
            self.assertEqual(rec.state, "blocked")
        finally:
            self.product.product_tmpl_id.vetution_sale_price_locked = False

    def test_same_price_noop_blocked(self):
        rec = self.Queue.enqueue(self.product, self.product.lst_price or self.product.list_price)
        self.assertEqual(rec.state, "blocked")

    def test_loop_prevention_reenqueue_same_price_within_window(self):
        first = self.Queue.enqueue(self.product, 140.0)
        second = self.Queue.enqueue(self.product, 140.0)
        self.assertEqual(first.id, second.id)

    def test_different_price_creates_new_row(self):
        first = self.Queue.enqueue(self.product, 150.0)
        second = self.Queue.enqueue(self.product, 160.0)
        self.assertNotEqual(first.id, second.id)

    def test_approve_then_publish_mock_flow(self):
        self.ICP.set_param("petspot_fulfillment_vetution.shopify_publish_transport", "mock")
        rec = self.Queue.enqueue(self.product, 170.0)
        rec.approve()
        self.assertEqual(rec.state, "approved")
        rec.publish_mock()
        self.assertEqual(rec.state, "published")
        self.assertTrue(rec.published_at)

    def test_publish_requires_approved_state(self):
        rec = self.Queue.enqueue(self.product, 180.0)
        with self.assertRaises(UserError):
            rec.publish_mock()

    def test_approve_requires_pending_state(self):
        rec = self.Queue.enqueue(self.product, 190.0)
        rec.approve()
        with self.assertRaises(UserError):
            rec.approve()

    def test_rollback_mock(self):
        rec = self.Queue.enqueue(self.product, 200.0)
        rec.approve()
        rec.publish_mock()
        rec.rollback_mock(reason="test rollback")
        self.assertEqual(rec.state, "rolled_back")

    def test_live_transport_raises_never_calls_shopify(self):
        self.ICP.set_param("petspot_fulfillment_vetution.shopify_publish_transport", "live")
        rec = self.Queue.enqueue(self.product, 210.0)
        rec.approve()
        with self.assertRaises(UserError):
            rec.publish_mock()
        self.assertEqual(rec.state, "approved")
        self.ICP.set_param("petspot_fulfillment_vetution.shopify_publish_transport", "mock")

    def test_default_transport_icp_is_mock(self):
        value = self.ICP.get_param(
            "petspot_fulfillment_vetution.shopify_publish_transport", "mock"
        )
        self.assertEqual((value or "mock").strip().lower(), "mock")
