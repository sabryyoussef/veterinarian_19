# -*- coding: utf-8 -*-
from odoo.tests import tagged, TransactionCase, new_test_user
from odoo.exceptions import AccessError


@tagged("post_install", "-at_install", "devhub_whatsapp")
class TestDevhubWhatsappIntake(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.source = cls.env.ref("dev_session_hub.dev_whatsapp_source_testopenclow")
        cls.service = new_test_user(
            cls.env,
            login="wa_intake_service_test",
            groups="devhub_whatsapp.group_dev_hub_whatsapp_intake",
        )

    def test_whitelist_reject_unknown_group(self):
        Intake = self.env["dev.whatsapp.intake"].with_user(self.service)
        result = Intake.service_ingest_message(
            {
                "group_jid": "999999999999999999@g.us",
                "chatwoot_message_id": 900001,
                "chatwoot_conversation_id": 1,
                "text": "Please fix the invoice report for May",
                "sender_jid": "201000000000@s.whatsapp.net",
                "classification": "new_dev_request",
                "confidence": 0.9,
            }
        )
        self.assertTrue(result.get("skipped"))
        self.assertEqual(result.get("reason"), "group_not_whitelisted")

    def test_ingest_creates_candidate_and_is_idempotent(self):
        Intake = self.env["dev.whatsapp.intake"].with_user(self.service)
        payload = {
            "group_jid": self.source.group_jid,
            "chatwoot_account_id": 1,
            "chatwoot_inbox_id": 2,
            "chatwoot_message_id": 900101,
            "chatwoot_conversation_id": 69,
            "text": "The invoice report has a problem when selecting May.",
            "sender_jid": "201003670502@s.whatsapp.net",
            "classification": "new_dev_request",
            "confidence": 0.9,
            "draft_title": "Invoice report May filter",
        }
        first = Intake.service_ingest_message(payload)
        self.assertFalse(first.get("skipped"))
        self.assertTrue(first.get("intake_id"))
        self.assertTrue(first.get("skip_openproject_autocreate"))
        second = Intake.service_ingest_message(payload)
        self.assertTrue(second.get("skipped"))
        self.assertEqual(second.get("reason"), "duplicate_message")
        self.assertEqual(first["intake_id"], second["intake_id"])

    def test_grouping_appends_context(self):
        Intake = self.env["dev.whatsapp.intake"].with_user(self.service)
        base = {
            "group_jid": self.source.group_jid,
            "chatwoot_account_id": 1,
            "chatwoot_inbox_id": 2,
            "chatwoot_conversation_id": 777001,
            "sender_jid": "201003670502@s.whatsapp.net",
            "confidence": 0.91,
        }
        a = Intake.service_ingest_message(
            {
                **base,
                "chatwoot_message_id": 900201,
                "text": "Invoice report problem",
                "classification": "new_dev_request",
            }
        )
        b = Intake.service_ingest_message(
            {
                **base,
                "chatwoot_message_id": 900202,
                "text": "Only some transactions show for May",
                "classification": "context_addition",
            }
        )
        self.assertEqual(a["intake_id"], b["intake_id"])
        intake = self.env["dev.whatsapp.intake"].browse(a["intake_id"])
        self.assertGreaterEqual(len(intake.source_message_ids), 2)

    def test_service_acl_denies_ordinary_user(self):
        user = new_test_user(
            self.env,
            login="wa_ordinary_test",
            groups="base.group_user",
        )
        with self.assertRaises(AccessError):
            self.env["dev.whatsapp.intake"].with_user(user).service_ingest_message(
                {
                    "group_jid": self.source.group_jid,
                    "chatwoot_message_id": 1,
                    "text": "x" * 30,
                }
            )
