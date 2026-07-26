# -*- coding: utf-8 -*-
"""Work orchestration blocks create when source messages already link a WI."""
from __future__ import annotations

import json

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged, new_test_user


@tagged("post_install", "-at_install", "devhub_whatsapp")
class TestWhatsappWorkOrchestration(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(
            cls.env,
            login="wa_orch_mgr",
            groups="devhub_core.group_dev_hub_manager,base.group_user",
        )
        Project = cls.env["dev.project"].sudo()
        cls.project = Project.create(
            {
                "name": "WA Orch Project",
                "code": "wa_orch",
                "owner_id": cls.manager.id,
                "member_ids": [(4, cls.manager.id)],
                "production_policy": "Test only.",
                "analysis_source_mode": "work_item",
            }
        )
        cls.odoo_project = cls.env["project.project"].sudo().create(
            {"name": "WA Orch Odoo"}
        )
        cls.source = (
            cls.env["dev.whatsapp.source"]
            .sudo()
            .create(
                {
                    "name": "Orch Group",
                    "group_jid": "120363999888777020@g.us",
                    "dev_project_id": cls.project.id,
                    "odoo_project_id": cls.odoo_project.id,
                    "ai_triage_enabled": True,
                    "analysis_review_only": True,
                    "openproject_create_allowed": False,
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
                    "name": "Orch Conv",
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
                "body": "Duplicate orchestration test",
                "sender_jid": "201000000020@s.whatsapp.net",
                "inbox_state": "new",
                "message_timestamp": "2026-07-26 09:00:00",
                "state": "received",
                "provider": "other",
                "provider_message_id": "manual:orch-1",
                "dedupe_key": "orch-test:1",
            }
        )
        cls.env["ir.config_parameter"].sudo().set_param(
            "devhub_whatsapp.allow_fixture_ai", "True"
        )

    def test_duplicate_message_link_blocks_create(self):
        Analysis = self.env["dev.whatsapp.analysis"].with_user(self.manager)
        analysis = Analysis.action_enqueue_analysis(self.source.id, force=True)
        fixture = {
            "schema_version": "1",
            "summary": "Duplicate link case",
            "classification": "bug_report",
            "should_ignore": False,
            "ignore_reason": None,
            "contains_work": True,
            "work_title": "Existing linked work",
            "work_description": "Should not create again.",
            "priority": "2",
            "project_reference": None,
            "participants": [],
            "source_message_ids": [self.msg.id],
            "noise_message_ids": [],
            "work_message_ids": [self.msg.id],
            "confidence": 0.9,
            "requires_human_review": True,
            "recommended_action": "create_work",
            "missing_information": [],
        }
        analysis.action_ingest_fixture_json(json.dumps(fixture))

        # Link message to an existing Work Item first
        source_msgs = self.msg._dh_ensure_source_messages()
        work = (
            self.env["dev.work.item"]
            .with_user(self.manager)
            .create(
                {
                    "name": "Pre-existing WA work",
                    "dev_project_id": self.project.id,
                    "odoo_project_id": self.odoo_project.id,
                    "responsible_user_id": self.manager.id,
                    "source_message_ids": [(6, 0, source_msgs.ids)],
                    "source_type": "whatsapp_ai",
                }
            )
        )
        self.assertTrue(work)
        self.msg.invalidate_recordset()

        Orch = self.env["dev.whatsapp.work.orchestration"]
        decision = Orch.evaluate_before_create(analysis)
        self.assertEqual(decision["decision"], "update_existing")
        self.assertTrue(decision["dev_work_item_matches"])

        with self.assertRaises(UserError):
            analysis.action_approve_create_work()

        # Manager force context may proceed past orchestration assert,
        # but the linked-message guard still blocks create.
        with self.assertRaises(UserError):
            analysis.with_context(wa_orchestration_force=True).action_approve_create_work()
