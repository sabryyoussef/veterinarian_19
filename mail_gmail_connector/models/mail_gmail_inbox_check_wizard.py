# -*- coding: utf-8 -*-
import logging
import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import html_escape

_logger = logging.getLogger(__name__)


def _norm_subject(s):
    if not s:
        return ""
    return re.sub(r"\s+", " ", s.strip().lower())


class MailGmailInboxCheckWizard(models.TransientModel):
    _name = "mail.gmail.inbox.check.wizard"
    _description = "Compare Gmail API results with Odoo CRM leads"

    account_id = fields.Many2one(
        "mail.gmail.account",
        string="Gmail account",
        required=True,
        ondelete="cascade",
    )
    incoming_mail_server_id = fields.Many2one(
        related="account_id.incoming_mail_server_id",
        readonly=True,
    )
    message_limit = fields.Integer(
        string="Messages / leads to compare",
        default=150,
        required=True,
    )
    gmail_query = fields.Char(
        string="Gmail search query",
        default="in:inbox",
        help=(
            "Passed to Gmail API messages.list as parameter q. "
            "Examples: in:inbox, label:Job Outreach, newer_than:7d"
        ),
    )
    result_html = fields.Html(
        string="Result",
        readonly=True,
        sanitize=False,
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if self.env.context.get("default_account_id"):
            res["account_id"] = self.env.context["default_account_id"]
        return res

    def action_run_compare(self):
        self.ensure_one()
        if self.message_limit < 1 or self.message_limit > 500:
            raise UserError(_("Limit must be between 1 and 500."))
        account = self.account_id
        if account.state != "connected" and not account.refresh_token:
            raise UserError(_("Connect the Gmail account and ensure a refresh token is stored."))

        try:
            service = account._gmail_service()
        except Exception as e:
            _logger.exception("Gmail API client failed")
            raise UserError(_("Could not connect to Gmail API: %s") % e) from e

        q = (self.gmail_query or "").strip()
        list_kwargs = {"userId": "me", "maxResults": self.message_limit}
        if q:
            list_kwargs["q"] = q
        else:
            list_kwargs["labelIds"] = ["INBOX"]

        try:
            lst = service.users().messages().list(**list_kwargs).execute()
        except Exception as e:
            _logger.exception("Gmail messages.list failed")
            raise UserError(_("Gmail list failed: %s") % e) from e

        mids = [m["id"] for m in lst.get("messages", [])]
        gmail_subjects = []
        for mid in mids:
            try:
                msg = (
                    service.users()
                    .messages()
                    .get(
                        userId="me",
                        id=mid,
                        format="metadata",
                        metadataHeaders=["Subject", "From"],
                    )
                    .execute()
                )
                headers = {
                    h["name"].lower(): h["value"]
                    for h in msg.get("payload", {}).get("headers", [])
                }
                gmail_subjects.append(
                    {
                        "subject": headers.get("subject", ""),
                        "from": headers.get("from", "")[:160],
                    }
                )
            except Exception as e:
                _logger.warning("Gmail get message %s: %s", mid, e)
                gmail_subjects.append({"subject": "(fetch error)", "from": ""})

        Lead = self.env["crm.lead"].sudo()
        leads = Lead.search(
            [], order="create_date desc, id desc", limit=self.message_limit
        )
        odoo_subjects = [{"subject": lead.name or "", "id": lead.id} for lead in leads]

        g_set = {_norm_subject(x["subject"]) for x in gmail_subjects if _norm_subject(x["subject"])}
        o_set = {_norm_subject(x["subject"]) for x in odoo_subjects if _norm_subject(x["subject"])}
        overlap = g_set & o_set
        only_g = g_set - o_set
        only_o = o_set - g_set

        def esc(s):
            return html_escape(s or "")

        rows = []
        rows.append(
            "<table class='table table-sm'><thead><tr>"
            "<th>Metric</th><th>Value</th></tr></thead><tbody>"
        )
        rows.append(
            f"<tr><td>Gmail messages listed</td><td>{len(mids)}</td></tr>"
        )
        rows.append(f"<tr><td>Odoo CRM leads</td><td>{len(leads)}</td></tr>")
        rows.append(
            f"<tr><td>Unique subjects (Gmail)</td><td>{len(g_set)}</td></tr>"
        )
        rows.append(
            f"<tr><td>Unique subjects (Odoo)</td><td>{len(o_set)}</td></tr>"
        )
        rows.append(
            f"<tr><td><strong>Matching subjects (normalized)</strong></td>"
            f"<td><strong>{len(overlap)}</strong></td></tr>"
        )
        rows.append("</tbody></table>")

        rows.append("<h4>Sample: only in Gmail (up to 8)</h4><ul>")
        for s in list(only_g)[:8]:
            rows.append(f"<li>{esc(s[:200])}</li>")
        rows.append("</ul>")

        rows.append("<h4>Sample: only in Odoo (up to 8)</h4><ul>")
        for s in list(only_o)[:8]:
            rows.append(f"<li>{esc(s[:200])}</li>")
        rows.append("</ul>")

        rows.append("<h4>Newest 5 in Gmail (API order)</h4><ol>")
        for x in gmail_subjects[:5]:
            rows.append(f"<li>{esc((x['subject'] or '(no subject)')[:200])}</li>")
        rows.append("</ol>")

        rows.append("<h4>Newest 5 in Odoo (by create_date)</h4><ol>")
        for x in odoo_subjects[:5]:
            rows.append(
                f"<li>{esc((x['subject'] or '(no subject)')[:200])} "
                f"<small>(lead id {x['id']})</small></li>"
            )
        rows.append("</ol>")

        rows.append(
            "<p><em>Low overlap is normal if fetch used UNSEEN, another label, or an older batch. "
            "Use <strong>Gmail fetch scope = All messages</strong> on the Gmail account form and "
            "<strong>Fetch Now</strong> on the incoming server to align imports.</em></p>"
        )

        self.write({"result_html": "\n".join(rows)})
        return {
            "type": "ir.actions.act_window",
            "name": _("Compare Gmail vs CRM leads"),
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    def action_open_incoming_server(self):
        self.ensure_one()
        srv = self.account_id.incoming_mail_server_id
        if not srv:
            raise UserError(_("Provision the incoming mail server from this Gmail account first."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Incoming mail server"),
            "res_model": "fetchmail.server",
            "res_id": srv.id,
            "view_mode": "form",
            "target": "current",
        }
