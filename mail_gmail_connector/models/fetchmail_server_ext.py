# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.addons.mail.models.fetchmail import MAIL_TIMEOUT, OdooIMAP4_SSL
from odoo.exceptions import UserError


class OdooIMAP4GmailConnector(OdooIMAP4_SSL):
    """Gmail IMAP: keep the same mailbox as _imap_login__ SELECT.

    Core ``OdooIMAP4.check_unread_messages`` calls ``select()`` with no arguments,
    which re-selects INBOX and ignores a previously selected Gmail label.

    Search criteria (UNSEEN vs ALL) is stored on the connection by ``_imap_login__``.
    """

    def check_unread_messages(self):
        mbox = getattr(self, "_odoo_imap_mailbox", None)
        if mbox is not None:
            self.select(mbox)
        else:
            self.select()
        crit = getattr(self, "_odoo_imap_search", "(UNSEEN)")
        _result, data = self.search(None, crit)
        self._unread_messages = data[0].split() if data and data[0] else []
        self._unread_messages.reverse()
        return len(self._unread_messages)


class FetchmailServerGmailConnector(models.Model):
    """Extend fetchmail.server with a back-link to the Gmail Connector account
    that provisioned it, so token refresh uses per-account client credentials."""

    _inherit = "fetchmail.server"

    gmail_connector_account_id = fields.Many2one(
        "mail.gmail.account",
        string="Gmail Connector Account",
        ondelete="set null",
        copy=False,
    )
    gmail_imap_mailbox = fields.Char(
        string="IMAP mailbox / Gmail label",
        default="INBOX",
        help=(
            "Gmail folder to read (IMAP SELECT). Use INBOX for all mail, or the exact "
            "name of a Gmail label (e.g. Recruiters) after you create a filter that "
            "labels recruiter mail. ASCII label names work as-is; special characters "
            "may need Gmail’s IMAP encoding."
        ),
    )
    gmail_inbound_subject_keywords = fields.Text(
        string="Only if subject contains (optional)",
        help=(
            "If set, only messages whose subject contains at least one of these "
            "comma- or line-separated keywords (case-insensitive) create records. "
            "Leave empty to not filter by subject (still use a dedicated label "
            "above to avoid importing the whole inbox)."
        ),
    )
    gmail_inbound_exclude_domains = fields.Text(
        string="Skip senders containing (optional)",
        help=(
            "Comma-separated substrings matched against the From header (lowercase). "
            "Example: youtube.com, noreply@, facebookmail.com — matched messages are "
            "ignored and marked read on the server."
        ),
    )
    gmail_imap_fetch_scope = fields.Selection(
        [
            ("unseen", "Unread only (IMAP UNSEEN)"),
            ("all_in_mailbox", "All messages in this mailbox (IMAP ALL)"),
        ],
        string="Gmail fetch scope",
        default="unseen",
        help=(
            "Unread only: only UNSEEN messages. "
            "All messages: imports the whole mailbox (read + unread). "
            "Use for a full local copy; may duplicate if the same message was imported twice. "
            "For INBOX + All messages, enable “Allow full INBOX import” below."
        ),
    )
    gmail_allow_inbox_all = fields.Boolean(
        string="Allow full INBOX import (IMAP ALL on INBOX)",
        default=True,
        help=(
            "Required when “Gmail fetch scope” is “All messages” and the mailbox is INBOX. "
            "Turn off if you only want a label or unread-only on INBOX."
        ),
    )

    @api.constrains(
        "server_type",
        "gmail_imap_mailbox",
        "gmail_imap_fetch_scope",
        "gmail_allow_inbox_all",
    )
    def _check_gmail_fetch_all_inbox(self):
        for server in self:
            if server.server_type != "gmail":
                continue
            if server.gmail_imap_fetch_scope != "all_in_mailbox":
                continue
            m = (server.gmail_imap_mailbox or "INBOX").strip().upper()
            if m == "INBOX" and not server.gmail_allow_inbox_all:
                raise UserError(
                    _(
                        "To import all messages from INBOX (including read mail), enable "
                        "“Allow full INBOX import”. Or switch to “Unread only”, or set "
                        "“IMAP mailbox / Gmail label” to a specific label."
                    )
                )

    def _fetch_mail(self, batch_limit=50):
        """Batch size: core default 50; use 0 or empty ICP = effectively unlimited.

        Parameter: ``mail_gmail_connector.fetchmail_batch_limit`` (integer; 0 = no cap).
        """
        raw = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("mail_gmail_connector.fetchmail_batch_limit", "0")
            .strip()
        )
        if raw in ("", "0", "unlimited"):
            batch_limit = 10**9
        else:
            try:
                batch_limit = max(int(raw), 1)
            except ValueError:
                batch_limit = 50
        return super()._fetch_mail(batch_limit=batch_limit)

    def _fetch_gmail_access_token(self, refresh_token):
        self.ensure_one()
        if self.gmail_connector_account_id:
            return self.gmail_connector_account_id.sudo()._gmail_fetch_access_token_direct(
                refresh_token
            )
        return super()._fetch_gmail_access_token(refresh_token)

    def _connect__(self, allow_archived=False):
        """Use a Gmail IMAP class that does not reset SELECT to INBOX before UNSEEN search."""
        self.ensure_one()
        if not allow_archived and not self.active:
            raise UserError(
                _('The server "%s" cannot be used because it is archived.', self.display_name)
            )
        if self._get_connection_type() == "imap" and self.server_type == "gmail" and self.is_ssl:
            server, port = self.server, int(self.port)
            connection = OdooIMAP4GmailConnector(server, port, timeout=MAIL_TIMEOUT)
            self._imap_login__(connection)
            return connection
        return super()._connect__(allow_archived=allow_archived)

    def _gmail_imap_select_mailbox(self, mailbox):
        """Build the mailbox argument for IMAP SELECT (quoted if needed).

        Gmail label names with spaces (e.g. ``Job Outreach``) must be sent as a
        single quoted string or Gmail returns ``BAD Could not parse command``.
        """
        raw = (mailbox or "INBOX").strip() or "INBOX"
        if raw.upper() == "INBOX":
            return "INBOX"
        if any(ch in raw for ch in ' \t\r\n(){%*]"\\'):
            escaped = raw.replace("\\", "\\\\").replace('"', '\\"')
            return '"%s"' % escaped
        return raw

    def _imap_login__(self, connection):  # noqa: PLW3201
        """Same as google_gmail, but SELECT the configured mailbox/label."""
        self.ensure_one()
        if self.server_type == "gmail":
            auth_string = self._generate_oauth2_string(
                self.user, self.google_gmail_refresh_token
            )
            connection.authenticate("XOAUTH2", lambda x: auth_string)
            mailbox_raw = (self.gmail_imap_mailbox or "INBOX").strip() or "INBOX"
            mailbox_arg = self._gmail_imap_select_mailbox(mailbox_raw)
            typ, data = connection.select(mailbox_arg)
            if typ != "OK":
                raise UserError(
                    _("Could not open mailbox “%s”: %s") % (mailbox_raw, data)
                )
            connection._odoo_imap_mailbox = mailbox_arg
            if self.gmail_imap_fetch_scope == "all_in_mailbox":
                connection._odoo_imap_search = "(ALL)"
            else:
                connection._odoo_imap_search = "(UNSEEN)"
        else:
            super()._imap_login__(connection)
