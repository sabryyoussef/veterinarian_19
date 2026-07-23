# -*- coding: utf-8 -*-
"""
lead.engine.ai.reply
====================
Stores a pending AI-drafted reply awaiting human approval.

One record is created per inbound email that triggered the AI.
States: pending -> sent | discarded
"""
import logging
import json

import requests

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools import html2plaintext

_logger = logging.getLogger(__name__)

# ── Default provider endpoints ──────────────────────────────────────────────
_DEFAULT_ENDPOINTS = {
    "openai":     "https://api.openai.com/v1/chat/completions",
    "anthropic":  "https://api.anthropic.com/v1/messages",
    "gemini":     "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
    "deepseek":   "https://api.deepseek.com/v1/chat/completions",
    "groq":       "https://api.groq.com/openai/v1/chat/completions",
    "mistral":    "https://api.mistral.ai/v1/chat/completions",
    "openrouter": "https://openrouter.ai/api/v1/chat/completions",
    "ollama":     "http://localhost:11434/v1/chat/completions",
}

_DEFAULT_SYSTEM_PROMPT = """\
You are a professional business communication assistant for a sales team.
Your task: draft a reply email to an incoming message on a sales lead.

Rules:
- Be professional, warm and concise (3-6 sentences max unless context demands more)
- Match the language of the incoming email exactly (Arabic reply for Arabic, English for English)
- Reference the specific topic from the incoming message
- Sign off with the salesperson name provided
- Never invent facts about products, pricing or timelines not mentioned in the context
- Output PLAIN TEXT only - no HTML tags, no markdown, no bullet points
- Start directly with the greeting (e.g. "Dear Ahmed," or "Hello,")
"""


def _call_openai_compatible(
    endpoint: str, api_key: str, model: str,
    system_prompt: str, user_prompt: str,
    extra_headers: dict | None = None,
) -> str:
    """
    Call any OpenAI-compatible Chat Completions endpoint.
    Used for: OpenAI, DeepSeek, Groq, Mistral, OpenRouter, Ollama.
    Pass api_key='' for Ollama (no auth needed).
    """
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    if extra_headers:
        headers.update(extra_headers)

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.5,
        "max_tokens": 800,
    }
    resp = requests.post(endpoint, json=payload, headers=headers, timeout=60)
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def _call_anthropic(
    api_key: str, model: str, system_prompt: str, user_prompt: str
) -> str:
    """Call Anthropic Messages API (claude-* models)."""
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": model,
        "max_tokens": 800,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_prompt}],
    }
    resp = requests.post(
        _DEFAULT_ENDPOINTS["anthropic"], json=payload, headers=headers, timeout=60
    )
    resp.raise_for_status()
    return resp.json()["content"][0]["text"].strip()


def _call_gemini(
    api_key: str, model: str, system_prompt: str, user_prompt: str
) -> str:
    """Call Google Gemini generateContent API."""
    url = _DEFAULT_ENDPOINTS["gemini"].format(model=model) + f"?key={api_key}"
    payload = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": {"temperature": 0.5, "maxOutputTokens": 800},
    }
    resp = requests.post(url, json=payload, timeout=60)
    resp.raise_for_status()
    return resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()


def call_llm(
    provider: str,
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    endpoint: str = "",
) -> str:
    """
    Dispatch to the correct LLM provider and return draft text.

    :param provider:    One of the known provider keys (openai, anthropic, …)
    :param api_key:     API key (empty string for Ollama local)
    :param model:       Model name string
    :param system_prompt: System-level instruction
    :param user_prompt: The user message (lead context + incoming email)
    :param endpoint:    Custom endpoint URL (required for ollama; overrides default for others)
    """
    # Resolve endpoint
    url = endpoint.strip() if endpoint and endpoint.strip() else _DEFAULT_ENDPOINTS.get(provider, "")

    if provider == "anthropic":
        return _call_anthropic(api_key, model, system_prompt, user_prompt)

    if provider == "gemini":
        return _call_gemini(api_key, model, system_prompt, user_prompt)

    if provider in ("openai", "deepseek", "groq", "mistral", "openrouter", "ollama", "custom"):
        if not url:
            raise ValueError(
                f"No endpoint URL configured for provider '{provider}'. "
                "Set the Endpoint URL in Lead Engine AI settings."
            )
        extra = {}
        if provider == "openrouter":
            extra = {"HTTP-Referer": "https://odoo.com", "X-Title": "Lead Engine AI"}
        return _call_openai_compatible(url, api_key, model, system_prompt, user_prompt, extra)

    raise ValueError(f"Unknown LLM provider: '{provider}'. Check Lead Engine AI settings.")


class LeadEngineAIReply(models.Model):
    _name = "lead.engine.ai.reply"
    _description = "AI Draft Reply"
    _order = "create_date desc"
    _rec_name = "subject"

    # ── Identity ────────────────────────────────────────────────
    lead_id = fields.Many2one(
        comodel_name="crm.lead",
        string="Lead",
        required=True,
        ondelete="cascade",
        index=True,
    )
    trigger_msg_id = fields.Many2one(
        comodel_name="mail.message",
        string="Triggering message",
        ondelete="set null",
        readonly=True,
    )

    # ── Email metadata ───────────────────────────────────────────
    from_email = fields.Char(string="From", readonly=True)
    subject = fields.Char(string="Subject")
    original_body = fields.Html(string="Received email", readonly=True, sanitize=False)
    gmail_account = fields.Char(
        string="Via Gmail account",
        readonly=True,
        help="Which monitored Gmail address received this email.",
    )

    # ── AI output ───────────────────────────────────────────────
    ai_draft = fields.Html(
        string="AI draft reply",
        help="Edit this before sending. The AI draft is a starting point.",
    )
    ai_model_used = fields.Char(string="Model used", readonly=True)
    ai_error = fields.Text(string="AI error", readonly=True)

    # ── Attachments ─────────────────────────────────────────────
    attachment_ids = fields.Many2many(
        comodel_name="ir.attachment",
        relation="lead_engine_ai_reply_attachment_rel",
        column1="reply_id",
        column2="attachment_id",
        string="Attachments",
        help="Files to attach when sending this reply (e.g. CV, brochure).",
    )

    # ── State ───────────────────────────────────────────────────
    state = fields.Selection(
        selection=[
            ("pending", "Pending approval"),
            ("sent", "Sent"),
            ("discarded", "Discarded"),
        ],
        string="State",
        default="pending",
        required=True,
    )

    # ── Actions ─────────────────────────────────────────────────
    def action_review_and_send(self):
        """Open the native mail compose window pre-filled with the AI draft."""
        self.ensure_one()
        if self.state != "pending":
            raise UserError(_("This draft has already been %s.") % self.state)

        # Determine partner to reply to — try multiple fallbacks so the To: field
        # is always pre-filled even when the inbound message had no author_id
        # (e.g. fetchmail-routed emails that didn't resolve a partner).
        partner_ids = []

        # 1) Author of the triggering message (fastest path)
        if self.trigger_msg_id and self.trigger_msg_id.author_id:
            partner_ids = [self.trigger_msg_id.author_id.id]

        # 2) Find/create partner from the stored from_email on this reply record
        if not partner_ids and self.from_email:
            import re as _re
            m = _re.search(r"<([^>]+)>", self.from_email)
            clean_email = (m.group(1) if m else self.from_email).strip().lower()
            partner = self.env["res.partner"].sudo().search(
                [("email", "ilike", clean_email)], limit=1
            )
            if not partner:
                # Create a minimal partner so the compose window has a valid recipient
                partner = self.env["res.partner"].sudo().create({
                    "name": self.from_email.split("<")[0].strip() or clean_email,
                    "email": clean_email,
                })
            partner_ids = [partner.id]

        # 3) Final fallback: use the lead's own partner
        if not partner_ids and self.lead_id.partner_id:
            partner_ids = [self.lead_id.partner_id.id]

        # Odoo 19 composer: use default_model + default_res_ids (default_res_id is rejected).
        # Subject/body/attachments are applied in wizard/lead_engine_ai_compose.py from this record.
        return {
            "type": "ir.actions.act_window",
            "name": _("Review & Send AI Reply"),
            "res_model": "mail.compose.message",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_model": "crm.lead",
                "default_res_ids": [self.lead_id.id],
                "default_composition_mode": "comment",
                "default_message_type": "comment",
                "default_partner_ids": partner_ids,
                "default_parent_id": self.trigger_msg_id.id if self.trigger_msg_id else False,
                "lead_engine_ai_reply_id": self.id,
            },
        }

    def action_discard(self):
        """Mark this draft as discarded."""
        for rec in self.filtered(lambda r: r.state == "pending"):
            rec.state = "discarded"

    def action_regenerate(self):
        """Re-run AI generation for this draft."""
        self.ensure_one()
        if not self.trigger_msg_id:
            raise UserError(_("Cannot regenerate: original triggering message is missing."))
        lead = self.lead_id
        draft = lead._lead_engine_ai_generate_draft(self.trigger_msg_id)
        if draft:
            self.write({"ai_draft": draft, "state": "pending", "ai_error": False})
        return True

    # ── Compute helpers ─────────────────────────────────────────
    @api.model
    def _generate_draft(self, lead, trigger_msg):
        """
        Call the configured LLM and return (draft_text, model_used, error).
        Tries the primary provider first; falls back to secondary if configured.
        Returns (None, None, error_str) on failure.
        """
        icp = self.env["ir.config_parameter"].sudo()
        provider    = icp.get_param("lead_engine_ai.llm_provider", "openai")
        api_key     = icp.get_param("lead_engine_ai.llm_api_key", "")
        model       = icp.get_param("lead_engine_ai.llm_model", "gpt-4o-mini")
        endpoint    = icp.get_param("lead_engine_ai.llm_endpoint", "")
        # Secondary fallback
        provider_2  = icp.get_param("lead_engine_ai.llm_provider_2", "")
        api_key_2   = icp.get_param("lead_engine_ai.llm_api_key_2", "")
        model_2     = icp.get_param("lead_engine_ai.llm_model_2", "")
        endpoint_2  = icp.get_param("lead_engine_ai.llm_endpoint_2", "")
        custom_prompt = icp.get_param("lead_engine_ai.system_prompt", "")
        system_prompt = custom_prompt.strip() if custom_prompt.strip() else _DEFAULT_SYSTEM_PROMPT

        # Ollama needs no key; all others need one
        if not api_key and provider != "ollama":
            return None, None, "No LLM API key configured. Go to Lead Engine AI → Settings."

        # ── Build conversation context ─────────────────────────
        lead_name = lead.partner_name or lead.contact_name or lead.name or "(no name)"
        salesperson = lead.user_id.name if lead.user_id else "our team"
        company = lead.company_id.name if lead.company_id else self.env.company.name

        # Gather recent chatter messages (last 10, oldest first)
        recent_msgs = []
        for msg in reversed(lead.message_ids[:10]):
            if msg.body and msg.message_type in ("email", "comment"):
                author = msg.author_id.name or "Unknown"
                text = html2plaintext(msg.body).strip()
                if text:
                    recent_msgs.append(f"[{author}]: {text[:500]}")

        conversation_history = "\n".join(recent_msgs) if recent_msgs else "(no previous messages)"

        # The incoming email body
        incoming_text = html2plaintext(trigger_msg.body or "").strip()[:2000]
        incoming_from = trigger_msg.email_from or (trigger_msg.author_id.name if trigger_msg.author_id else "Unknown")

        user_prompt = (
            f"Lead: {lead_name}\n"
            f"Company: {company}\n"
            f"Our salesperson: {salesperson}\n\n"
            f"--- Conversation history (oldest to newest) ---\n"
            f"{conversation_history}\n\n"
            f"--- NEW incoming email from {incoming_from} ---\n"
            f"{incoming_text}\n\n"
            f"Draft a professional reply from {salesperson} ({company}) to this email. "
            f"Sign off with {salesperson}'s name."
        )

        def _to_html(text):
            paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
            return "\n".join(
                f"<p>{p.replace(chr(10), '<br/>')}</p>" for p in paragraphs
            ) or f"<p>{text}</p>"

        # ── Try primary ───────────────────────────────────────
        try:
            draft = call_llm(provider, api_key, model, system_prompt, user_prompt, endpoint)
            return _to_html(draft), f"{provider}/{model}", None
        except Exception as primary_exc:
            primary_err = f"Primary LLM ({provider}/{model}) failed: {primary_exc}"
            _logger.warning("[LeadEngineAI] %s", primary_err)

        # ── Try secondary fallback ────────────────────────────
        has_secondary = provider_2 and model_2 and (api_key_2 or provider_2 == "ollama")
        if has_secondary:
            try:
                draft = call_llm(provider_2, api_key_2, model_2, system_prompt, user_prompt, endpoint_2)
                return _to_html(draft), f"{provider_2}/{model_2} (fallback)", None
            except Exception as sec_exc:
                combined_err = f"{primary_err}\nFallback ({provider_2}/{model_2}) also failed: {sec_exc}"
                _logger.warning("[LeadEngineAI] %s", combined_err)
                return None, None, combined_err

        return None, None, primary_err
