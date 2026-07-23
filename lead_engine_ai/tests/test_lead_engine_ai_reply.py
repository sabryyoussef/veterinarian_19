# -*- coding: utf-8 -*-
"""Tests for lead.engine.ai.reply and crm.lead AI counters (LLM mocked)."""

from unittest.mock import patch

from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestLeadEngineAIReplyModel(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Reply = cls.env["lead.engine.ai.reply"]
        cls.Lead = cls.env["crm.lead"]

    def _lead_with_message(self):
        lead = self.Lead.create({"name": "AI Test Lead", "partner_name": "Acme"})
        msg = lead.message_post(
            body="<p>Please send a quote</p>",
            message_type="comment",
            subtype_xmlid="mail.mt_comment",
        )
        return lead, msg

    def test_generate_draft_calls_llm_and_returns_html(self):
        lead, msg = self._lead_with_message()
        icp = self.env["ir.config_parameter"].sudo()
        icp.set_param("lead_engine_ai.llm_provider", "openai")
        icp.set_param("lead_engine_ai.llm_api_key", "sk-test")
        icp.set_param("lead_engine_ai.llm_model", "gpt-4o-mini")
        icp.set_param("lead_engine_ai.llm_endpoint", "https://api.openai.com/v1/chat/completions")

        with patch(
            "odoo.addons.lead_engine_ai.models.lead_engine_ai_reply.call_llm",
            return_value="Dear friend,\n\nThanks for your note.\n\nBest",
        ):
            draft, model_used, err = self.Reply._generate_draft(lead, msg)
        self.assertIsNone(err)
        self.assertIn("openai", model_used)
        self.assertTrue(draft)
        self.assertIn("<p>", draft)

    def test_generate_draft_no_key_returns_error(self):
        lead, msg = self._lead_with_message()
        icp = self.env["ir.config_parameter"].sudo()
        icp.set_param("lead_engine_ai.llm_provider", "openai")
        icp.set_param("lead_engine_ai.llm_api_key", "")
        icp.set_param("lead_engine_ai.llm_model", "gpt-4o-mini")

        draft, model_used, err = self.Reply._generate_draft(lead, msg)
        self.assertIsNone(draft)
        self.assertIsNotNone(err)
        self.assertIn("API key", err)

    def test_ai_reply_counts_on_lead(self):
        lead = self.Lead.create({"name": "Count Lead"})
        p1 = self.Reply.create(
            {
                "lead_id": lead.id,
                "subject": "S1",
                "state": "pending",
            }
        )
        self.Reply.create(
            {
                "lead_id": lead.id,
                "subject": "S2",
                "state": "sent",
            }
        )
        lead.invalidate_recordset()
        self.assertEqual(lead.ai_reply_count, 2)
        self.assertEqual(lead.ai_reply_pending_count, 1)
        p1.action_discard()
        lead.invalidate_recordset()
        self.assertEqual(lead.ai_reply_pending_count, 0)

    def test_action_review_and_send_opens_composer_action(self):
        lead = self.Lead.create({"name": "Act Lead"})
        reply = self.Reply.create(
            {
                "lead_id": lead.id,
                "subject": "Hello",
                "state": "pending",
            }
        )
        act = reply.action_review_and_send()
        self.assertEqual(act.get("res_model"), "mail.compose.message")
        self.assertEqual(act["context"].get("lead_engine_ai_reply_id"), reply.id)
