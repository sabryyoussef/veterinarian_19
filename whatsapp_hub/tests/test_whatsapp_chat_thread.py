# -*- coding: utf-8 -*-
import base64

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install", "whatsapp_hub")
class TestWhatsappMediaKind(TransactionCase):
    def test_classify_image_placeholder(self):
        Message = self.env["whatsapp.message"]
        self.assertEqual(
            Message._classify_media_kind("[image]", "", ""),
            "image",
        )
        self.assertEqual(
            Message._classify_media_kind("", "media_type=audio", ""),
            "audio",
        )
        self.assertEqual(
            Message._classify_media_kind("hello", "", ""),
            "none",
        )


@tagged("post_install", "-at_install", "whatsapp_hub")
class TestWhatsappChatThread(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Conversation = cls.env["whatsapp.conversation"]
        cls.Message = cls.env["whatsapp.message"]
        cls.conversation = cls.Conversation.create(
            {
                "name": "Test Chat Thread",
                "conversation_type": "dm",
                "purpose": "other",
                "remote_jid": "201000000001@s.whatsapp.net",
                "identity_key": "test-chat-thread-identity-key",
            }
        )

    def _make_message(self, **vals):
        defaults = {
            "direction": "in",
            "state": "received",
            "body": "hello",
            "conversation_id": self.conversation.id,
            "dedupe_key": f"test-dedupe-{self.Message.search_count([])}-{vals.get('body', '')}",
            "message_timestamp": "2026-07-20 10:00:00",
        }
        defaults.update(vals)
        if "dedupe_key" in vals:
            defaults["dedupe_key"] = vals["dedupe_key"]
        return self.Message.create(defaults)

    def test_get_thread_messages_order_and_noise(self):
        m1 = self._make_message(
            body="first",
            dedupe_key="thread-1",
            message_timestamp="2026-07-20 10:00:00",
        )
        m2 = self._make_message(
            body="[sticker]",
            media_kind="sticker",
            has_media=True,
            dedupe_key="thread-2",
            message_timestamp="2026-07-20 10:01:00",
        )
        m3 = self._make_message(
            body="second",
            direction="out",
            dedupe_key="thread-3",
            message_timestamp="2026-07-20 10:02:00",
        )
        m4 = self._make_message(
            body="hidden one",
            is_hidden=True,
            dedupe_key="thread-4",
            message_timestamp="2026-07-20 10:03:00",
        )
        data = self.conversation.get_thread_messages(hide_noise=True, show_hidden=False)
        ids = [m["id"] for m in data["messages"]]
        self.assertIn(m1.id, ids)
        self.assertIn(m3.id, ids)
        self.assertNotIn(m2.id, ids)
        self.assertNotIn(m4.id, ids)
        # chronological
        self.assertEqual(ids, sorted(ids, key=lambda i: ids.index(i)))
        self.assertLess(ids.index(m1.id), ids.index(m3.id))

        data_all = self.conversation.get_thread_messages(
            hide_noise=False, show_hidden=True
        )
        all_ids = {m["id"] for m in data_all["messages"]}
        self.assertTrue({m1.id, m2.id, m3.id, m4.id}.issubset(all_ids))

    def test_action_open_chat(self):
        action = self.conversation.action_open_chat()
        self.assertEqual(action["type"], "ir.actions.client")
        self.assertEqual(action["tag"], "whatsapp_hub_conversation_chat")
        self.assertEqual(action["context"]["conversation_id"], self.conversation.id)

        msg = self._make_message(body="open me", dedupe_key="thread-open")
        action2 = msg.action_open_chat()
        self.assertEqual(action2["tag"], "whatsapp_hub_conversation_chat")
        self.assertEqual(action2["context"]["focus_message_id"], msg.id)

    def test_hide_toggle(self):
        msg = self._make_message(body="hide me", dedupe_key="thread-hide")
        msg.action_hide()
        self.assertTrue(msg.is_hidden)
        msg.action_unhide()
        self.assertFalse(msg.is_hidden)

    def test_ingest_stores_media_base64(self):
        # Bypass ACL via sudo (ingest path is service-role gated)
        png = base64.b64encode(
            b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
        ).decode()
        result = self.Message.sudo().service_ingest_normalized(
            {
                "evolution_message_id": "evo-media-test-1",
                "instance_reference": "test-instance",
                "sender_jid": "201000000099@s.whatsapp.net",
                "media_type": "image",
                "media_base64": png,
                "mimetype": "image/png",
                "media_filename": "probe.png",
                "allow_empty": True,
            }
        )
        self.assertFalse(result.get("skipped"))
        message = self.Message.browse(result["message_id"])
        self.assertTrue(message.has_media)
        self.assertEqual(message.media_kind, "image")
        self.assertTrue(message.attachment_ids)
