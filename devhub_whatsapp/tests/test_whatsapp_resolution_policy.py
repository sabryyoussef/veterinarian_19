# -*- coding: utf-8 -*-
"""Tests for unique-candidate commitment, WI boost, taxonomy, segmentation."""
from __future__ import annotations

from datetime import timedelta

from odoo import fields
from odoo.tests import TransactionCase, tagged

from odoo.addons.devhub_whatsapp.models.dev_whatsapp_analysis_utils import (
    normalize_classification_v2,
)


@tagged("post_install", "-at_install")
class TestWhatsappResolutionPolicy(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.asta = cls.env["dev.project"].search([("code", "=", "ASTA")], limit=1)
        cls.kafaat = cls.env["dev.project"].search([("code", "=", "KAFAAT")], limit=1)
        cls.pet = cls.env["dev.project"].search([("code", "=", "PETSPOT")], limit=1)
        if not (cls.asta and cls.pet):
            cls.skipTest("Required Dev Hub projects missing on this DB.")
        cls.env["dev.project.alias"]._seed_default_aliases()
        cls.Candidates = cls.env["dev.whatsapp.analysis.candidates"]
        cls.Segment = cls.env["dev.whatsapp.analysis.segment"]
        Source = cls.env["dev.whatsapp.source"].sudo()
        cls.ambiguous = Source.create(
            {
                "name": "Policy Ambiguous Group",
                "group_jid": "120363999000222001@g.us",
                "dev_project_id": cls.pet.id,
                "ai_triage_enabled": False,
                "project_mapping_state": "ambiguous",
                "project_mapping_confidence": 0.35,
                "project_mapping_evidence": "multi-project test",
            }
        )
        Message = cls.env["whatsapp.message"].sudo()
        sample = Message.search([], limit=1)
        if not sample:
            cls.skipTest("No whatsapp.message available")
        cls._conv = sample.conversation_id
        cls.Message = Message

    def _msg(self, body, minutes_ago=0, dedupe=None):
        return self.Message.create(
            {
                "conversation_id": self._conv.id,
                "direction": "in",
                "state": "received",
                "dedupe_key": dedupe or ("pol-%s" % fields.Datetime.now().timestamp()),
                "group_jid": self.ambiguous.group_jid,
                "sender_jid": "201000000001@s.whatsapp.net",
                "body": body,
                "message_timestamp": fields.Datetime.now()
                - timedelta(minutes=minutes_ago),
                "media_kind": "none",
                "inbox_state": "new",
            }
        )

    def test_ambiguous_one_strong_candidate_proposed(self):
        msg = self._msg("مشكلة في استا / ASTA vacation balance", dedupe="pol-asta-1")
        pack = self.Candidates.build_project_candidates(self.ambiguous, msg)
        policy = pack["selection_policy"]
        self.assertTrue(pack["requires_project_confirmation"])
        self.assertTrue(policy["eligible_for_proposed_selection"])
        self.assertEqual(policy["proposed_project_id"], self.asta.id)
        self.assertTrue(
            any(c.get("eligible_for_proposed_selection") for c in pack["project_candidates"])
        )

    def test_ambiguous_weak_only_not_proposed(self):
        # No alias — only demoted petspot mapping signal
        msg = self._msg("ok thanks", dedupe="pol-weak-1")
        pack = self.Candidates.build_project_candidates(self.ambiguous, msg)
        policy = pack["selection_policy"]
        self.assertFalse(policy["eligible_for_proposed_selection"])
        self.assertIsNone(policy["proposed_project_id"])

    def test_two_close_candidates_null(self):
        if not self.kafaat:
            self.skipTest("KAFAAT missing")
        msg = self._msg("ASTA and KAFAAT both mentioned in one line", dedupe="pol-two-1")
        pack = self.Candidates.build_project_candidates(self.ambiguous, msg)
        # If both match with similar scores, should not propose
        cands = pack["project_candidates"]
        if len(cands) >= 2:
            policy = pack["selection_policy"]
            scores = [c["deterministic_score"] for c in cands[:2]]
            if scores[0] - scores[1] < 0.20:
                self.assertFalse(policy["eligible_for_proposed_selection"])

    def test_no_candidate_null(self):
        msg = self._msg("👍", dedupe="pol-empty-1")
        pack = self.Candidates.build_project_candidates(self.ambiguous, msg)
        self.assertFalse(pack["selection_policy"]["eligible_for_proposed_selection"])

    def test_taxonomy_normalization(self):
        self.assertEqual(normalize_classification_v2("feature"), "new_task")
        self.assertEqual(normalize_classification_v2("bug_report"), "bug")
        self.assertEqual(normalize_classification_v2("follow_up"), "existing_work_followup")
        self.assertEqual(normalize_classification_v2("context"), "context_update")
        self.assertEqual(normalize_classification_v2("info"), "unclear")
        self.assertEqual(normalize_classification_v2("new_task"), "new_task")

    def test_alias_switch_creates_boundary(self):
        if not self.kafaat:
            self.skipTest("KAFAAT missing")
        m1 = self._msg("ASTA issue on leave", minutes_ago=10, dedupe="pol-seg-1")
        m2 = self._msg("KAFAAT payroll report broken", minutes_ago=5, dedupe="pol-seg-2")
        segs = self.Segment.segment_messages(m1 | m2, max_per_segment=12, gap_minutes=45)
        self.assertGreaterEqual(len(segs), 2)

    def test_same_project_alias_does_not_oversplit(self):
        m1 = self._msg("ASTA leave module", minutes_ago=10, dedupe="pol-seg-3")
        m2 = self._msg("ASTA also needs print fix", minutes_ago=5, dedupe="pol-seg-4")
        segs = self.Segment.segment_messages(m1 | m2, max_per_segment=12, gap_minutes=45)
        self.assertEqual(len(segs), 1)

    def test_direct_wi_link_boosts_existing(self):
        Work = self.env["dev.work.item"].sudo()
        work = Work.search([("dev_project_id", "=", self.pet.id)], limit=1)
        if not work:
            self.skipTest("No PETSPOT work item")
        msg = self._msg("follow up on this ticket", dedupe="pol-wi-1")
        source_msgs = msg._dh_ensure_source_messages()
        source_msgs.write({"work_item_ids": [(4, work.id)]})
        msg.invalidate_recordset()
        pack = self.Candidates.build_work_item_candidates(self.pet, msg)
        self.assertTrue(pack["work_item_candidates"])
        self.assertTrue(pack["work_item_candidates"][0].get("direct_message_link"))
        self.assertEqual(pack["recommended_work_item_decision"], "existing")
        self.assertEqual(pack["recommended_work_item_id"], work.id)

    def test_foreign_wi_rejected_for_other_project(self):
        Work = self.env["dev.work.item"].sudo()
        work = Work.search([("dev_project_id", "=", self.pet.id)], limit=1)
        if not work or not self.asta:
            self.skipTest("Need PETSPOT WI and ASTA")
        msg = self._msg("ASTA unrelated", dedupe="pol-wi-2")
        # Non-linked recent PETSPOT WI must not appear under ASTA project filter
        pack = self.Candidates.build_work_item_candidates(self.asta, msg)
        ids = [c["work_item_id"] for c in pack["work_item_candidates"]]
        self.assertNotIn(work.id, ids)
        # Direct-linked foreign WI is included (authoritative) for later policy align
        source_msgs = msg._dh_ensure_source_messages()
        source_msgs.write({"work_item_ids": [(4, work.id)]})
        msg.invalidate_recordset()
        pack2 = self.Candidates.build_work_item_candidates(self.asta, msg)
        linked = [c for c in pack2["work_item_candidates"] if c["work_item_id"] == work.id]
        self.assertTrue(linked)
        self.assertTrue(linked[0].get("direct_message_link"))
