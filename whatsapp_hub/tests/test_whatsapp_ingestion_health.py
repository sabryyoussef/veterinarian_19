# -*- coding: utf-8 -*-
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests import TransactionCase, tagged, new_test_user


@tagged("post_install", "-at_install", "whatsapp_hub")
class TestWhatsappIngestionHealth(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.service = new_test_user(
            cls.env,
            login="wa_hub_ingest_health_svc",
            groups="whatsapp_hub.group_whatsapp_ingest_service",
        )
        cls.Message = cls.env["whatsapp.message"].with_user(cls.service)
        cls.Health = cls.env["whatsapp.ingestion.health"].sudo()
        cls.Recovery = cls.env["whatsapp.evolution.recovery"].sudo()

    def _evo_payload(self, evo_id, text="hello recovery", **extra):
        payload = {
            "group_jid": "120363499999999999@g.us",
            "group_name": "health-test-group",
            "evolution_message_id": evo_id,
            "provider_message_id": evo_id,
            "instance_reference": "health-test-instance",
            "evolution_instance": "health-test-instance",
            "text": text,
            "body": text,
            "sender_jid": "201003670502@s.whatsapp.net",
            "sender_name": "Sabry",
            "message_timestamp": fields.Datetime.now(),
        }
        payload.update(extra)
        return payload

    def test_duplicate_evolution_ingest_updates_health(self):
        payload = self._evo_payload("EVO-HEALTH-DUP-1")
        first = self.Message.service_ingest_normalized(payload)
        self.assertFalse(first.get("duplicate"))
        self.assertTrue(first.get("message_id"))
        self.assertTrue(first.get("conversation_id"))

        health = self.Health.search(
            [("conversation_id", "=", first["conversation_id"])], limit=1
        )
        self.assertTrue(health)
        self.assertEqual(health.health_status, "healthy")
        self.assertEqual(health.last_external_message_id, "EVO-HEALTH-DUP-1")
        self.assertEqual(health.consecutive_failure_count, 0)

        second = self.Message.service_ingest_normalized(payload)
        self.assertTrue(second.get("duplicate"))
        self.assertEqual(first["message_id"], second["message_id"])
        self.assertEqual(
            self.env["whatsapp.message"].search_count(
                [("evolution_message_id", "=", "EVO-HEALTH-DUP-1")]
            ),
            1,
        )

    def test_gap_detection_when_provider_newer(self):
        payload = self._evo_payload("EVO-HEALTH-GAP-1")
        result = self.Message.service_ingest_normalized(payload)
        health = self.Health.search(
            [("conversation_id", "=", result["conversation_id"])], limit=1
        )
        self.assertTrue(health)
        # Simulate successful ingest in the past, then a newer provider event
        # beyond the stall threshold (provider heard, Hub not catching up).
        past = fields.Datetime.now() - timedelta(minutes=45)
        health.write(
            {
                "last_successful_ingestion_at": past,
                "last_provider_event_at": past,
                "stall_threshold_minutes": 30,
                "gap_detected": False,
            }
        )
        health.record_provider_event(
            external_id="EVO-HEALTH-GAP-PROVIDER",
            event_at=fields.Datetime.now(),
        )
        self.assertTrue(health.gap_detected)
        self.assertIn(health.health_status, ("gap_detected", "delayed", "failed"))

    def test_inactive_conversation_is_idle_not_delayed(self):
        """Old last-ingest with no fresher provider event => idle, not delayed."""
        payload = self._evo_payload("EVO-HEALTH-IDLE-1")
        result = self.Message.service_ingest_normalized(payload)
        health = self.Health.search(
            [("conversation_id", "=", result["conversation_id"])], limit=1
        )
        self.assertTrue(health)
        past = fields.Datetime.now() - timedelta(minutes=120)
        # Provider event == last successful ingest (both old): quiet chat.
        health.write(
            {
                "last_successful_ingestion_at": past,
                "last_provider_event_at": past,
                "stall_threshold_minutes": 30,
                "gap_detected": False,
                "consecutive_failure_count": 0,
                "recovery_state": "idle",
            }
        )
        health.recompute_health_status()
        self.assertEqual(health.health_status, "idle")
        delayed, gap = health._should_flag_gap_or_delay()
        self.assertFalse(delayed)
        self.assertFalse(gap)

    def test_missing_freshness_data_is_unknown(self):
        """Row with neither successful ingest nor provider event => unknown."""
        payload = self._evo_payload("EVO-HEALTH-UNK-1")
        result = self.Message.service_ingest_normalized(payload)
        health = self.Health.search(
            [("conversation_id", "=", result["conversation_id"])], limit=1
        )
        self.assertTrue(health)
        health.write(
            {
                "last_successful_ingestion_at": False,
                "last_provider_event_at": False,
                "gap_detected": False,
                "consecutive_failure_count": 0,
                "recovery_state": "idle",
            }
        )
        health.recompute_health_status()
        self.assertEqual(health.health_status, "unknown")

    def test_provider_ahead_within_threshold_is_delayed(self):
        """Provider event newer than last ingest (sub-threshold) => delayed."""
        payload = self._evo_payload("EVO-HEALTH-DELAY-1")
        result = self.Message.service_ingest_normalized(payload)
        health = self.Health.search(
            [("conversation_id", "=", result["conversation_id"])], limit=1
        )
        self.assertTrue(health)
        now = fields.Datetime.now()
        health.write(
            {
                "last_successful_ingestion_at": now - timedelta(minutes=20),
                "last_provider_event_at": now - timedelta(minutes=5),
                "stall_threshold_minutes": 30,
                "gap_detected": False,
                "consecutive_failure_count": 0,
                "recovery_state": "idle",
            }
        )
        health.recompute_health_status()
        self.assertEqual(health.health_status, "delayed")

    def test_recent_ingest_is_healthy(self):
        payload = self._evo_payload("EVO-HEALTH-OK-1")
        result = self.Message.service_ingest_normalized(payload)
        health = self.Health.search(
            [("conversation_id", "=", result["conversation_id"])], limit=1
        )
        self.assertTrue(health)
        self.assertEqual(health.health_status, "healthy")

    def test_normalize_and_idempotent_recovery_pass(self):
        raw = {
            "key": {
                "id": "EVO-HEALTH-NORM-1",
                "remoteJid": "120363488888888888@g.us",
                "fromMe": False,
                "participant": "201003670502@s.whatsapp.net",
            },
            "message": {"conversation": "Normalized recovery text"},
            "messageTimestamp": 1720000000,
            "pushName": "Sabry",
            "messageType": "conversation",
        }
        payload = self.Recovery.normalize_evolution_upsert(raw, "health-test-instance")
        self.assertTrue(payload)
        self.assertEqual(payload["evolution_message_id"], "EVO-HEALTH-NORM-1")
        self.assertEqual(payload["group_jid"], "120363488888888888@g.us")
        self.assertEqual(payload["direction"], "in")
        self.assertIn("Normalized recovery text", payload["body"])

        first = self.Message.service_ingest_normalized(payload)
        self.assertFalse(first.get("duplicate"))
        second = self.Message.service_ingest_normalized(payload)
        self.assertTrue(second.get("duplicate"))
        self.assertEqual(first["message_id"], second["message_id"])

        # recover_conversation with mocked Evolution HTTP → same payloads, idempotent
        conv = self.env["whatsapp.conversation"].browse(first["conversation_id"])
        with patch.object(
            type(self.Recovery),
            "_fetch_find_messages",
            return_value=[raw],
        ):
            result = self.Recovery.recover_conversation(conv, limit=10)
        self.assertEqual(result["created"], 0)
        self.assertGreaterEqual(result["existing"], 1)
        self.assertEqual(result["errors"], [])
