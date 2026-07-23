# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.tools import email_normalize
from odoo.tools.mail import email_split


class CrmLeadGmail(models.Model):
    _inherit = "crm.lead"

    job_outreach_match = fields.Boolean(
        string="Job outreach match",
        compute="_compute_job_outreach_match",
        store=True,
        index=True,
        help=(
            "True when the Gmail label line contains “Job Outreach”, or the subject matches "
            "configured keywords, or the sender domain looks like a careers / ATS domain. "
            "IMAP often omits X-Gmail-Labels, so this is the main filter."
        ),
    )
    gmail_labels = fields.Text(
        string="Gmail labels",
        readonly=True,
        copy=False,
        help=(
            "Gmail label list from the fetched message (IMAP header X-Gmail-Labels), "
            "when present. Search or use quick filters."
        ),
    )
    sender_domain = fields.Char(
        string="Sender domain",
        compute="_compute_sender_domain",
        store=True,
        index=True,
        readonly=True,
        help="Domain part of the sender address (for filters and grouping).",
    )
    gateway_mail_to = fields.Text(
        string="Mail To (gateway)",
        readonly=True,
        copy=False,
        help="To / Delivered-To from the original incoming email (searchable).",
    )
    gateway_mail_cc = fields.Text(
        string="Mail Cc (gateway)",
        readonly=True,
        copy=False,
    )
    mail_list_id = fields.Char(
        string="List-Id",
        readonly=True,
        copy=False,
        help="Mailing-list identifier from List-Id header, if any.",
    )

    @api.depends("email_from")
    def _compute_sender_domain(self):
        for lead in self:
            lead.sender_domain = lead._parse_sender_domain(lead.email_from)

    @api.depends("gmail_labels", "name", "sender_domain", "email_from")
    def _compute_job_outreach_match(self):
        icp = self.env["ir.config_parameter"].sudo()
        kw_line = icp.get_param(
            "mail_gmail_connector.job_outreach_keywords",
            "interview,recruiter,application,position,hiring,opportunity,candidate,resume,job offer,job opening",
        )
        career_line = icp.get_param(
            "mail_gmail_connector.job_outreach_sender_domains",
            "linkedin.com,indeed.com,greenhouse.io,lever.co,myworkday.com,smartrecruiters.com",
        )
        keywords = [k.strip().lower() for k in kw_line.split(",") if k.strip()]
        career_domains = [d.strip().lower() for d in career_line.split(",") if d.strip()]
        for lead in self:
            match = False
            gl = (lead.gmail_labels or "").lower()
            if "job outreach" in gl or "job-outreach" in gl:
                match = True
            if not match and lead.name:
                subj = lead.name.lower()
                if any(k in subj for k in keywords):
                    match = True
            if not match and lead.sender_domain:
                sd = lead.sender_domain.lower()
                if any(d in sd for d in career_domains):
                    match = True
            lead.job_outreach_match = match

    @api.model
    def _parse_sender_domain(self, email_from):
        if not email_from:
            return False
        addrs = email_split(email_from)
        if not addrs:
            return False
        norm = email_normalize(addrs[0])
        if not norm or "@" not in norm:
            return False
        return norm.split("@", 1)[1].lower()

    @api.model
    def message_new(self, msg_dict, custom_values=None):
        if custom_values is None:
            custom_values = {}
        custom_values = dict(custom_values)
        if msg_dict.get("gmail_labels"):
            custom_values["gmail_labels"] = (msg_dict["gmail_labels"] or "")[:8000]
        if msg_dict.get("gateway_mail_to"):
            custom_values["gateway_mail_to"] = (msg_dict["gateway_mail_to"] or "")[:8000]
        if msg_dict.get("gateway_mail_cc"):
            custom_values["gateway_mail_cc"] = (msg_dict["gateway_mail_cc"] or "")[:4000]
        if msg_dict.get("mail_list_id"):
            custom_values["mail_list_id"] = (msg_dict["mail_list_id"] or "")[:500]
        return super().message_new(msg_dict, custom_values=custom_values)
