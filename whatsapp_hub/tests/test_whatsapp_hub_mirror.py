# -*- coding: utf-8 -*-
"""Phase 1–2: conversation resolver, mirror idempotency, lifecycle sync."""
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged, new_test_user


@tagged("post_install", "-at_install", "whatsapp_hub")
class TestWhatsappHubConversationResolver(TransactionCase):
    def test_same_jid_reuses_conversation(self):
        Conv = self.env["whatsapp.conversation"].sudo()
        a = Conv.resolve_conversation(
            remote_jid="201000000111",
            purpose="crm",
            instance_reference="inst-a",
            name="Partner A",
        )
        b = Conv.resolve_conversation(
            remote_jid="201000000111@s.whatsapp.net",
            purpose="crm",
            instance_reference="inst-a",
            name="Partner A again",
        )
        self.assertEqual(a.id, b.id)
        self.assertTrue(a.identity_key)
        self.assertEqual(a.remote_jid, "201000000111@s.whatsapp.net")

    def test_different_jid_different_conversation(self):
        Conv = self.env["whatsapp.conversation"].sudo()
        a = Conv.resolve_conversation(
            remote_jid="201000000211",
            purpose="crm",
            instance_reference="inst-a",
        )
        b = Conv.resolve_conversation(
            remote_jid="201000000212",
            purpose="crm",
            instance_reference="inst-a",
        )
        self.assertNotEqual(a.id, b.id)

    def test_same_jid_different_instance_isolated(self):
        Conv = self.env["whatsapp.conversation"].sudo()
        a = Conv.resolve_conversation(
            remote_jid="201000000311",
            purpose="crm",
            instance_reference="inst-a",
        )
        b = Conv.resolve_conversation(
            remote_jid="201000000311",
            purpose="crm",
            instance_reference="inst-b",
        )
        self.assertNotEqual(a.id, b.id)
        self.assertNotEqual(a.identity_key, b.identity_key)

    def test_same_jid_different_purpose_isolated(self):
        Conv = self.env["whatsapp.conversation"].sudo()
        a = Conv.resolve_conversation(
            remote_jid="201000000411",
            purpose="crm",
            instance_reference="inst-a",
        )
        b = Conv.resolve_conversation(
            remote_jid="201000000411",
            purpose="campaign",
            instance_reference="inst-a",
        )
        self.assertNotEqual(a.id, b.id)


@tagged("post_install", "-at_install", "whatsapp_hub")
class TestWhatsappHubMirror(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if "wa.message.log" not in cls.env:
            return
        cls.partner = cls.env["res.partner"].create(
            {"name": "Hub Mirror Partner", "phone": "+201009990001"}
        )
        cls.channel = cls.env["discuss.channel"].create(
            {
                "name": "WA Hub Mirror Channel",
                "wa_partner_id": cls.partner.id,
                "wa_phone": "201009990001",
            }
        )

    def _skip_without_log(self):
        if "wa.message.log" not in self.env:
            self.skipTest("evolution_whatsapp_chat / wa.message.log not installed")

    def test_mirror_twice_one_hub_message(self):
        self._skip_without_log()
        Log = self.env["wa.message.log"].sudo()
        log = Log.create(
            {
                "phone": "201009990001",
                "direction": "out",
                "message_text": "Hello mirror once",
                "wa_message_id": "EVOMIRROR001",
                "delivery_status": "sent",
                "partner_id": self.partner.id,
                "channel_id": self.channel.id,
            }
        )
        Compat = self.env["whatsapp.hub.compat"]
        first = Compat.mirror_wa_message_log(log)
        second = Compat.mirror_wa_message_log(log)
        self.assertTrue(first)
        self.assertEqual(first.id, second.id)
        self.assertEqual(
            self.env["whatsapp.message"].search_count(
                [("wa_message_log_id", "=", log.id)]
            ),
            1,
        )
        self.assertEqual(first.discuss_channel_id, self.channel.id)
        self.assertEqual(first.partner_id, self.partner)

    def test_status_update_same_hub_message(self):
        self._skip_without_log()
        log = self.env["wa.message.log"].sudo().create(
            {
                "phone": "201009990002",
                "direction": "out",
                "message_text": "Status sync",
                "wa_message_id": "EVOMIRROR002",
                "delivery_status": "sent",
                "partner_id": self.partner.id,
            }
        )
        msg = self.env["whatsapp.message"].search(
            [("wa_message_log_id", "=", log.id)], limit=1
        )
        self.assertTrue(msg)
        log.write({"delivery_status": "delivered"})
        msg.invalidate_recordset()
        self.assertEqual(msg.delivery_state, "delivered")
        self.assertEqual(msg.state, "delivered")
        self.assertEqual(
            self.env["whatsapp.message"].search_count(
                [("wa_message_log_id", "=", log.id)]
            ),
            1,
        )

    def test_provider_id_backfill_same_message(self):
        self._skip_without_log()
        log = self.env["wa.message.log"].sudo().create(
            {
                "phone": "201009990003",
                "direction": "out",
                "message_text": "Pending provider id",
                "delivery_status": "pending",
                "partner_id": self.partner.id,
            }
        )
        msg = self.env["whatsapp.message"].search(
            [("wa_message_log_id", "=", log.id)], limit=1
        )
        self.assertTrue(msg)
        self.assertFalse(msg.evolution_message_id)
        log.write({"wa_message_id": "EVOMIRROR003", "delivery_status": "sent"})
        msg.invalidate_recordset()
        self.assertEqual(msg.evolution_message_id, "EVOMIRROR003")
        self.assertEqual(msg.delivery_state, "sent")
        self.assertEqual(
            self.env["whatsapp.message"].search_count(
                [("wa_message_log_id", "=", log.id)]
            ),
            1,
        )

    def test_conversation_reuse_same_jid(self):
        self._skip_without_log()
        Log = self.env["wa.message.log"].sudo()
        log1 = Log.create(
            {
                "phone": "201009990004",
                "direction": "out",
                "message_text": "First",
                "wa_message_id": "EVOMIRROR004A",
                "delivery_status": "sent",
                "partner_id": self.partner.id,
                "channel_id": self.channel.id,
            }
        )
        log2 = Log.create(
            {
                "phone": "201009990004",
                "direction": "out",
                "message_text": "Second",
                "wa_message_id": "EVOMIRROR004B",
                "delivery_status": "sent",
                "partner_id": self.partner.id,
                "channel_id": self.channel.id,
            }
        )
        m1 = self.env["whatsapp.message"].search(
            [("wa_message_log_id", "=", log1.id)], limit=1
        )
        m2 = self.env["whatsapp.message"].search(
            [("wa_message_log_id", "=", log2.id)], limit=1
        )
        self.assertTrue(m1 and m2)
        self.assertEqual(m1.conversation_id, m2.conversation_id)
        self.assertNotEqual(m1.id, m2.id)

    def test_campaign_refs_preserved(self):
        self._skip_without_log()
        if "wa.campaign" not in self.env:
            self.skipTest("wa.campaign missing")
        campaign = self.env["wa.campaign"].create(
            {
                "name": "Hub Mirror Campaign",
                "message": "Hi {name}",
            }
        )
        line = self.env["wa.campaign.line"].create(
            {
                "campaign_id": campaign.id,
                "partner_id": self.partner.id,
                "phone": "201009990005",
                "status": "sent",
                "wa_message_id": "EVOMIRROR005",
            }
        )
        log = self.env["wa.message.log"].sudo().create(
            {
                "phone": "201009990005",
                "direction": "out",
                "message_text": "Campaign body",
                "wa_message_id": "EVOMIRROR005",
                "delivery_status": "sent",
                "partner_id": self.partner.id,
                "campaign_id": campaign.id,
                "campaign_line_id": line.id,
            }
        )
        msg = self.env["whatsapp.message"].search(
            [("wa_message_log_id", "=", log.id)], limit=1
        )
        self.assertTrue(msg)
        self.assertEqual(msg.campaign_id, campaign.id)
        self.assertEqual(msg.campaign_line_id, line.id)
        self.assertEqual(msg.purpose, "campaign")
        self.assertEqual(msg.source_app, "campaign")

    def test_mirror_does_not_trigger_outbound_send(self):
        self._skip_without_log()
        Out = self.env["whatsapp.outbound.message"].sudo()
        before = Out.search_count([])
        with patch(
            "odoo.addons.whatsapp_hub.models.whatsapp_outbound.requests.post"
        ) as mocked:
            self.env["wa.message.log"].sudo().create(
                {
                    "phone": "201009990006",
                    "direction": "out",
                    "message_text": "No outbound from mirror",
                    "wa_message_id": "EVOMIRROR006",
                    "delivery_status": "sent",
                    "partner_id": self.partner.id,
                }
            )
            mocked.assert_not_called()
        self.assertEqual(Out.search_count([]), before)

    def test_no_recursive_hub_log_loop(self):
        self._skip_without_log()
        Log = self.env["wa.message.log"].sudo()
        before = Log.search_count([])
        log = Log.create(
            {
                "phone": "201009990007",
                "direction": "out",
                "message_text": "Loop check",
                "wa_message_id": "EVOMIRROR007",
                "delivery_status": "sent",
                "partner_id": self.partner.id,
            }
        )
        msg = self.env["whatsapp.message"].search(
            [("wa_message_log_id", "=", log.id)], limit=1
        )
        self.assertTrue(msg)
        # Hub write with mirroring context must not create another log
        msg.with_context(whatsapp_hub_mirroring=True).write(
            {"delivery_state": "delivered", "state": "delivered"}
        )
        self.assertEqual(Log.search_count([]), before + 1)

    def test_pilot_ingest_still_works(self):
        service = new_test_user(
            self.env,
            login="wa_hub_ingest_mirror_svc",
            groups="whatsapp_hub.group_whatsapp_ingest_service",
        )
        Message = self.env["whatsapp.message"].with_user(service)
        payload = {
            "group_jid": "120363411424964076@g.us",
            "chatwoot_account_id": 1,
            "chatwoot_conversation_id": 91001,
            "chatwoot_message_id": 810001,
            "text": "Pilot ingest after Phase 1/2",
            "sender_jid": "201003670502@s.whatsapp.net",
        }
        first = Message.service_ingest_normalized(payload)
        second = Message.service_ingest_normalized(payload)
        self.assertFalse(first.get("duplicate"))
        self.assertTrue(second.get("duplicate"))
        self.assertEqual(first["message_id"], second["message_id"])
        msg = self.env["whatsapp.message"].browse(first["message_id"])
        self.assertEqual(msg.source_app, "n8n")
        self.assertEqual(msg.purpose, "chatwoot")
        self.assertTrue(msg.remote_jid)
        self.assertTrue(msg.business_key)
