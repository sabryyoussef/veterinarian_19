# -*- coding: utf-8 -*-
"""
crm.lead extension for Lead Engine AI
======================================
- Hooks into message_post to detect inbound external emails
- Triggers background AI draft generation (non-blocking)
- Adds smart button to show pending AI drafts count
"""
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class CrmLead(models.Model):
    _inherit = "crm.lead"

    # ── Smart button counter ─────────────────────────────────────
    ai_reply_count = fields.Integer(
        compute="_compute_ai_reply_count",
        string="AI Drafts",
        store=False,
    )
    ai_reply_pending_count = fields.Integer(
        compute="_compute_ai_reply_count",
        string="Pending AI Drafts",
        store=False,
    )
    ai_reply_ids = fields.One2many(
        comodel_name="lead.engine.ai.reply",
        inverse_name="lead_id",
        string="AI Draft Replies",
    )

    @api.depends("ai_reply_ids.state")
    def _compute_ai_reply_count(self):
        for lead in self:
            replies = lead.ai_reply_ids
            lead.ai_reply_count = len(replies)
            lead.ai_reply_pending_count = len(replies.filtered(lambda r: r.state == "pending"))

    # ── Smart button action ─────────────────────────────────────
    def action_view_ai_replies(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "AI Draft Replies",
            "res_model": "lead.engine.ai.reply",
            "view_mode": "list,form",
            "domain": [("lead_id", "=", self.id)],
            "context": {"default_lead_id": self.id},
        }

    # ── message_post hook ───────────────────────────────────────
    def message_post(self, **kwargs):
        """After posting a message, trigger AI draft for inbound external emails."""
        msg = super().message_post(**kwargs)
        # Only process if it's a proper email-type message
        if (
            msg
            and msg.message_type == "email"
            and self._is_external_inbound_message(msg)
            and self._lead_engine_ai_is_monitored(msg)
            and not self._lead_engine_ai_draft_exists(msg)
        ):
            self._lead_engine_ai_create_draft(msg)
        return msg

    # ── Detection helpers ────────────────────────────────────────
    def _is_external_inbound_message(self, msg):
        """Return True if the message is from an external (non-Odoo-user) sender.

        Fetchmail-routed emails from unknown contacts have no author_id — those are
        the most external possible, so we treat missing author as external too.
        """
        author = msg.author_id
        if not author:
            # No partner resolved — check email_from is not an internal Odoo user address
            if not msg.email_from:
                return False
            from_email = (msg.email_from or "").lower()
            internal_match = self.env["res.users"].sudo().search([
                ("email", "ilike", from_email),
                ("share", "=", False),
                ("active", "=", True),
            ], limit=1)
            return not internal_match
        # Known partner — check if they have any internal Odoo user account
        internal_users = author.user_ids.filtered(lambda u: not u.share and u.active)
        return not internal_users

    def _lead_engine_ai_is_monitored(self, msg):
        """
        Check if this email came through a monitored address.
        If no monitored addresses are configured, trigger for ALL inbound emails.

        Detection order:
        1. gateway_mail_to field (set by mail_gmail_connector for inbound gateway messages)
        2. In-Reply-To chain — find original outgoing message email_from (fetchmail replies)
        3. Lead's responsible user email
        4. Any fetchmail server user in the monitored list (broadest fallback)
        """
        icp = self.env["ir.config_parameter"].sudo()
        monitored_raw = icp.get_param("lead_engine_ai.monitored_emails", "").strip()
        if not monitored_raw:
            return True  # no filter — trigger for everything
        monitored = {e.strip().lower() for e in monitored_raw.split(",") if e.strip()}
        if not monitored:
            return True

        # 1. Check gateway_mail_to (set by mail_gmail_connector)
        if hasattr(self, "gateway_mail_to"):
            to_field = (self.gateway_mail_to or "").lower()
            for addr in monitored:
                if addr in to_field:
                    return True

        # 2. Walk parent_id chain to find the original outgoing message email_from.
        #    Fetchmail-routed replies have parent_id pointing to the sent message.
        parent = msg.parent_id
        if parent and parent.email_from:
            from_addr = parent.email_from.lower()
            for addr in monitored:
                if addr in from_addr:
                    return True

        # 3. Lead's responsible user email
        if self.user_id and self.user_id.email:
            if self.user_id.email.lower() in monitored:
                return True

        # 4. Broadest fallback: any active fetchmail server user is in the monitored list
        fetchmail_users = self.env["fetchmail.server"].sudo().search(
            [("active", "=", True)]
        ).mapped("user")
        for fu in fetchmail_users:
            if fu and fu.lower() in monitored:
                return True

        return False

    def _lead_engine_ai_draft_exists(self, msg):
        """Return True if a pending draft already exists for this message."""
        return bool(
            self.env["lead.engine.ai.reply"].search(
                [
                    ("lead_id", "=", self.id),
                    ("trigger_msg_id", "=", msg.id),
                    ("state", "=", "pending"),
                ],
                limit=1,
            )
        )

    # ── Draft generation ────────────────────────────────────────
    def _lead_engine_ai_create_draft(self, trigger_msg):
        """
        Call AI to draft a reply and store the result in lead.engine.ai.reply.
        All errors are caught — never raises (to avoid breaking the mail pipeline).
        """
        try:
            AiReply = self.env["lead.engine.ai.reply"]
            draft_html, model_used, error = AiReply._generate_draft(self, trigger_msg)

            # Determine which monitored account received this (for display)
            gmail_account = self._lead_engine_ai_detect_account()

            AiReply.create({
                "lead_id": self.id,
                "trigger_msg_id": trigger_msg.id,
                "from_email": trigger_msg.email_from or (trigger_msg.author_id.email if trigger_msg.author_id else ""),
                "subject": trigger_msg.subject or self.name or "",
                "original_body": trigger_msg.body or "",
                "gmail_account": gmail_account,
                "ai_draft": draft_html or "",
                "ai_model_used": model_used or "",
                "ai_error": error or "",
                "state": "pending" if draft_html else "pending",  # keep pending even on error for manual review
            })

            if error:
                _logger.warning("[LeadEngineAI] Draft created with error on lead %s: %s", self.id, error)
            else:
                _logger.info("[LeadEngineAI] Draft created for lead %s using %s", self.id, model_used)

        except Exception as exc:
            # Absolute fallback: log and continue — never break mail pipeline
            _logger.error("[LeadEngineAI] Unexpected error creating draft for lead %s: %s", self.id, exc)

    def _lead_engine_ai_generate_draft(self, trigger_msg):
        """Re-run AI draft generation and return the HTML text."""
        AiReply = self.env["lead.engine.ai.reply"]
        draft_html, _model, _error = AiReply._generate_draft(self, trigger_msg)
        return draft_html

    def _lead_engine_ai_detect_account(self):
        """Try to identify which monitored Gmail account received this email."""
        icp = self.env["ir.config_parameter"].sudo()
        monitored_raw = icp.get_param("lead_engine_ai.monitored_emails", "").strip()
        monitored = [e.strip().lower() for e in monitored_raw.split(",") if e.strip()]
        if not monitored:
            return ""
        # Check gateway_mail_to if available
        if hasattr(self, "gateway_mail_to"):
            to_field = (self.gateway_mail_to or "").lower()
            for addr in monitored:
                if addr in to_field:
                    return addr
        # Fallback: responsible user email
        if self.user_id and self.user_id.email:
            email = self.user_id.email.lower()
            if email in monitored:
                return email
        return monitored[0] if monitored else ""
