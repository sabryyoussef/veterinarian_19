# -*- coding: utf-8 -*-
"""Recovery hardening: historical non-mutation + Whisper circuit breaker."""
from __future__ import annotations

import uuid
from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, new_test_user, tagged

from odoo.addons.devhub_whatsapp.models.dev_whatsapp_historical_guard import (
    CTX_NON_MUTATING,
)


@tagged("post_install", "-at_install", "devhub_whatsapp")
class TestWhatsappMediaRecoveryHardening(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["dev.whatsapp.media.job"].sudo().search(
            [("state", "in", ["pending", "leased", "processing", "retry"])]
        ).with_context(dev_wa_media_action=True).write({"state": "cancelled"})
        ICP = cls.env["ir.config_parameter"].sudo()
        ICP.set_param("devhub_whatsapp.media_transcription_circuit_open_until", False)
        ICP.set_param("devhub_whatsapp.media_transcription_circuit_last_rate", False)
        ICP.set_param("devhub_whatsapp.media_transcription_circuit_lookback_sec", "1")
        cls.manager = new_test_user(
            cls.env,
            login="wa_rec_mgr",
            groups="devhub_core.group_dev_hub_manager,base.group_user",
        )
        cls.service = new_test_user(
            cls.env,
            login="wa_rec_svc",
            groups="devhub_whatsapp.group_dev_hub_wa_media_service,base.group_user",
        )
        cls.project = cls.env["dev.project"].sudo().create(
            {
                "name": "WA Recovery Project",
                "code": "WA_REC",
                "owner_id": cls.manager.id,
                "member_ids": [(4, cls.manager.id)],
                "production_policy": "Test only.",
                "analysis_source_mode": "work_item",
            }
        )
        cls.source = cls.env["dev.whatsapp.source"].sudo().create(
            {
                "name": "Recovery Group",
                "group_jid": "120363999100000099@g.us",
                "dev_project_id": cls.project.id,
                "active": True,
                "historical_review_enabled": True,
                "historical_review_lane": "confirmed_single",
                "project_mapping_state": "confirmed",
                "project_mapping_confidence": 1.0,
                "project_mapping_evidence": "test",
                "require_human_confirm": True,
            }
        )
        cls.conv = cls.env["whatsapp.conversation"].sudo().create(
            {
                "name": "Recovery Conv",
                "remote_jid": cls.source.group_jid,
                "conversation_type": "group",
                "purpose": "other",
            }
        )

    def _msg(self, inbox_state="untriaged", media_kind="audio"):
        token = uuid.uuid4().hex
        return (
            self.env["whatsapp.message"]
            .sudo()
            .create(
                {
                    "conversation_id": self.conv.id,
                    "dh_source_id": self.source.id,
                    "group_jid": self.source.group_jid,
                    "direction": "in",
                    "body": "[%s]" % media_kind,
                    "media_kind": media_kind,
                    "has_media": True,
                    "sender_jid": "201000000099@s.whatsapp.net",
                    "inbox_state": inbox_state,
                    "message_timestamp": fields.Datetime.now() - timedelta(hours=1),
                    "state": "received",
                    "provider": "evolution",
                    "instance_reference": "sabry min",
                    "evolution_message_id": token[:24],
                    "provider_message_id": token[:24],
                    "dedupe_key": "wa-rec:%s" % token,
                }
            )
        )

    def _historical_media(self, message, media_type="audio"):
        Media = self.env["dev.whatsapp.media"].sudo()
        media = Media._ensure_for_message(message, is_historical_review=True)
        media.write(
            {
                "media_type": media_type,
                "retrieval_state": "downloaded",
                "mime_type": "audio/ogg" if media_type == "audio" else "image/png",
                "attachment_id": self.env["ir.attachment"]
                .sudo()
                .create(
                    {
                        "name": "t.bin",
                        "datas": "QUFBQQ==",
                        "res_model": "whatsapp.message",
                        "res_id": message.id,
                        "mimetype": "audio/ogg"
                        if media_type == "audio"
                        else "image/png",
                    }
                )
                .id,
            }
        )
        return media

    def test_historical_whitelist_admission_skips_historical_media(self):
        msg = self._msg(inbox_state="untriaged")
        self._historical_media(msg)
        before = msg.inbox_state
        work_before = self.env["dev.work.item"].sudo().search_count([])
        msg.with_user(self.manager).action_inbox_add()
        msg.invalidate_recordset()
        self.assertEqual(msg.inbox_state, before)
        self.assertTrue(
            self.env["dev.whatsapp.inbox.event"]
            .sudo()
            .search_count(
                [
                    ("message_id", "=", msg.id),
                    ("event_type", "=", "historical_skip"),
                ]
            )
        )
        self.assertEqual(
            self.env["dev.work.item"].sudo().search_count([]), work_before
        )

    def test_context_guard_blocks_inbox_mutation(self):
        msg = self._msg(inbox_state="untriaged")
        with self.assertRaises(ValidationError):
            msg.with_user(self.manager).with_context(
                **{CTX_NON_MUTATING: True}
            ).action_inbox_add()
        self.assertEqual(msg.inbox_state, "untriaged")

    def test_media_download_complete_does_not_mutate_inbox(self):
        import base64

        msg = self._msg(inbox_state="untriaged", media_kind="image")
        Media = self.env["dev.whatsapp.media"].sudo()
        media = Media._ensure_for_message(msg, is_historical_review=True)
        Job = self.env["dev.whatsapp.media.job"].sudo()
        job = Job._enqueue_download(media)
        Job.search(
            [
                ("id", "!=", job.id),
                ("state", "in", ["pending", "retry", "leased", "processing"]),
            ]
        ).with_context(dev_wa_media_action=True).write({"state": "cancelled"})
        out = Job.with_user(self.service).service_lease(limit=1, lease_seconds=300)
        leased = out["jobs"][0]
        png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
        )
        Job.with_user(self.service).service_complete(
            leased["job_id"],
            leased["correlation_id"],
            leased["lease_token"],
            {
                "media_bytes_b64": base64.b64encode(png).decode(),
                "mime_type": "image/png",
                "filename": "x.png",
            },
        )
        msg.invalidate_recordset()
        self.assertEqual(msg.inbox_state, "untriaged")

    def test_provider_http_500_retries_with_backoff(self):
        ICP = self.env["ir.config_parameter"].sudo()
        ICP.set_param("devhub_whatsapp.media_transcription_circuit_open_until", False)
        ICP.set_param("devhub_whatsapp.media_transcription_circuit_lookback_sec", "1")
        msg = self._msg()
        media = self._historical_media(msg)
        Job = self.env["dev.whatsapp.media.job"].sudo()
        job = Job._enqueue_enrichment_kind(media, "audio_transcription", force=True)
        # Cancel unrelated open jobs so this unit leases deterministically.
        Job.search(
            [
                ("id", "!=", job.id),
                ("state", "in", ["pending", "retry", "leased", "processing"]),
            ]
        ).with_context(dev_wa_media_action=True).write({"state": "cancelled"})
        leased = Job.with_user(self.service).with_context(
            dev_wa_media_bypass_transcription_circuit=True
        ).service_lease(limit=5, lease_seconds=300)
        self.assertTrue(leased["jobs"], "expected leased jobs")
        target = next(j for j in leased["jobs"] if j["job_id"] == job.id)
        Job.with_user(self.service).service_fail(
            target["job_id"],
            target["correlation_id"],
            target["lease_token"],
            error_code="provider_outage",
            error_summary="Whisper HTTP 500",
            provider_response={"http_status": 500, "retry_after": 5},
            retryable=True,
        )
        job.invalidate_recordset()
        self.assertEqual(job.state, "retry")
        self.assertTrue(job.next_attempt_at)

    def test_transcription_circuit_blocks_whisper_not_ocr(self):
        ICP = self.env["ir.config_parameter"].sudo()
        ICP.set_param("devhub_whatsapp.media_transcription_circuit_open_until", False)
        ICP.set_param("devhub_whatsapp.media_transcription_circuit_lookback_sec", "3600")
        ICP.set_param("devhub_whatsapp.media_transcription_circuit_window", "5")
        ICP.set_param(
            "devhub_whatsapp.media_transcription_circuit_threshold_pct", "10"
        )
        Job = self.env["dev.whatsapp.media.job"].sudo()
        Job.search(
            [("state", "in", ["pending", "retry", "leased", "processing"])]
        ).with_context(dev_wa_media_action=True).write({"state": "cancelled"})
        # Seed recent Whisper provider failures to open the circuit.
        for _ in range(3):
            msg = self._msg()
            media = self._historical_media(msg)
            job = Job._enqueue_enrichment_kind(
                media, "audio_transcription", force=True
            )
            job.with_context(dev_wa_media_action=True).write(
                {
                    "state": "dead_letter",
                    "attempt_count": 3,
                    "last_error_code": "provider_outage",
                    "last_error_summary": "Whisper HTTP 500",
                    "completed_at": fields.Datetime.now(),
                }
            )
        img_msg = self._msg(media_kind="image")
        img_media = self._historical_media(img_msg, media_type="image")
        ocr = Job._enqueue_enrichment_kind(img_media, "image_ocr", force=True)
        audio_msg = self._msg()
        audio_media = self._historical_media(audio_msg)
        audio = Job._enqueue_enrichment_kind(
            audio_media, "audio_transcription", force=True
        )
        leased = Job.with_user(self.service).service_lease(limit=10, lease_seconds=300)
        leased_ids = {j["job_id"] for j in leased["jobs"]}
        self.assertTrue(leased.get("transcription_circuit_open"))
        self.assertIn(ocr.id, leased_ids)
        self.assertNotIn(audio.id, leased_ids)

    def test_circuit_force_closed_allows_whisper_lease(self):
        ICP = self.env["ir.config_parameter"].sudo()
        Job = self.env["dev.whatsapp.media.job"].sudo()
        Job.search(
            [("state", "in", ["pending", "retry", "leased", "processing"])]
        ).with_context(dev_wa_media_action=True).write({"state": "cancelled"})
        for _ in range(3):
            msg = self._msg()
            media = self._historical_media(msg)
            job = Job._enqueue_enrichment_kind(
                media, "audio_transcription", force=True
            )
            job.with_context(dev_wa_media_action=True).write(
                {
                    "state": "dead_letter",
                    "attempt_count": 3,
                    "last_error_code": "provider_outage",
                    "completed_at": fields.Datetime.now(),
                }
            )
        ICP.set_param(
            "devhub_whatsapp.media_transcription_circuit_force_closed_until",
            fields.Datetime.to_string(fields.Datetime.now() + timedelta(minutes=10)),
        )
        ICP.set_param("devhub_whatsapp.media_transcription_circuit_lookback_sec", "3600")
        ICP.set_param("devhub_whatsapp.media_transcription_circuit_window", "5")
        ICP.set_param(
            "devhub_whatsapp.media_transcription_circuit_threshold_pct", "10"
        )
        audio_msg = self._msg()
        audio_media = self._historical_media(audio_msg)
        audio = Job._enqueue_enrichment_kind(
            audio_media, "audio_transcription", force=True
        )
        self.assertFalse(Job._transcription_circuit_open())
        leased = Job.with_user(self.service).service_lease(limit=5, lease_seconds=300)
        leased_ids = {j["job_id"] for j in leased["jobs"]}
        self.assertIn(audio.id, leased_ids)

    def test_evaluation_cannot_create_or_attach_work(self):
        Analysis = self.env["dev.whatsapp.analysis"].sudo()
        msg = self._msg(inbox_state="untriaged")
        analysis = Analysis.create(
            {
                "name": "eval-safety",
                "source_id": self.source.id,
                "dev_project_id": self.project.id,
                "group_jid": self.source.group_jid,
                "batch_fingerprint": "eval-safety-%s" % uuid.uuid4().hex,
                "correlation_id": str(uuid.uuid4()),
                "state": "awaiting_review",
                "requested_at": fields.Datetime.now(),
                "is_evaluation_result": True,
                "historical_review_lane": "confirmed_single",
                "contains_work": True,
                "work_title": "x",
                "work_description": "y",
                "batch_message_ids": [(6, 0, [msg.id])],
                "work_message_ids": [(6, 0, [msg.id])],
            }
        )
        with self.assertRaises(UserError):
            analysis.with_user(self.manager).action_approve_create_work()
        with self.assertRaises(UserError):
            analysis.with_user(self.manager).action_approve_ignore()
        self.assertEqual(msg.inbox_state, "untriaged")
