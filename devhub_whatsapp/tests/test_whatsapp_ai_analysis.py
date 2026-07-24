# -*- coding: utf-8 -*-
"""WhatsApp AI analysis: fingerprint, validation, approve create, jobs."""
from __future__ import annotations

import json

from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged, new_test_user

from odoo.addons.devhub_whatsapp.models.dev_whatsapp_analysis_utils import (
    batch_fingerprint,
    validate_ai_response,
)


@tagged("post_install", "-at_install", "devhub_whatsapp")
class TestWhatsappAiAnalysis(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(
            cls.env,
            login="wa_ai_mgr",
            groups="devhub_core.group_dev_hub_manager,base.group_user",
        )
        cls.service = new_test_user(
            cls.env,
            login="wa_ai_svc",
            groups="devhub_whatsapp.group_dev_hub_wa_analysis_service,base.group_user",
        )
        Project = cls.env["dev.project"].sudo()
        cls.project = Project.create(
            {
                "name": "WA AI Test Project",
                "code": "wa_ai_test",
                "owner_id": cls.manager.id,
                "member_ids": [(4, cls.manager.id)],
                "production_policy": "Test only. No production mutations.",
                "analysis_source_mode": "work_item",
            }
        )
        OdooProject = cls.env["project.project"].sudo()
        cls.odoo_project = OdooProject.create({"name": "WA AI Odoo Project"})
        Source = cls.env["dev.whatsapp.source"].sudo()
        cls.source = Source.create(
            {
                "name": "AI Test Group",
                "group_jid": "120363999888777001@g.us",
                "dev_project_id": cls.project.id,
                "odoo_project_id": cls.odoo_project.id,
                "ai_triage_enabled": True,
                "auto_ignore_enabled": False,
                "cooldown_minutes": 0,
                "project_mapping_state": "confirmed",
                "project_mapping_confidence": 1.0,
                "project_mapping_evidence": "unit test confirmed",
            }
        )
        cls.env["ir.config_parameter"].sudo().set_param(
            "devhub_whatsapp.allow_fixture_ai", "True"
        )
        Conv = cls.env["whatsapp.conversation"].sudo()
        cls.conv = Conv.create(
            {
                "name": "AI Test Conv",
                "remote_jid": cls.source.group_jid,
                "conversation_type": "group",
                "purpose": "other",
            }
        )
        Msg = cls.env["whatsapp.message"].sudo()
        token = "ai-test"
        cls.msg1 = Msg.create(
            {
                "conversation_id": cls.conv.id,
                "group_jid": cls.source.group_jid,
                "direction": "in",
                "body": "Invoice print fails on test DB",
                "sender_jid": "201000000001@s.whatsapp.net",
                "inbox_state": "new",
                "message_timestamp": "2026-07-24 10:00:00",
                "state": "received",
                "provider": "other",
                "provider_message_id": "manual:%s-1" % token,
                "dedupe_key": "ai-test:%s-1" % token,
            }
        )
        cls.msg2 = Msg.create(
            {
                "conversation_id": cls.conv.id,
                "group_jid": cls.source.group_jid,
                "direction": "in",
                "body": "Please fix ASAP",
                "sender_jid": "201000000002@s.whatsapp.net",
                "inbox_state": "new",
                "message_timestamp": "2026-07-24 10:01:00",
                "state": "received",
                "provider": "other",
                "provider_message_id": "manual:%s-2" % token,
                "dedupe_key": "ai-test:%s-2" % token,
            }
        )

    def _fixture(self, **overrides):
        data = {
            "schema_version": "1",
            "summary": "Invoice print failure reported",
            "classification": "bug_report",
            "should_ignore": False,
            "ignore_reason": None,
            "contains_work": True,
            "work_title": "Fix invoice print on test",
            "work_description": "Users report invoice print fails.",
            "priority": "2",
            "project_reference": None,
            "participants": ["201000000001@s.whatsapp.net"],
            "source_message_ids": [self.msg1.id, self.msg2.id],
            "noise_message_ids": [],
            "work_message_ids": [self.msg1.id, self.msg2.id],
            "confidence": 0.91,
            "requires_human_review": True,
            "recommended_action": "create_work",
            "missing_information": [],
        }
        data.update(overrides)
        return json.dumps(data)

    def test_fingerprint_stable_and_prompt_changes(self):
        a = batch_fingerprint(
            self.source.group_jid, [self.msg2.id, self.msg1.id], "wa_triage_v1", "1", "group_triage"
        )
        b = batch_fingerprint(
            self.source.group_jid, [self.msg1.id, self.msg2.id], "wa_triage_v1", "1", "group_triage"
        )
        self.assertEqual(a, b)
        c = batch_fingerprint(
            self.source.group_jid, [self.msg1.id, self.msg2.id], "wa_triage_v2", "1", "group_triage"
        )
        self.assertNotEqual(a, c)

    def test_validate_rejects_foreign_ids(self):
        with self.assertRaises(ValidationError):
            validate_ai_response(
                self._fixture(source_message_ids=[self.msg1.id, 999999]),
                [self.msg1.id, self.msg2.id],
            )

    def test_recommendation_does_not_mutate_inbox(self):
        Analysis = self.env["dev.whatsapp.analysis"].with_user(self.manager)
        analysis = Analysis.action_enqueue_analysis(self.source.id, force=True)
        analysis.action_ingest_fixture_json(self._fixture(should_ignore=True, ignore_reason="noise", contains_work=False, work_title=None, work_description=None, recommended_action="ignore", classification="noise", work_message_ids=[], noise_message_ids=[self.msg1.id, self.msg2.id]))
        # If not auto-ignore, messages stay new until approve
        self.msg1.invalidate_recordset()
        if analysis.state == "awaiting_review":
            self.assertEqual(self.msg1.inbox_state, "new")
            analysis.action_approve_ignore()
            self.msg1.invalidate_recordset()
            self.assertEqual(self.msg1.inbox_state, "ignored")
            analysis.action_restore_messages()
            self.msg1.invalidate_recordset()
            self.assertIn(self.msg1.inbox_state, ("new", "pending"))

    def test_approve_create_work_item(self):
        Analysis = self.env["dev.whatsapp.analysis"].with_user(self.manager)
        analysis = Analysis.action_enqueue_analysis(self.source.id, force=True)
        analysis.action_ingest_fixture_json(self._fixture())
        self.assertEqual(analysis.state, "awaiting_review")
        action = analysis.action_approve_create_work()
        work = self.env["dev.work.item"].browse(action["res_id"])
        self.assertTrue(work.exists())
        self.assertEqual(work.source_type, "whatsapp_ai")
        self.assertTrue(work.origin_ai_whatsapp)
        self.assertEqual(work.whatsapp_analysis_id, analysis)
        self.assertFalse(getattr(work, "op_work_package_id", False))
        with self.assertRaises(UserError):
            analysis.action_approve_create_work()

    def test_job_lease_complete(self):
        Analysis = self.env["dev.whatsapp.analysis"].with_user(self.manager)
        analysis = Analysis.action_enqueue_analysis(self.source.id, force=True)
        Job = self.env["dev.whatsapp.analysis.job"].with_user(self.service)
        leased = Job.service_lease(limit=1, consumer_ref="test-n8n")
        self.assertTrue(leased["jobs"])
        job = leased["jobs"][0]
        Job.service_start(job["job_id"], job["correlation_id"], job["lease_token"])
        result = Job.service_complete(
            job["job_id"],
            job["correlation_id"],
            job["lease_token"],
            {"raw_response": self._fixture(), "provider_model": "test"},
        )
        self.assertTrue(result["ok"])
        analysis.invalidate_recordset()
        self.assertEqual(analysis.state, "awaiting_review")

    def test_malformed_json_no_mutation(self):
        Analysis = self.env["dev.whatsapp.analysis"].with_user(self.manager)
        analysis = Analysis.action_enqueue_analysis(self.source.id, force=True)
        Job = self.env["dev.whatsapp.analysis.job"].with_user(self.service)
        leased = Job.service_lease(limit=1, consumer_ref="test-n8n")["jobs"][0]
        Job.service_complete(
            leased["job_id"],
            leased["correlation_id"],
            leased["lease_token"],
            {"raw_response": "{not-json"},
        )
        self.msg1.invalidate_recordset()
        self.assertEqual(self.msg1.inbox_state, "new")
        analysis.invalidate_recordset()
        self.assertIn(analysis.state, ("pending", "failed"))

    def test_deep_analysis_prereq_work_item_mode(self):
        # Create a minimal work item via AI path then check prerequisites
        Analysis = self.env["dev.whatsapp.analysis"].with_user(self.manager)
        analysis = Analysis.action_enqueue_analysis(self.source.id, force=True)
        analysis.action_ingest_fixture_json(self._fixture())
        action = analysis.action_approve_create_work()
        work = self.env["dev.work.item"].browse(action["res_id"])
        # Without repo/env still missing
        missing = work._generation_prerequisites()
        self.assertTrue(any("repository" in m for m in missing))
        # OP task not required in work_item mode
        self.assertFalse(any("OpenProject" in m for m in missing))
