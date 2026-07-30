# -*- coding: utf-8 -*-
import json

from odoo.tests import tagged, TransactionCase
from odoo.addons.petspot_fulfillment.models.petspot_cta_parser import (
    normalize_eg_phone,
    parse_availability_cta,
    is_availability_cta,
)


def _cta_en(sku="SKU-EN-1", variant_id=None, qty=2, title="Test Product"):
    lines = [
        "Request availability — pet.spot",
        "",
        f"Product: {title}",
        "Variant / pack size: 12.5 Kg",
    ]
    if sku:
        lines.append(f"SKU: {sku}")
    elif variant_id:
        lines.append(f"Variant ID: {variant_id}")
    lines.append("URL: https://shopify.drpaws.ai/products/test-product")
    lines.append(f"Requested quantity: {qty}")
    return "\n".join(lines)


def _cta_ar(sku="SKU-AR-1"):
    # Theme still uses English marker; body may include Arabic product title
    return _cta_en(sku=sku, title="منتج تجريبي")


def _payload(content, message_id="9001", conversation_id="8001", message_type=0,
             account_id=2, inbox_id=2, phone="+201000000099", private=False,
             event="message_created", sender_type="contact"):
    return {
        "event": event,
        "id": int(message_id) if str(message_id).isdigit() else message_id,
        "content": content,
        "message_type": message_type,
        "private": private,
        "account": {"id": account_id},
        "inbox": {"id": inbox_id},
        "conversation": {"id": int(conversation_id), "inbox_id": inbox_id},
        "sender": {
            "id": 501,
            "name": "CTA Customer",
            "phone_number": phone,
            "type": sender_type,
        },
    }


@tagged("post_install", "-at_install", "petspot_fulfillment", "petspot_ff_chatwoot")
class TestPetspotChatwootIntake(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        ICP = cls.env["ir.config_parameter"].sudo()
        ICP.set_param("petspot_fulfillment.chatwoot_intake_enabled", "True")
        ICP.set_param("petspot_fulfillment.chatwoot_webhook_secret", "test-secret-ff")
        ICP.set_param("petspot_fulfillment.chatwoot_account_id", "2")
        ICP.set_param("petspot_fulfillment.chatwoot_inbox_id", "2")
        ICP.set_param("petspot_fulfillment.chatwoot_ack_enabled", "True")
        ICP.set_param("petspot_fulfillment.chatwoot_test_mode", "True")
        ICP.set_param("petspot_fulfillment.chatwoot_api_token", "")
        cls.Event = cls.env["petspot.chatwoot.webhook.event"]
        cls.Inquiry = cls.env["petspot.availability.inquiry"]
        cls.product = cls.env["product.product"].create({
            "name": "FF CTA Product",
            "type": "consu",
            "default_code": "SKU-EN-1",
            "list_price": 50.0,
        })
        cls.product_ar = cls.env["product.product"].create({
            "name": "FF CTA AR Product",
            "type": "consu",
            "default_code": "SKU-AR-1",
            "list_price": 55.0,
        })
        cls.product_var = cls.env["product.product"].create({
            "name": "FF CTA Variant Product",
            "type": "consu",
            "default_code": "SKU-VAR-ONLY",
            "list_price": 60.0,
        })
        if "shopify.variant.map" in cls.env and "shopify.store" in cls.env:
            store = cls.env["shopify.store"].search([], limit=1)
            if not store:
                store = cls.env["shopify.store"].create({
                    "name": "FF Test Store",
                    "shop_url": "ff-test.myshopify.com",
                })
            # field names vary; try minimal
            vals = {
                "store_id": store.id,
                "shopify_product_id": "111",
                "shopify_variant_id": "555001",
                "product_id": cls.product_var.id,
            }
            cls.env["shopify.variant.map"].create(vals)

    def _process(self, payload):
        return self.Event.with_context(petspot_ff_force_intake=True).process_webhook_payload(
            payload, headers={"X-PetSpot-Webhook-Secret": "test-secret-ff"}
        )

    def test_01_valid_english_cta(self):
        res = self._process(_payload(_cta_en(), message_id="1001", conversation_id="2001"))
        self.assertTrue(res.get("ok"))
        inq = self.Inquiry.browse(res["inquiry_id"])
        self.assertEqual(inq.product_id, self.product)
        self.assertTrue(inq.case_id)
        self.assertFalse(inq.sale_order_id)
        self.assertEqual(inq.channel, "whatsapp")
        self.assertTrue(inq.ack_sent)

    def test_02_valid_arabic_title_cta(self):
        res = self._process(_payload(_cta_ar(), message_id="1002", conversation_id="2002"))
        self.assertTrue(res.get("ok"))
        inq = self.Inquiry.browse(res["inquiry_id"])
        self.assertEqual(inq.product_id, self.product_ar)

    def test_03_variant_map_without_sku(self):
        content = _cta_en(sku=None, variant_id="555001")
        res = self._process(_payload(content, message_id="1003", conversation_id="2003"))
        self.assertTrue(res.get("ok"))
        inq = self.Inquiry.browse(res["inquiry_id"])
        self.assertEqual(inq.product_id, self.product_var)
        self.assertFalse(inq.review_required)

    def test_04_egyptian_phone_normalization(self):
        self.assertEqual(normalize_eg_phone("01001234567"), "+201001234567")
        self.assertEqual(normalize_eg_phone("+20 100 123 4567"), "+201001234567")
        self.assertEqual(normalize_eg_phone("201001234567"), "+201001234567")
        res = self._process(_payload(
            _cta_en(sku="SKU-EN-1"),
            message_id="1004",
            conversation_id="2004",
            phone="01009998887",
        ))
        inq = self.Inquiry.browse(res["inquiry_id"])
        self.assertEqual(inq.phone, "+201009998887")

    def test_05_duplicate_webhook_replay(self):
        p = _payload(_cta_en(), message_id="1005", conversation_id="2005")
        r1 = self._process(p)
        r2 = self._process(p)
        self.assertTrue(r2.get("replay"))
        self.assertEqual(r1["inquiry_id"], r2["inquiry_id"])
        self.assertEqual(self.Inquiry.search_count([("message_id", "=", "1005")]), 1)
        self.assertEqual(self.env["sale.order"].search_count([
            ("origin", "ilike", "petspot-inquiry:%s" % r1["inquiry_id"]),
        ]), 0)
        self.assertEqual(self.env["purchase.order"].search_count([
            ("origin", "ilike", "petspot-ff:"),
        ]), 0)

    def test_06_outgoing_agent_ignored(self):
        res = self._process(_payload(
            _cta_en(), message_id="1006", conversation_id="2006",
            message_type=1, sender_type="user",
        ))
        self.assertTrue(res.get("ignored"))
        self.assertEqual(res.get("reason"), "outgoing_message")

    def test_07_regular_whatsapp_ignored(self):
        res = self._process(_payload(
            "Hello, is this available?", message_id="1007", conversation_id="2007",
        ))
        self.assertTrue(res.get("ignored"))
        self.assertEqual(res.get("reason"), "not_availability_cta")
        event = self.Event.browse(res["event_id"])
        self.assertFalse(event.content_preview)
        self.assertEqual(self.Inquiry.search_count([("message_id", "=", "1007")]), 0)
        # Ordinary WA body must not be retained on ignored events
        ev = self.Event.browse(res["event_id"])
        self.assertFalse(ev.content_preview)

    def test_08_unknown_product_review(self):
        res = self._process(_payload(
            _cta_en(sku="DOES-NOT-EXIST-SKU"),
            message_id="1008", conversation_id="2008",
        ))
        self.assertTrue(res.get("ok"))
        inq = self.Inquiry.browse(res["inquiry_id"])
        self.assertTrue(inq.review_required)
        self.assertFalse(inq.product_id)
        self.assertEqual(inq.state, "review_required")
        self.assertTrue(inq.case_id)
        self.assertFalse(inq.sale_order_id)

    def test_09_parser_marker(self):
        self.assertTrue(is_availability_cta(_cta_en()))
        parsed = parse_availability_cta(_cta_en(sku="ABC", qty=3))
        self.assertEqual(parsed["sku"], "ABC")
        self.assertEqual(parsed["requested_qty"], 3.0)

    def test_10_no_quotation_rfq_awb(self):
        before_so = self.env["sale.order"].search_count([])
        before_po = self.env["purchase.order"].search_count([])
        before_ship = self.env["shipblu.shipment"].search_count([]) if "shipblu.shipment" in self.env else 0
        self._process(_payload(_cta_en(), message_id="1010", conversation_id="2010"))
        self.assertEqual(self.env["sale.order"].search_count([]), before_so)
        self.assertEqual(self.env["purchase.order"].search_count([]), before_po)
        if "shipblu.shipment" in self.env:
            self.assertEqual(self.env["shipblu.shipment"].search_count([]), before_ship)


@tagged("post_install", "-at_install", "petspot_fulfillment", "petspot_ff_chatwoot")
class TestPetspotChatwootWebhookAuth(TransactionCase):

    def test_unauthorized_secret_and_health(self):
        ICP = self.env["ir.config_parameter"].sudo()
        ICP.set_param("petspot_fulfillment.chatwoot_webhook_secret", "http-secret")
        ICP.set_param("petspot_fulfillment.chatwoot_intake_enabled", "True")
        Event = self.env["petspot.chatwoot.webhook.event"]
        self.assertFalse(Event.validate_webhook_secret({}))
        self.assertFalse(Event.validate_webhook_secret({"X-PetSpot-Webhook-Secret": "wrong"}))
        self.assertTrue(Event.validate_webhook_secret({"X-PetSpot-Webhook-Secret": "http-secret"}))
        self.assertTrue(Event.validate_webhook_secret({"Authorization": "Bearer http-secret"}))
        # Malformed handling is controller-level; simulate JSON error path expectation
        self.assertEqual(
            Event.process_webhook_payload({"event": "message_created"}),
            {"ok": False, "error": "missing_ids", "status": 400},
        )
