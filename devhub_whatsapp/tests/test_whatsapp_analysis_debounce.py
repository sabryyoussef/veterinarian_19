# -*- coding: utf-8 -*-
"""Debounced analysis scheduling + fingerprint idempotency."""
from __future__ import annotations

from datetime import timedelta

from odoo import fields
from odoo.tests import TransactionCase, tagged, new_test_user


@tagged("post_install", "-at_install", "devhub_whatsapp")
class TestWhatsappAnalysisDebounce(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(
            cls.env,
            login="wa_debounce_mgr",
            groups="devhub_core.group_dev_hub_manager,base.group_user",
        )
        Project = cls.env["dev.project"].sudo()
        cls.project = Project.create(
            {
                "name": "WA Debounce Project",
                "code": "wa_debounce",
                "owner_id": cls.manager.id,
                "member_ids": [(4, cls.manager.id)],
                "production_policy": "Test only.",
                "analysis_source_mode": "work_item",
            }
        )
        cls.odoo_project = cls.env["project.project"].sudo().create(
            {"name": "WA Debounce Odoo"}
        )
        cls.source = (
            cls.env["dev.whatsapp.source"]
            .sudo()
            .create(
                {
                    "name": "Debounce Group",
                    "group_jid": "120363999888777010@g.us",
                    "dev_project_id": cls.project.id,
                    "odoo_project_id": cls.odoo_project.id,
                    "ai_triage_enabled": True,
                    "auto_analysis_enabled": True,
                    "analysis_debounce_minutes": 3,
                    "analysis_min_messages": 1,
                    "analysis_review_only": True,
                    "cooldown_minutes": 0,
                    "project_mapping_state": "confirmed",
                    "project_mapping_confidence": 1.0,
                    "project_mapping_evidence": "unit test",
                }
            )
        )
        cls.conv = (
            cls.env["whatsapp.conversation"]
            .sudo()
            .create(
                {
                    "name": "Debounce Conv",
                    "remote_jid": cls.source.group_jid,
                    "conversation_type": "group",
                    "purpose": "other",
                }
            )
        )
        Msg = cls.env["whatsapp.message"].sudo()
        cls.msg = Msg.create(
            {
                "conversation_id": cls.conv.id,
                "group_jid": cls.source.group_jid,
                "direction": "in",
                "body": "Debounce test message",
                "sender_jid": "201000000010@s.whatsapp.net",
                "inbox_state": "new",
                "message_timestamp": "2026-07-26 08:00:00",
                "state": "received",
                "provider": "other",
                "provider_message_id": "manual:debounce-1",
                "dedupe_key": "debounce-test:1",
            }
        )

    def test_schedule_resets_pending_after(self):
        self.source.schedule_debounced_analysis()
        first = self.source.pending_analysis_after
        self.assertTrue(first)
        # Simulate later call — must reset forward
        self.source.write(
            {
                "pending_analysis_after": fields.Datetime.now()
                - timedelta(minutes=1)
            }
        )
        self.source.schedule_debounced_analysis()
        second = self.source.pending_analysis_after
        self.assertTrue(second)
        self.assertGreaterEqual(second, first)

    def test_fingerprint_duplicate_returns_existing(self):
        Analysis = self.env["dev.whatsapp.analysis"].with_user(self.manager)
        a1 = Analysis.action_enqueue_analysis(self.source.id, force=True)
        a2 = Analysis.action_enqueue_analysis(self.source.id, force=True)
        self.assertEqual(a1.id, a2.id)
        self.assertTrue(a1.batch_fingerprint)
        self.assertEqual(a1.batch_fingerprint, a2.batch_fingerprint)

    def test_cron_clears_pending_when_due(self):
        self.source.write(
            {
                "pending_analysis_after": fields.Datetime.now()
                - timedelta(minutes=1)
            }
        )
        flushed = self.env["dev.whatsapp.source"].cron_flush_debounced_analyses()
        self.assertGreaterEqual(flushed, 1)
        self.source.invalidate_recordset()
        self.assertFalse(self.source.pending_analysis_after)
