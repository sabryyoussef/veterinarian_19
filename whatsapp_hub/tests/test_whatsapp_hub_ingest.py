# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase, tagged, new_test_user


@tagged("post_install", "-at_install", "whatsapp_hub")
class TestWhatsappHubIngest(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.service = new_test_user(
            cls.env,
            login="wa_hub_ingest_svc",
            groups="whatsapp_hub.group_whatsapp_ingest_service",
        )

    def test_ingest_idempotent(self):
        Message = self.env["whatsapp.message"].with_user(self.service)
        payload = {
            "group_jid": "120363411424964076@g.us",
            "group_name": "testopenclow",
            "chatwoot_account_id": 1,
            "chatwoot_inbox_id": 2,
            "chatwoot_conversation_id": 9001,
            "chatwoot_message_id": 800001,
            "text": "Please add a filter on the Dev Hub report menu.",
            "sender_jid": "201003670502@s.whatsapp.net",
            "sender_name": "Sabry",
        }
        first = Message.service_ingest_normalized(payload)
        self.assertFalse(first.get("duplicate"))
        self.assertTrue(first.get("message_id"))
        second = Message.service_ingest_normalized(payload)
        self.assertTrue(second.get("duplicate"))
        self.assertEqual(first["message_id"], second["message_id"])
        self.assertEqual(
            self.env["whatsapp.message"].search_count(
                [("chatwoot_message_id", "=", 800001)]
            ),
            1,
        )

    def test_group_jid_created(self):
        Message = self.env["whatsapp.message"].with_user(self.service)
        Message.service_ingest_normalized(
            {
                "group_jid": "120363422104853335@g.us",
                "chatwoot_message_id": 800002,
                "chatwoot_conversation_id": 9002,
                "chatwoot_account_id": 1,
                "text": "Hello group",
                "sender_jid": "201000000001@s.whatsapp.net",
            }
        )
        group = self.env["whatsapp.group"].search(
            [("jid", "=", "120363422104853335@g.us")], limit=1
        )
        self.assertTrue(group)

    def test_outbound_queue_creates_message(self):
        manager = new_test_user(
            self.env,
            login="wa_hub_manager",
            groups="whatsapp_hub.group_whatsapp_manager",
        )
        Out = self.env["whatsapp.outbound.message"].with_user(manager)
        result = Out.service_queue_outbound(
            {
                "destination": "201000000000",
                "body": "Hub outbound UAT",
                "purpose": "other",
                "send_now": False,
            }
        )
        self.assertTrue(result.get("outbound_id"))
        self.assertTrue(result.get("message_id"))
        msg = self.env["whatsapp.message"].browse(result["message_id"])
        self.assertEqual(msg.direction, "out")
        self.assertEqual(msg.state, "queued")
