# -*- coding: utf-8 -*-
import base64
import logging
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import html_escape

_logger = logging.getLogger(__name__)


class MailGmailFetchImportWizard(models.TransientModel):
    _name = "mail.gmail.fetch.import.wizard"
    _description = "Search Gmail and import messages via the provisioned incoming server"

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

    scope_base = fields.Char(
        string="Where to search",
        default="in:inbox",
        help=(
            "Gmail scope: in:inbox, in:anywhere, in:sent, in:spam (not recommended), etc. "
            "Combined with other filters below."
        ),
    )
    label_source = fields.Char(
        string="Label / source",
        help='Restrict to a Gmail label, e.g. Job Outreach or "My Label" (spaces allowed).',
    )
    sender = fields.Char(
        string="From (sender)",
        help="Email or domain. Examples: recruiter@company.com, @greenhouse.io",
    )
    subject_contains = fields.Char(
        string="Subject contains",
        help="Words that must appear in the subject (passed to Gmail subject: search).",
    )
    contains_words = fields.Char(
        string="Contains words (subject or body)",
        help="Space-separated terms; Gmail matches messages containing all of them.",
    )
    date_from = fields.Date(string="From date")
    date_to = fields.Date(string="To date (inclusive)")

    only_primary_category = fields.Boolean(
        string="Only Primary tab",
        help="Adds category:primary (Gmail “Primary” category).",
    )

    exclude_spam_trash = fields.Boolean(
        string="Exclude spam & trash",
        default=True,
        help="Adds -in:spam and -in:trash.",
    )
    exclude_category_tabs = fields.Boolean(
        string="Exclude Promotions / Social / Updates",
        default=True,
        help="Adds -category:promotions, -category:social, -category:forums.",
    )
    exclude_youtube = fields.Boolean(
        string="Exclude YouTube",
        default=True,
        help="Adds -from:youtube.com and related exclusions.",
    )
    exclude_bulk_senders = fields.Boolean(
        string="Exclude typical bulk / no-reply",
        default=False,
        help="Adds -from:noreply, -from:no-reply, -from:donotreply, etc.",
    )

    extra_gmail_query = fields.Char(
        string="Extra Gmail operators",
        help="Appended to the built query. Example: -larger:1M has:attachment",
    )

    max_messages = fields.Integer(
        string="Max messages",
        default=50,
        required=True,
        help="Maximum messages to list or import (1–200).",
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

    def _esc(self, s):
        return html_escape(s or "")

    def _format_label_token(self, label):
        label = (label or "").strip()
        if not label:
            return ""
        if any(ch in label for ch in ' \t\r\n'):
            escaped = label.replace("\\", "\\\\").replace('"', '\\"')
            return f'label:"{escaped}"'
        return f"label:{label}"

    def _format_sender_token(self, sender):
        sender = (sender or "").strip()
        if not sender:
            return ""
        low = sender.lower()
        if low.startswith("from:"):
            return sender
        return f"from:{sender}"

    def build_gmail_query(self):
        """Return the Gmail API ``q`` string for this wizard."""
        self.ensure_one()
        parts = []

        scope = (self.scope_base or "").strip()
        if scope:
            parts.append(scope)

        if self.label_source and (self.label_source or "").strip():
            parts.append(self._format_label_token(self.label_source))

        st = self._format_sender_token(self.sender)
        if st:
            parts.append(st)

        subj = (self.subject_contains or "").strip()
        if subj:
            # subject:(a b) groups words for subject search
            if " " in subj:
                esc = subj.replace("\\", "\\\\").replace('"', '\\"')
                parts.append(f'subject:"{esc}"')
            else:
                parts.append(f"subject:{subj}")

        words = (self.contains_words or "").strip()
        if words:
            parts.append(words)

        if self.date_from:
            parts.append(f"after:{self.date_from.strftime('%Y/%m/%d')}")
        if self.date_to:
            end = self.date_to + timedelta(days=1)
            parts.append(f"before:{end.strftime('%Y/%m/%d')}")

        if self.only_primary_category:
            parts.append("category:primary")

        if self.exclude_spam_trash:
            parts.extend(["-in:spam", "-in:trash"])
        if self.exclude_category_tabs:
            parts.extend(
                ["-category:promotions", "-category:social", "-category:forums"]
            )
        if self.exclude_youtube:
            parts.extend(
                [
                    "-from:youtube.com",
                    "-from:youtube-noreply.com",
                ]
            )
        if self.exclude_bulk_senders:
            parts.extend(
                [
                    "-from:noreply",
                    "-from:no-reply",
                    "-from:donotreply",
                    "-from:mailer-daemon",
                    "-from:notification",
                ]
            )

        extra = (self.extra_gmail_query or "").strip()
        if extra:
            parts.append(extra)

        return " ".join(p for p in parts if p).strip()

    def _ensure_account_and_server(self):
        self.ensure_one()
        account = self.account_id
        if account.state != "connected" and not account.refresh_token:
            raise UserError(_("Connect the Gmail account and ensure a refresh token is stored."))
        server = account.incoming_mail_server_id
        if not server:
            raise UserError(
                _("Provision the incoming mail server from this Gmail account first.")
            )
        if not server.object_id:
            raise UserError(
                _(
                    'Configure the incoming mail server: set “Create a New Record” '
                    "(e.g. Lead) before importing."
                )
            )
        return account, server

    def _list_message_ids(self, service, q, limit):
        """Return up to ``limit`` Gmail message ids (paginated)."""
        ids = []
        page_token = None
        while len(ids) < limit:
            batch = min(500, limit - len(ids))
            kwargs = {"userId": "me", "maxResults": batch, "q": q}
            if page_token:
                kwargs["pageToken"] = page_token
            try:
                resp = service.users().messages().list(**kwargs).execute()
            except Exception as e:
                _logger.exception("Gmail messages.list failed")
                raise UserError(_("Gmail search failed: %s") % e) from e
            for m in resp.get("messages", []):
                ids.append(m["id"])
                if len(ids) >= limit:
                    break
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        return ids

    def _fetch_metadata(self, service, mid):
        return (
            service.users()
            .messages()
            .get(
                userId="me",
                id=mid,
                format="metadata",
                metadataHeaders=["Subject", "From", "Date"],
            )
            .execute()
        )

    def _headers_dict(self, msg):
        return {
            h["name"].lower(): h["value"]
            for h in msg.get("payload", {}).get("headers", [])
        }

    def action_preview(self):
        self.ensure_one()
        lim = self.max_messages
        if lim < 1 or lim > 200:
            raise UserError(_("Max messages must be between 1 and 200."))
        account, _server = self._ensure_account_and_server()
        try:
            service = account._gmail_service()
        except Exception as e:
            _logger.exception("Gmail API client failed")
            raise UserError(_("Could not connect to Gmail API: %s") % e) from e

        q = self.build_gmail_query()
        if not q:
            raise UserError(_("Build a non-empty search (e.g. keep “Where to search” as in:inbox)."))

        mids = self._list_message_ids(service, q, lim)
        rows = [
            "<h4>Preview</h4>",
            f"<p><strong>Gmail query</strong>: <code>{self._esc(q)}</code></p>",
            f"<p><strong>Messages matched</strong>: {len(mids)}</p>",
            "<table class='table table-sm'><thead><tr><th>From</th><th>Subject</th></tr></thead><tbody>",
        ]
        for mid in mids[: min(40, len(mids))]:
            try:
                msg = self._fetch_metadata(service, mid)
                h = self._headers_dict(msg)
                rows.append(
                    "<tr><td>%s</td><td>%s</td></tr>"
                    % (
                        self._esc((h.get("from") or "")[:120]),
                        self._esc((h.get("subject") or "(no subject)")[:200]),
                    )
                )
            except Exception as e:
                rows.append(
                    f"<tr><td colspan='2'>{self._esc(str(e))}</td></tr>"
                )
        rows.append("</tbody></table>")
        if len(mids) > 40:
            rows.append(f"<p><em>Showing 40 of {len(mids)}; import processes up to max messages.</em></p>")
        self.write({"result_html": "\n".join(rows)})
        return self._reload_wizard()

    def action_import(self):
        self.ensure_one()
        lim = self.max_messages
        if lim < 1 or lim > 200:
            raise UserError(_("Max messages must be between 1 and 200."))
        account, server = self._ensure_account_and_server()
        try:
            service = account._gmail_service()
        except Exception as e:
            _logger.exception("Gmail API client failed")
            raise UserError(_("Could not connect to Gmail API: %s") % e) from e

        q = self.build_gmail_query()
        if not q:
            raise UserError(_("Build a non-empty search."))

        mids = self._list_message_ids(service, q, lim)
        model = server.object_id.model

        imported = skipped = failed = 0
        errors = []

        for mid in mids:
            try:
                gmsg = (
                    service.users()
                    .messages()
                    .get(userId="me", id=mid, format="raw")
                    .execute()
                )
                raw_b64 = gmsg.get("raw")
                if not raw_b64:
                    failed += 1
                    errors.append(f"{mid}: no raw payload")
                    continue
                raw_bytes = base64.urlsafe_b64decode(raw_b64.encode("ascii"))

                cr = self.env.registry.cursor()
                try:
                    env = api.Environment(cr, self.env.uid, dict(self.env.context))
                    mt = env["mail.thread"].with_context(
                        default_fetchmail_server_id=server.id
                    )
                    res = mt.message_process(
                        model,
                        raw_bytes,
                        save_original=server.original,
                        strip_attachments=(not server.attach),
                    )
                    cr.commit()
                except Exception:
                    cr.rollback()
                    raise
                finally:
                    cr.close()

                if res:
                    imported += 1
                else:
                    skipped += 1
            except Exception as e:
                failed += 1
                errors.append(f"{mid}: {e}")
                _logger.warning("Gmail import message %s failed: %s", mid, e)

        err_html = ""
        if errors:
            err_html = "<h4>Errors (sample)</h4><ul>" + "".join(
                f"<li>{self._esc(e[:300])}</li>" for e in errors[:15]
            ) + "</ul>"

        summary = [
            "<h4>Import finished</h4>",
            f"<p><strong>Query</strong>: <code>{self._esc(q)}</code></p>",
            "<table class='table table-sm'><tbody>",
            f"<tr><td>Listed</td><td>{len(mids)}</td></tr>",
            f"<tr><td>Imported (new)</td><td>{imported}</td></tr>",
            f"<tr><td>Skipped (duplicate / loop)</td><td>{skipped}</td></tr>",
            f"<tr><td>Failed</td><td>{failed}</td></tr>",
            "</tbody></table>",
            "<p><em>Skipped</em> usually means the Message-Id already exists in Odoo.</p>",
            err_html,
        ]
        self.write({"result_html": "\n".join(summary)})
        return self._reload_wizard()

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

    def _reload_wizard(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Search Gmail and import"),
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }
