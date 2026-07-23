# -*- coding: utf-8 -*-
"""
Extend mail.compose.message for Lead Engine AI.

Odoo 19:
- Context must use default_res_ids (not default_res_id), and default_model for crm.lead.
- Without a mail template, the standard composer _compute_body forces body to False,
  which cleared the AI draft; we restore subject/body/attachments from the
  lead.engine.ai.reply when lead_engine_ai_reply_id is in context.
"""
import logging

from odoo import api, models

_logger = logging.getLogger(__name__)


class MailComposeMessage(models.TransientModel):
    _inherit = "mail.compose.message"

    @api.depends(
        "composition_mode",
        "model",
        "parent_id",
        "res_domain",
        "res_ids",
        "template_id",
    )
    def _compute_subject(self):
        reply_id = self.env.context.get("lead_engine_ai_reply_id")
        if reply_id and not any(self.mapped("template_id")):
            reply = self.env["lead.engine.ai.reply"].browse(reply_id)
            if reply.exists():
                for composer in self:
                    subj = reply.subject or ""
                    if subj and not subj.startswith("Re:"):
                        subj = "Re: " + subj
                    composer.subject = subj
                return
        return super()._compute_subject()

    @api.depends(
        "composition_mode",
        "model",
        "res_domain",
        "res_ids",
        "template_id",
    )
    def _compute_body(self):
        reply_id = self.env.context.get("lead_engine_ai_reply_id")
        if reply_id and not any(self.mapped("template_id")):
            reply = self.env["lead.engine.ai.reply"].browse(reply_id)
            if reply.exists():
                for composer in self:
                    composer.body = reply.ai_draft or False
                return
        return super()._compute_body()

    @api.depends(
        "composition_mode",
        "model",
        "res_domain",
        "res_ids",
        "template_id",
    )
    def _compute_attachment_ids(self):
        reply_id = self.env.context.get("lead_engine_ai_reply_id")
        if reply_id and not any(self.mapped("template_id")):
            reply = self.env["lead.engine.ai.reply"].browse(reply_id)
            if reply.exists():
                # Use the files the user pre-attached to the draft reply record.
                # Do NOT forward the inbound email's attachments — those belong to
                # the sender and should not be echoed back.
                atts = reply.attachment_ids
                for composer in self:
                    composer.attachment_ids = atts
                return
        return super()._compute_attachment_ids()

    def _action_send_mail(self, auto_commit=False):
        """After sending, mark AI reply as sent and auto-convert lead to opportunity."""
        result = super()._action_send_mail(auto_commit=auto_commit)
        ai_reply_id = self.env.context.get("lead_engine_ai_reply_id")
        if ai_reply_id:
            try:
                reply = self.env["lead.engine.ai.reply"].browse(ai_reply_id)
                if reply.exists() and reply.state == "pending":
                    reply.state = "sent"
                    _logger.info("[LeadEngineAI] Reply %d marked as sent.", ai_reply_id)

                    lead = reply.lead_id
                    if lead and lead.exists() and lead.type != "opportunity":
                        vals = {"type": "opportunity"}
                        if "qualification_state" in lead._fields:
                            vals["qualification_state"] = "qualified"
                        lead.sudo().write(vals)
                        _logger.info(
                            "[LeadEngineAI] Lead %s auto-converted to opportunity after AI reply send.",
                            lead.id,
                        )
            except Exception as exc:
                _logger.warning("[LeadEngineAI] Could not mark reply as sent: %s", exc)
        return result
