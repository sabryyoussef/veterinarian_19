# -*- coding: utf-8 -*-
"""Unit tests for LLM dispatch helpers (HTTP mocked — no live API calls)."""

from unittest.mock import MagicMock, patch

from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestLeadEngineAILlmDispatch(TransactionCase):
    """Exercise call_llm() routing and response parsing with mocked requests.post."""

    def test_call_llm_openai_compatible_parses_message(self):
        from odoo.addons.lead_engine_ai.models import lead_engine_ai_reply as ler

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "  Draft line  "}}],
        }
        mock_resp.raise_for_status = MagicMock()
        with patch.object(ler.requests, "post", return_value=mock_resp) as post:
            out = ler.call_llm(
                "openai",
                "sk-x",
                "gpt-4o-mini",
                "sys",
                "user",
                endpoint="https://api.openai.com/v1/chat/completions",
            )
        self.assertEqual(out, "Draft line")
        post.assert_called_once()

    def test_call_llm_anthropic_parses_content(self):
        from odoo.addons.lead_engine_ai.models import lead_engine_ai_reply as ler

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"content": [{"text": "Claude says hi"}]}
        mock_resp.raise_for_status = MagicMock()
        with patch.object(ler.requests, "post", return_value=mock_resp):
            out = ler.call_llm(
                "anthropic",
                "ak",
                "claude-3-haiku",
                "sys",
                "user",
            )
        self.assertEqual(out, "Claude says hi")

    def test_call_llm_gemini_parses_candidate(self):
        from odoo.addons.lead_engine_ai.models import lead_engine_ai_reply as ler

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": "Gemini ok"}]}}],
        }
        mock_resp.raise_for_status = MagicMock()
        with patch.object(ler.requests, "post", return_value=mock_resp):
            out = ler.call_llm(
                "gemini",
                "gk",
                "gemini-1.5-flash",
                "sys",
                "user",
            )
        self.assertEqual(out, "Gemini ok")

    def test_call_llm_unknown_provider_raises(self):
        from odoo.addons.lead_engine_ai.models import lead_engine_ai_reply as ler

        with self.assertRaises(ValueError):
            ler.call_llm("not_a_provider", "k", "m", "s", "u")
