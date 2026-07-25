# -*- coding: utf-8 -*-
"""Historical review allowlist: confirmed groups + Dev Needed multi-project."""
from __future__ import annotations

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestWhatsappHistoricalReviewScope(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Source = cls.env["dev.whatsapp.source"].sudo()
        Source._apply_p0_mapping_corrections()
        cls.dev_needed = Source.search(
            [("group_jid", "=", "120363422104853335@g.us")], limit=1
        )
        cls.alzaeem = Source.search(
            [("group_jid", "=", "120363409479957889@g.us")], limit=1
        )
        cls.asta = Source.search(
            [("group_jid", "=", "120363428056737368@g.us")], limit=1
        )
        if not (cls.dev_needed and cls.alzaeem and cls.asta):
            cls.skipTest("Required WhatsApp sources missing on this DB.")

    def test_dev_needed_multi_project_historical_allowed(self):
        self.assertEqual(self.dev_needed.project_mapping_state, "ambiguous")
        self.assertFalse(self.dev_needed.ai_triage_enabled)
        self.assertTrue(self.dev_needed.historical_review_enabled)
        self.assertEqual(self.dev_needed.historical_review_lane, "multi_project")
        self.assertTrue(self.dev_needed._historical_review_allowed())
        self.assertIsNone(self.dev_needed._historical_review_block_reason())
        # Live AI still blocked
        self.assertFalse(self.dev_needed._ai_mapping_allowed())

    def test_confirmed_single_historical_allowed(self):
        self.assertEqual(self.asta.project_mapping_state, "confirmed")
        self.assertTrue(self.asta.historical_review_enabled)
        self.assertEqual(self.asta.historical_review_lane, "confirmed_single")
        self.assertTrue(self.asta._historical_review_allowed())

    def test_alzaeem_excluded_from_historical_review(self):
        self.assertEqual(self.alzaeem.project_mapping_state, "unmapped")
        self.assertFalse(self.alzaeem.historical_review_enabled)
        self.assertEqual(self.alzaeem.historical_review_lane, "excluded")
        self.assertFalse(self.alzaeem._historical_review_allowed())
        self.assertTrue(self.alzaeem._historical_review_block_reason())

    def test_enqueue_historical_rejects_alzaeem(self):
        Analysis = self.env["dev.whatsapp.analysis"]
        manager = self.env.ref("base.user_admin")
        if not manager.has_group("devhub_core.group_dev_hub_manager"):
            self.env.ref("devhub_core.group_dev_hub_manager").sudo().write(
                {"users": [(4, manager.id)]}
            )
        Msg = self.env["whatsapp.message"].sudo().search(
            [("group_jid", "=", self.alzaeem.group_jid)], limit=1
        )
        if not Msg:
            self.skipTest("No Alzaeem hub messages")
        with self.assertRaises(UserError):
            Analysis.with_user(manager).action_enqueue_historical_quality_evaluation(
                self.alzaeem.id, Msg.ids, "ALZ-TEST"
            )

    def test_enqueue_historical_allows_dev_needed(self):
        Analysis = self.env["dev.whatsapp.analysis"]
        manager = self.env.ref("base.user_admin")
        if not manager.has_group("devhub_core.group_dev_hub_manager"):
            self.env.ref("devhub_core.group_dev_hub_manager").sudo().write(
                {"users": [(4, manager.id)]}
            )
        Msg = self.env["whatsapp.message"].sudo().search(
            [("group_jid", "=", self.dev_needed.group_jid)],
            order="message_timestamp desc",
            limit=2,
        )
        if len(Msg) < 1:
            self.skipTest("No Dev Needed hub messages")
        analysis = Analysis.with_user(manager).action_enqueue_historical_quality_evaluation(
            self.dev_needed.id, Msg.ids[:1], "DN-SCOPE-TEST", force_reanalyse=True
        )
        self.assertTrue(analysis.is_evaluation_result)
        self.assertEqual(analysis.historical_review_lane, "multi_project")
        self.assertEqual(self.dev_needed.project_mapping_state, "ambiguous")
        self.assertFalse(self.dev_needed.ai_triage_enabled)
