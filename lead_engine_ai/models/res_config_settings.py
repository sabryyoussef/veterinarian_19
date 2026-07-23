# -*- coding: utf-8 -*-
"""
lead.engine.ai.settings
========================
Dedicated settings model for Lead Engine AI.
Reads / writes to ir.config_parameter so values survive upgrades.

Accessed via: Lead Engine AI → Settings
"""
import requests as _requests

from odoo import api, fields, models
from odoo.exceptions import UserError

# Provider choices (used in both primary + secondary selections)
_PROVIDER_SELECTION = [
    ("openai",      "OpenAI  (GPT-4o, GPT-4.1, o3-mini …)"),
    ("anthropic",   "Anthropic  (Claude 3.5 Sonnet, Claude 3 Haiku …)"),
    ("gemini",      "Google Gemini  (1.5 Flash, 2.0 Flash, Pro …)"),
    ("deepseek",    "DeepSeek  (deepseek-chat, deepseek-coder …)"),
    ("groq",        "Groq  (llama3-70b, mixtral-8x7b — very fast, free tier)"),
    ("mistral",     "Mistral AI  (mistral-large, mistral-small …)"),
    ("openrouter",  "OpenRouter  (aggregator: GPT-4, Claude, Llama, …)"),
    ("ollama",      "Ollama  (local — no API key needed)"),
    ("custom",      "Custom / Self-hosted  (any OpenAI-compatible endpoint)"),
]

_PROVIDER_SELECTION_SECONDARY = [("", "— none / disabled —")] + _PROVIDER_SELECTION

# Hint text shown next to the model name field, per provider
_MODEL_HINTS = {
    "openai": (
        "gpt-4o-mini  (fast, cheap)\n"
        "gpt-4o  (best quality)\n"
        "gpt-4.1, gpt-4.1-mini  (latest 2025)\n"
        "gpt-3.5-turbo  (legacy, very cheap)"
    ),
    "anthropic": (
        "claude-3-5-sonnet-20241022  (best)\n"
        "claude-3-5-haiku-20241022  (fast)\n"
        "claude-3-opus-20240229  (most powerful)\n"
        "claude-3-haiku-20240307  (cheapest)"
    ),
    "gemini": (
        "gemini-2.0-flash-exp  (latest, fast)\n"
        "gemini-1.5-flash  (free tier available)\n"
        "gemini-1.5-pro  (best quality)\n"
        "gemini-2.5-pro-preview-03-25  (cutting-edge)"
    ),
    "deepseek": (
        "deepseek-chat  (general purpose, very cheap)\n"
        "deepseek-coder  (code focused)"
    ),
    "groq": (
        "llama3-70b-8192  (Llama 3, fast free tier)\n"
        "llama3-8b-8192  (smaller, even faster)\n"
        "mixtral-8x7b-32768  (Mistral mixture)\n"
        "gemma2-9b-it  (Google Gemma)"
    ),
    "mistral": (
        "mistral-large-latest  (best)\n"
        "mistral-small-latest  (cheap)\n"
        "open-mistral-7b  (free tier)"
    ),
    "openrouter": (
        "openai/gpt-4o\n"
        "anthropic/claude-3.5-sonnet\n"
        "meta-llama/llama-3-70b-instruct\n"
        "google/gemini-flash-1.5"
    ),
    "ollama": (
        "llama3  (Meta Llama 3)\n"
        "mistral  (Mistral 7B)\n"
        "gemma2  (Google Gemma 2)\n"
        "phi3  (Microsoft Phi-3)\n"
        "deepseek-coder-v2  (DeepSeek)\n"
        "Run: ollama pull <model> first"
    ),
    "custom": "Enter the model name expected by your endpoint.",
}


class LeadEngineAISettings(models.TransientModel):
    _name = "lead.engine.ai.settings"
    _description = "Lead Engine AI Settings"

    # ── Primary LLM ──────────────────────────────────────────────
    llm_provider = fields.Selection(
        selection=_PROVIDER_SELECTION,
        string="Primary provider",
        default="openai",
        required=True,
    )
    llm_model = fields.Char(
        string="Model name",
        default="gpt-4o-mini",
        required=True,
    )
    llm_api_key = fields.Char(
        string="API Key",
        help="Leave empty for Ollama (no key needed for local models).",
    )
    llm_endpoint = fields.Char(
        string="Endpoint URL",
        help=(
            "Required for Ollama and Custom.\n"
            "Ollama default: http://localhost:11434/v1/chat/completions\n"
            "Leave empty for cloud providers (OpenAI, Anthropic, etc.) "
            "to use their standard URL."
        ),
    )

    # Helper computed field so the view can show provider-specific model hints
    llm_model_hint = fields.Char(
        compute="_compute_model_hints",
        string="Model hint",
    )

    # ── Secondary LLM (fallback) ──────────────────────────────────
    llm_provider_2 = fields.Selection(
        selection=_PROVIDER_SELECTION_SECONDARY,
        string="Secondary provider (fallback)",
        default="",
    )
    llm_model_2 = fields.Char(string="Secondary model")
    llm_api_key_2 = fields.Char(
        string="Secondary API Key",
        help="Leave empty for Ollama.",
    )
    llm_endpoint_2 = fields.Char(
        string="Secondary endpoint URL",
        help="Required for Ollama/Custom secondary provider.",
    )
    llm_model_hint_2 = fields.Char(
        compute="_compute_model_hints",
        string="Secondary model hint",
    )

    # ── Monitored addresses ───────────────────────────────────────
    monitored_emails = fields.Char(
        string="Monitored email addresses",
        help=(
            "Comma-separated. AI drafts only for emails received at these addresses.\n"
            "Leave empty to trigger for every inbound email on any CRM lead.\n"
            "Example: vendorah2@gmail.com, abhorya@gmail.com"
        ),
    )

    # ── System prompt ─────────────────────────────────────────────
    system_prompt = fields.Text(
        string="System prompt override",
        help=(
            "Custom instructions for the AI. Leave empty for the built-in prompt.\n"
            "Built-in: match email language, sign with salesperson name, "
            "professional tone, no invented facts."
        ),
    )

    # ── Computed hints ────────────────────────────────────────────
    @api.depends("llm_provider", "llm_provider_2")
    def _compute_model_hints(self):
        for rec in self:
            rec.llm_model_hint = _MODEL_HINTS.get(rec.llm_provider, "")
            rec.llm_model_hint_2 = _MODEL_HINTS.get(rec.llm_provider_2 or "", "")

    # ── Load / Save ───────────────────────────────────────────────
    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        icp = self.env["ir.config_parameter"].sudo()
        res.update({
            "llm_provider":   icp.get_param("lead_engine_ai.llm_provider", "openai"),
            "llm_model":      icp.get_param("lead_engine_ai.llm_model", "gpt-4o-mini"),
            "llm_api_key":    icp.get_param("lead_engine_ai.llm_api_key", ""),
            "llm_endpoint":   icp.get_param("lead_engine_ai.llm_endpoint", ""),
            "llm_provider_2": icp.get_param("lead_engine_ai.llm_provider_2", ""),
            "llm_model_2":    icp.get_param("lead_engine_ai.llm_model_2", ""),
            "llm_api_key_2":  icp.get_param("lead_engine_ai.llm_api_key_2", ""),
            "llm_endpoint_2": icp.get_param("lead_engine_ai.llm_endpoint_2", ""),
            "monitored_emails": icp.get_param(
                "lead_engine_ai.monitored_emails",
                "vendorah2@gmail.com, abhorya@gmail.com",
            ),
            "system_prompt":  icp.get_param("lead_engine_ai.system_prompt", ""),
        })
        return res

    def action_save(self):
        self.ensure_one()
        icp = self.env["ir.config_parameter"].sudo()
        icp.set_param("lead_engine_ai.llm_provider",   self.llm_provider or "openai")
        icp.set_param("lead_engine_ai.llm_model",      self.llm_model or "gpt-4o-mini")
        icp.set_param("lead_engine_ai.llm_api_key",    self.llm_api_key or "")
        icp.set_param("lead_engine_ai.llm_endpoint",   self.llm_endpoint or "")
        icp.set_param("lead_engine_ai.llm_provider_2", self.llm_provider_2 or "")
        icp.set_param("lead_engine_ai.llm_model_2",    self.llm_model_2 or "")
        icp.set_param("lead_engine_ai.llm_api_key_2",  self.llm_api_key_2 or "")
        icp.set_param("lead_engine_ai.llm_endpoint_2", self.llm_endpoint_2 or "")
        icp.set_param("lead_engine_ai.monitored_emails", self.monitored_emails or "")
        icp.set_param("lead_engine_ai.system_prompt",  self.system_prompt or "")
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Settings saved",
                "message": "Lead Engine AI settings saved successfully.",
                "type": "success",
                "sticky": False,
            },
        }

    def action_test_connection(self):
        """Send a test ping to the primary LLM and show the result."""
        self.ensure_one()
        from odoo.addons.lead_engine_ai.models.lead_engine_ai_reply import call_llm

        provider = self.llm_provider
        api_key  = self.llm_api_key or ""
        model    = self.llm_model
        endpoint = self.llm_endpoint or ""

        if not api_key and provider != "ollama":
            raise UserError(
                "Please enter an API Key and click Save Settings before testing.\n"
                "(Ollama does not need an API key.)"
            )
        if provider in ("ollama", "custom") and not endpoint:
            raise UserError(
                f"'{provider}' requires an Endpoint URL.\n"
                "Example for Ollama: http://localhost:11434/v1/chat/completions"
            )

        try:
            result = call_llm(
                provider, api_key, model,
                "You are a helpful assistant.",
                "Reply with exactly one sentence: 'Lead Engine AI connection OK'",
                endpoint,
            )
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": "Connection test passed",
                    "message": f"{provider}/{model} replied: {result[:200]}",
                    "type": "success",
                    "sticky": True,
                },
            }

        except _requests.exceptions.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else 0

            if status == 429:
                return {
                    "type": "ir.actions.client",
                    "tag": "display_notification",
                    "params": {
                        "title": "API key is valid (rate limited)",
                        "message": (
                            f"Got HTTP 429 from {provider} — your API key works but hit a rate limit. "
                            "This is normal on free-tier accounts. The key is configured correctly."
                        ),
                        "type": "warning",
                        "sticky": True,
                    },
                }
            if status in (401, 403):
                raise UserError(
                    f"Authentication failed (HTTP {status}) for {provider}.\n"
                    "Your API key is invalid or has been revoked. Please check and try again."
                ) from exc

            body = ""
            try:
                body = exc.response.text[:400]
            except Exception:
                pass
            raise UserError(f"HTTP {status} from {provider}:\n{body}") from exc

        except _requests.exceptions.ConnectionError as exc:
            raise UserError(
                f"Cannot reach {provider} endpoint.\n"
                "Check your internet connection or Ollama is running.\n"
                f"Detail: {exc}"
            ) from exc

        except _requests.exceptions.Timeout:
            raise UserError(
                f"{provider} request timed out (>60 s). "
                "The service may be overloaded — try again in a moment."
            ) from None

        except Exception as exc:
            raise UserError(f"Test failed for {provider}/{model}:\n{exc}") from exc
