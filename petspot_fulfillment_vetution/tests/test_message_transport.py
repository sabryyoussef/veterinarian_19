# -*- coding: utf-8 -*-
"""Chatwoot mock transport + message template tests (Phase 15B)."""

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.petspot_fulfillment_vetution.services.chatwoot_transport import (
    ChatwootTransport,
)


@tagged("post_install", "-at_install", "petspot_fulfillment_vetution")
class TestMessageTransport(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({"name": "Msg Transport Customer"})
        cls.product = cls.env["product.product"].create(
            {"name": "Msg Transport Product", "type": "consu", "default_code": "MSGTX-1"}
        )
        cls.ICP = cls.env["ir.config_parameter"].sudo()

    def _make_inquiry(self):
        return self.env["petspot.availability.inquiry"].create(
            {
                "phone": "+201000000099",
                "partner_id": self.partner.id,
                "product_id": self.product.id,
                "default_code": self.product.default_code,
                "requested_qty": 1.0,
                "requested_fulfillment": "store_pickup",
                "channel": "manual",
                "conversation_id": f"msg-conv-{fields.Datetime.now()}",
                "message_id": f"msg-msg-{fields.Datetime.now()}",
            }
        )

    def test_mock_transport_never_http_and_logs(self):
        self.ICP.set_param("petspot_fulfillment_vetution.chatwoot_transport", "mock")
        inquiry = self._make_inquiry()
        log = ChatwootTransport(self.env).send_template(
            inquiry, "checking", context_dict={}
        )
        self.assertEqual(log.transport, "mock")
        self.assertEqual(log.state, "sent")
        self.assertTrue(log.external_message_id.startswith("mock-"))

    def test_idempotent_same_context_returns_existing_log(self):
        inquiry = self._make_inquiry()
        first = ChatwootTransport(self.env).send_template(
            inquiry, "checking", context_dict={"sku": "MSGTX-1"}
        )
        second = ChatwootTransport(self.env).send_template(
            inquiry, "checking", context_dict={"sku": "MSGTX-1"}
        )
        self.assertEqual(first.id, second.id)
        count = self.env["petspot.vetution.message.log"].search_count(
            [("inquiry_id", "=", inquiry.id), ("template_key", "=", "checking")]
        )
        self.assertEqual(count, 1)

    def test_different_context_creates_new_log(self):
        inquiry = self._make_inquiry()
        first = ChatwootTransport(self.env).send_template(
            inquiry, "checking", context_dict={"sku": "A"}
        )
        second = ChatwootTransport(self.env).send_template(
            inquiry, "checking", context_dict={"sku": "B"}
        )
        self.assertNotEqual(first.id, second.id)

    def test_live_transport_raises_when_not_forced_mock(self):
        self.ICP.set_param("petspot_fulfillment_vetution.chatwoot_transport", "live")
        inquiry = self._make_inquiry()
        with self.assertRaises(UserError):
            ChatwootTransport(self.env, force_mock=False).send_template(
                inquiry, "checking", context_dict={"live_attempt": True}
            )
        self.ICP.set_param("petspot_fulfillment_vetution.chatwoot_transport", "mock")

    def test_render_bilingual_templates(self):
        Template = self.env["petspot.vetution.message.template"]
        en = Template.search([("key", "=", "quotation_ready"), ("lang", "=", "en")], limit=1)
        ar = Template.search([("key", "=", "quotation_ready"), ("lang", "=", "ar")], limit=1)
        self.assertTrue(en, "English quotation_ready template must be seeded")
        self.assertTrue(ar, "Arabic quotation_ready template must be seeded")
        self.assertNotEqual(en.body_text, ar.body_text)

    def test_missing_template_raises(self):
        with self.assertRaises(UserError):
            self.env["petspot.vetution.message.template"].render(
                "does_not_exist_template_key", "en", {}
            )

    def test_all_required_keys_seeded_both_langs(self):
        Template = self.env["petspot.vetution.message.template"]
        required = [
            "supplier_available",
            "revised_product_price",
            "delivery_charge_revision",
            "unavailable",
            "checking",
            "quotation_ready",
            "quotation_expired",
            "payment_received",
            "ready_for_pickup",
            "tracking_issued",
            "manual_review_required",
        ]
        for key in required:
            for lang in ("en", "ar"):
                tmpl = Template.search([("key", "=", key), ("lang", "=", lang)], limit=1)
                self.assertTrue(tmpl, f"Missing template key={key} lang={lang}")

    def test_message_log_idempotency_key_format(self):
        inquiry = self._make_inquiry()
        log = ChatwootTransport(self.env).send_template(
            inquiry, "ready_for_pickup", context_dict={"order": inquiry.name}
        )
        self.assertTrue(log.idempotency_key.startswith(f"{inquiry.id}:ready_for_pickup:"))
