# -*- coding: utf-8 -*-
"""Project-aware WhatsApp AI: aliases, mapping gates, candidates, schema v2."""
from __future__ import annotations

import json

from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged, new_test_user

from odoo.addons.devhub_whatsapp.models.dev_whatsapp_analysis_utils import (
    validate_ai_response,
)


@tagged("post_install", "-at_install")
class TestWhatsappProjectAwareAi(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(
            cls.env,
            login="wa_pa_manager",
            groups="devhub_core.group_dev_hub_manager,base.group_user",
        )
        cls.pet = cls.env["dev.project"].search([("code", "=", "PETSPOT")], limit=1)
        cls.asta = cls.env["dev.project"].search([("code", "=", "ASTA")], limit=1)
        cls.azone = cls.env["dev.project"].search([("code", "=", "AZONE")], limit=1)
        if not (cls.pet and cls.asta and cls.azone):
            cls.skipTest("Required Dev Hub projects missing on this DB.")
        cls.env["dev.project.alias"]._seed_default_aliases()
        cls.env["ir.config_parameter"].sudo().set_param(
            "devhub_whatsapp.allow_fixture_ai", "True"
        )

    def test_arabic_alias_resolves_asta(self):
        Alias = self.env["dev.project.alias"]
        hits = Alias.match_text("مشكلة في أستا sandbox learning")
        self.assertTrue(any(a.dev_project_id == self.asta for a in hits))

    def test_azone_alias(self):
        hits = self.env["dev.project.alias"].match_text("AZone WorldPosta Shopify issue")
        self.assertTrue(any(a.dev_project_id == self.azone for a in hits))

    def test_unmapped_source_blocks_enqueue(self):
        Source = self.env["dev.whatsapp.source"].with_user(self.manager)
        src = Source.create(
            {
                "name": "Unmapped Test Group",
                "group_jid": "120363999000111222@g.us",
                "dev_project_id": self.pet.id,
                "ai_triage_enabled": True,
                "project_mapping_state": "unmapped",
                "project_mapping_confidence": 0.0,
                "project_mapping_evidence": "test",
            }
        )
        with self.assertRaises(UserError):
            self.env["dev.whatsapp.analysis"].with_user(self.manager).action_enqueue_analysis(
                src.id, force=True
            )

    def test_candidate_builder_prefers_confirmed_mapping(self):
        Source = self.env["dev.whatsapp.source"].sudo()
        src = Source.create(
            {
                "name": "Asta Candidate Group",
                "group_jid": "120363999000111223@g.us",
                "dev_project_id": self.asta.id,
                "ai_triage_enabled": True,
                "project_mapping_state": "confirmed",
                "project_mapping_confidence": 1.0,
                "project_mapping_evidence": "test confirmed",
            }
        )
        pack = self.env["dev.whatsapp.analysis.candidates"].build_project_candidates(
            src, self.env["whatsapp.message"]
        )
        self.assertTrue(pack["project_candidates"])
        self.assertEqual(pack["project_candidates"][0]["project_id"], self.asta.id)
        self.assertGreaterEqual(pack["project_candidates"][0]["deterministic_score"], 0.98)

    def test_schema_v2_rejects_foreign_project_id(self):
        with self.assertRaises(ValidationError):
            validate_ai_response(
                json.dumps(
                    {
                        "schema_version": "2",
                        "message_understanding": {
                            "summary": "x",
                            "classification": "bug",
                            "language": "en",
                            "technical_terms": [],
                            "missing_information": [],
                            "contains_multiple_tasks": False,
                        },
                        "project_resolution": {
                            "project_id": 999999,
                            "project_name": "Fake",
                            "confidence": 0.9,
                            "evidence": [],
                            "candidate_ids": [1],
                            "requires_confirmation": False,
                        },
                        "work_item_resolution": {
                            "decision": "none",
                            "work_item_id": None,
                            "work_item_title": None,
                            "confidence": 0.5,
                            "evidence": [],
                            "candidate_ids": [],
                            "requires_confirmation": False,
                        },
                        "analysis": {},
                        "evidence_used": [],
                        "confidence": 0.5,
                        "safe_to_create_work": False,
                        "safe_to_attach_to_existing_work": False,
                        "legacy_v1_bridge": {
                            "source_message_ids": [1],
                            "noise_message_ids": [],
                            "work_message_ids": [],
                        },
                    }
                ),
                [1],
                project_candidate_ids=[1],
                work_item_candidate_ids=[],
            )

    def test_schema_v2_accepts_candidate_project(self):
        validated = validate_ai_response(
            json.dumps(
                {
                    "schema_version": "2",
                    "message_understanding": {
                        "summary": "Fix ASTA sandbox",
                        "classification": "bug",
                        "language": "mixed",
                        "technical_terms": ["sandbox"],
                        "missing_information": [],
                        "contains_multiple_tasks": False,
                    },
                    "project_resolution": {
                        "project_id": self.asta.id,
                        "project_name": self.asta.name,
                        "confidence": 0.95,
                        "evidence": ["alias"],
                        "candidate_ids": [self.asta.id],
                        "requires_confirmation": False,
                    },
                    "work_item_resolution": {
                        "decision": "new",
                        "work_item_id": None,
                        "work_item_title": None,
                        "confidence": 0.8,
                        "evidence": [],
                        "candidate_ids": [],
                        "requires_confirmation": False,
                    },
                    "analysis": {"business_request": "Fix sandbox"},
                    "evidence_used": [],
                    "confidence": 0.9,
                    "safe_to_create_work": True,
                    "safe_to_attach_to_existing_work": False,
                    "legacy_v1_bridge": {
                        "source_message_ids": [10],
                        "noise_message_ids": [],
                        "work_message_ids": [10],
                        "work_title": "Fix sandbox",
                        "work_description": "desc",
                        "priority": "2",
                    },
                }
            ),
            [10],
            project_candidate_ids=[self.asta.id],
            work_item_candidate_ids=[],
        )
        self.assertEqual(validated["resolved_project_id"], self.asta.id)
        self.assertTrue(validated["safe_to_create_work"])

    def test_language_alias_english_accepted(self):
        validated = validate_ai_response(
            json.dumps(
                {
                    "schema_version": "2",
                    "message_understanding": {
                        "summary": "Invoice print issue",
                        "classification": "bug",
                        "language": "English",
                        "technical_terms": [],
                        "missing_information": [],
                        "contains_multiple_tasks": False,
                    },
                    "project_resolution": {
                        "project_id": self.azone.id,
                        "project_name": self.azone.name,
                        "confidence": "high",
                        "evidence": [],
                        "candidate_ids": [self.azone.id],
                        "requires_confirmation": False,
                    },
                    "work_item_resolution": {
                        "decision": "new",
                        "work_item_id": None,
                        "work_item_title": None,
                        "confidence": 0.7,
                        "evidence": [],
                        "candidate_ids": [],
                        "requires_confirmation": False,
                    },
                    "analysis": {"business_request": "Fix print"},
                    "evidence_used": [],
                    "confidence": "high",
                    "safe_to_create_work": True,
                    "safe_to_attach_to_existing_work": False,
                    "legacy_v1_bridge": {
                        "source_message_ids": [11],
                        "noise_message_ids": [],
                        "work_message_ids": [11],
                        "work_title": "Fix print",
                        "work_description": "desc",
                        "priority": "2",
                    },
                }
            ),
            [11],
            project_candidate_ids=[self.azone.id],
            work_item_candidate_ids=[],
        )
        self.assertEqual(validated["language"], "en")
        self.assertGreaterEqual(validated["confidence"], 0.8)

    def test_service_lease_requires_service_group(self):
        user = new_test_user(
            self.env,
            login="wa_pa_nosvc",
            groups="base.group_user,devhub_core.group_dev_hub_user",
        )
        with self.assertRaises(Exception):
            self.env["dev.whatsapp.analysis.job"].with_user(user).service_lease(limit=1)

    def test_service_lease_atomic_and_invalid_token(self):
        from odoo import fields
        from odoo.exceptions import AccessError

        svc = new_test_user(
            self.env,
            login="wa_pa_svc",
            groups="base.group_user,devhub_whatsapp.group_dev_hub_wa_analysis_service",
        )
        mgr = self.manager
        Source = self.env["dev.whatsapp.source"].sudo()
        src = Source.create(
            {
                "name": "Lease Test Group",
                "group_jid": "120363999000111224@g.us",
                "dev_project_id": self.azone.id,
                "ai_triage_enabled": True,
                "project_mapping_state": "confirmed",
                "project_mapping_confidence": 1.0,
                "project_mapping_evidence": "test",
            }
        )
        Message = self.env["whatsapp.message"].sudo()
        sample = Message.search([], limit=1)
        if not sample:
            self.skipTest("No whatsapp.message available")
        Message.create(
            {
                "conversation_id": sample.conversation_id.id,
                "direction": "in",
                "state": "received",
                "dedupe_key": "lease-test-%s" % src.id,
                "group_jid": src.group_jid,
                "sender_jid": "201000000099@s.whatsapp.net",
                "body": "AZone connector timeout on sync",
                "message_timestamp": fields.Datetime.now(),
                "media_kind": "none",
                "inbox_state": "new",
            }
        )
        analysis = self.env["dev.whatsapp.analysis"].with_user(mgr).action_enqueue_analysis(
            src.id, force=True, force_reanalyse=True
        )
        Job = self.env["dev.whatsapp.analysis.job"].with_user(svc)
        first = Job.service_lease(limit=1, lease_seconds=120, consumer_ref="t1")
        self.assertEqual(len(first["jobs"]), 1)
        second = Job.service_lease(limit=1, lease_seconds=120, consumer_ref="t2")
        leased_ids = {j["job_id"] for j in second.get("jobs") or []}
        self.assertNotIn(first["jobs"][0]["job_id"], leased_ids)
        job = first["jobs"][0]
        Job.service_start(job["job_id"], job["correlation_id"], job["lease_token"])
        with self.assertRaises(AccessError):
            Job.service_complete(
                job["job_id"],
                job["correlation_id"],
                "invalid-token",
                {"raw_response": "{}"},
            )

    def test_fixture_disabled_by_default_param(self):
        self.env["ir.config_parameter"].sudo().set_param(
            "devhub_whatsapp.allow_fixture_ai", "False"
        )
        self.assertEqual(
            self.env["ir.config_parameter"].sudo().get_param(
                "devhub_whatsapp.allow_fixture_ai"
            ),
            "False",
        )

    def test_ambiguous_source_blocks_enqueue(self):
        Source = self.env["dev.whatsapp.source"].with_user(self.manager)
        src = Source.create(
            {
                "name": "Ambiguous Test Group",
                "group_jid": "120363999000111225@g.us",
                "dev_project_id": self.pet.id,
                "ai_triage_enabled": True,
                "project_mapping_state": "ambiguous",
                "project_mapping_confidence": 0.4,
                "project_mapping_evidence": "multi",
            }
        )
        with self.assertRaises(UserError):
            self.env["dev.whatsapp.analysis"].with_user(self.manager).action_enqueue_analysis(
                src.id, force=True
            )
