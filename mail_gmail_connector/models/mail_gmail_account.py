# -*- coding: utf-8 -*-
import base64
import logging
import time
from email.mime.text import MIMEText

import requests

from odoo import _, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

GMAIL_TOKEN_URI = "https://oauth2.googleapis.com/token"
DEFAULT_GMAIL_SCOPES = (
    # https://mail.google.com/ is required for SMTP/IMAP XOAUTH2.
    # Must also be listed in Google Cloud Console → OAuth consent screen → Data access.
    "https://mail.google.com/ "
    "https://www.googleapis.com/auth/gmail.send "
    "https://www.googleapis.com/auth/gmail.modify "
    "https://www.googleapis.com/auth/gmail.readonly "
    "https://www.googleapis.com/auth/userinfo.email"
)


class MailGmailAccount(models.Model):
    _name = "mail.gmail.account"
    _description = "Gmail OAuth mailbox"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "name"

    name = fields.Char(required=True, tracking=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        default=lambda self: self.env.company,
        required=True,
        index=True,
    )
    user_id = fields.Many2one(
        "res.users",
        string="Responsible",
        default=lambda self: self.env.user,
        required=True,
        index=True,
        tracking=True,
    )
    gmail_email = fields.Char(string="Gmail address", tracking=True)
    state = fields.Selection(
        [
            ("draft", "Not connected"),
            ("connected", "Connected"),
            ("error", "Error"),
        ],
        string="Status",
        default="draft",
        required=True,
        tracking=True,
    )
    oauth_client_id = fields.Char(groups="mail_gmail_connector.group_gmail_manager")
    oauth_client_secret = fields.Char(groups="mail_gmail_connector.group_gmail_manager")
    refresh_token = fields.Char(groups="mail_gmail_connector.group_gmail_manager")
    scopes = fields.Text(
        string="OAuth scopes",
        groups="mail_gmail_connector.group_gmail_manager",
        default=DEFAULT_GMAIL_SCOPES,
        help="Space- or newline-separated scopes. Default includes send + profile metadata.",
    )
    last_sync_at = fields.Datetime(string="Last sync", readonly=True)
    last_error = fields.Text(string="Last error", readonly=True)

    # Phase D — provisioned mail servers
    outgoing_mail_server_id = fields.Many2one(
        "ir.mail_server",
        string="Outgoing mail server",
        copy=False,
        readonly=True,
        ondelete="set null",
    )
    incoming_mail_server_id = fields.Many2one(
        "fetchmail.server",
        string="Incoming mail server",
        copy=False,
        readonly=True,
        ondelete="set null",
    )

    def _gmail_ensure_libraries(self):
        try:
            import google.auth.transport.requests  # noqa: F401
            from google.oauth2.credentials import Credentials  # noqa: F401
            from googleapiclient.discovery import build  # noqa: F401
        except ImportError as e:
            raise UserError(
                _(
                    "Python libraries for Google are not installed on this server. "
                    "Install them with pip, for example:\n"
                    "  pip install google-api-python-client google-auth google-auth-oauthlib\n"
                    "See addons/mail_gmail_connector/requirements.txt"
                )
            ) from e

    def _gmail_scope_list(self):
        self.ensure_one()
        raw = (self.scopes or DEFAULT_GMAIL_SCOPES).replace(",", " ")
        return [s for s in raw.split() if s]

    def _gmail_oauth_web_client_config(self, redirect_uri=None):
        """Google OAuth 'web' client JSON for google_auth_oauthlib.flow.Flow."""
        self.ensure_one()
        cfg = {
            "web": {
                "client_id": self.oauth_client_id.strip(),
                "client_secret": self.oauth_client_secret.strip(),
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": GMAIL_TOKEN_URI,
            }
        }
        if redirect_uri:
            cfg["web"]["redirect_uris"] = [redirect_uri]
        return cfg

    def action_gmail_connect_google(self):
        self.ensure_one()
        self.check_access("write")
        if not self.env.user.has_group("mail_gmail_connector.group_gmail_manager"):
            raise UserError(_("Only Gmail managers can run the OAuth connection flow."))
        if not (self.oauth_client_id and self.oauth_client_secret):
            raise UserError(
                _("Set OAuth Client ID and Client secret on this account before connecting.")
            )
        self._gmail_ensure_libraries()
        return {
            "type": "ir.actions.act_url",
            "url": f"/google_gmail/mail_connector_oauth/start?account_id={self.id}",
            "target": "self",
        }

    def _gmail_credentials(self):
        self.ensure_one()
        self._gmail_ensure_libraries()
        from google.oauth2.credentials import Credentials

        if not (self.refresh_token and self.oauth_client_id and self.oauth_client_secret):
            raise UserError(
                _("Set OAuth Client ID, Client secret, and Refresh token (Gmail managers only).")
            )
        # Do not pass scopes here: google-auth includes them in the refresh-token POST body,
        # causing invalid_scope if Google's actual grant differs from what we stored.
        # Omitting scopes lets the token endpoint return all originally-granted scopes.
        return Credentials(
            token=None,
            refresh_token=self.refresh_token.strip(),
            token_uri=GMAIL_TOKEN_URI,
            client_id=self.oauth_client_id.strip(),
            client_secret=self.oauth_client_secret.strip(),
        )

    def _gmail_refresh_credentials(self, creds):
        from google.auth.transport.requests import Request

        creds.refresh(Request())

    def _gmail_service(self):
        self.ensure_one()
        from googleapiclient.discovery import build

        creds = self._gmail_credentials()
        self._gmail_refresh_credentials(creds)
        return build("gmail", "v1", credentials=creds, cache_discovery=False)

    def _gmail_resolve_sender_email(self, service):
        self.ensure_one()
        if self.gmail_email:
            return self.gmail_email.strip()
        profile = service.users().getProfile(userId="me").execute()
        return (profile.get("emailAddress") or "").strip()

    def action_gmail_refresh_profile(self):
        self.ensure_one()
        try:
            service = self._gmail_service()
            profile = service.users().getProfile(userId="me").execute()
            email = (profile.get("emailAddress") or "").strip()
            vals = {
                "last_sync_at": fields.Datetime.now(),
                "last_error": False,
                "state": "connected",
            }
            if email:
                vals["gmail_email"] = email
            self.write(vals)
            self.message_post(body=_("Gmail profile refreshed: %s") % (email or _("(no address)")))
        except Exception as e:
            _logger.exception("Gmail profile refresh failed for account %s", self.id)
            self.write(
                {
                    "state": "error",
                    "last_error": str(e),
                }
            )
            raise UserError(_("Could not refresh Gmail profile: %s") % e) from e
        return True

    # ── Phase D: token refresh helper ─────────────────────────────────────────

    def _gmail_fetch_access_token_direct(self, refresh_token):
        """Fetch a new Google access token using this account's own OAuth credentials.

        Called by ir_mail_server_ext / fetchmail_server_ext so that SMTP and IMAP
        token refreshes use per-account client_id/secret instead of the system-wide
        google_gmail_client_id ir.config_parameter.
        """
        self.ensure_one()
        response = requests.post(
            GMAIL_TOKEN_URI,
            data={
                "client_id": self.oauth_client_id.strip(),
                "client_secret": self.oauth_client_secret.strip(),
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            timeout=10,
        )
        if not response.ok:
            raise UserError(
                _("Could not refresh Gmail access token for %s: %s")
                % (self.name, response.text)
            )
        data = response.json()
        return data["access_token"], int(time.time()) + data.get("expires_in", 3600)

    # ── Phase D: provision outgoing + incoming mail servers ────────────────────

    def action_provision_mail_servers(self):
        """Create (or update) an ir.mail_server (SMTP) and a fetchmail.server (IMAP)
        from this account's stored OAuth credentials."""
        self.ensure_one()
        if self.state != "connected":
            raise UserError(_("Connect to Gmail first (state must be 'connected')."))
        if not self.refresh_token:
            raise UserError(_("No refresh token stored. Run 'Connect with Google' first."))
        if not self.gmail_email:
            raise UserError(_("Gmail address not set. Run 'Refresh profile' first."))

        self._provision_outgoing_server()
        self._provision_incoming_server()
        self.message_post(
            body=_(
                "Outgoing SMTP and incoming IMAP servers provisioned for %(email)s.",
                email=self.gmail_email,
            )
        )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Mail servers ready"),
                "message": _("SMTP + IMAP configured for %s.") % self.gmail_email,
                "type": "success",
                "sticky": False,
            },
        }

    def _provision_outgoing_server(self):
        self.ensure_one()
        vals = {
            "name": "Gmail — %s" % self.gmail_email,
            "smtp_host": "smtp.gmail.com",
            "smtp_port": 587,
            "smtp_encryption": "starttls",
            "smtp_authentication": "gmail",
            "smtp_user": self.gmail_email.strip(),
            "from_filter": self.gmail_email.strip(),
            "google_gmail_refresh_token": self.refresh_token,
            "gmail_connector_account_id": self.id,
            "active": True,
        }
        if self.outgoing_mail_server_id:
            self.outgoing_mail_server_id.sudo().write(vals)
            return self.outgoing_mail_server_id
        server = self.env["ir.mail_server"].sudo().create(vals)
        self.outgoing_mail_server_id = server
        return server

    def _provision_incoming_server(self):
        self.ensure_one()
        vals = {
            "name": "Gmail — %s" % self.gmail_email,
            "server": "imap.gmail.com",
            "port": 993,
            "is_ssl": True,
            "server_type": "gmail",
            "user": self.gmail_email.strip(),
            "google_gmail_refresh_token": self.refresh_token,
            "gmail_connector_account_id": self.id,
            "active": True,
            "state": "draft",
        }
        if self.incoming_mail_server_id:
            self.incoming_mail_server_id.sudo().write(vals)
            return self.incoming_mail_server_id
        # First-time provision: full INBOX backfill (read + unread), then you filter in Odoo.
        vals["gmail_imap_mailbox"] = "INBOX"
        vals["gmail_imap_fetch_scope"] = "all_in_mailbox"
        vals["gmail_allow_inbox_all"] = True
        server = self.env["fetchmail.server"].sudo().create(vals)
        self.incoming_mail_server_id = server
        return server

    def action_view_outgoing_server(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Outgoing mail server"),
            "res_model": "ir.mail_server",
            "res_id": self.outgoing_mail_server_id.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_view_incoming_server(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Incoming mail server"),
            "res_model": "fetchmail.server",
            "res_id": self.incoming_mail_server_id.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_open_inbox_check_wizard(self):
        """Open wizard: Gmail API vs CRM leads (same OAuth as this module)."""
        self.ensure_one()
        self.check_access("read")
        if not self.env.user.has_group("mail_gmail_connector.group_gmail_manager"):
            raise UserError(_("Only Gmail managers can run the inbox comparison."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Compare Gmail vs CRM leads"),
            "res_model": "mail.gmail.inbox.check.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_account_id": self.id},
        }

    def action_open_fetch_import_wizard(self):
        """Gmail search (API) then import RFC822 through the provisioned incoming server."""
        self.ensure_one()
        self.check_access("read")
        if not self.env.user.has_group("mail_gmail_connector.group_gmail_manager"):
            raise UserError(_("Only Gmail managers can search Gmail and import messages."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Search Gmail and import"),
            "res_model": "mail.gmail.fetch.import.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_account_id": self.id},
        }

    # ── Phase B: send test / refresh ──────────────────────────────────────────

    def action_gmail_send_test(self):
        self.ensure_one()
        try:
            service = self._gmail_service()
            to_addr = self._gmail_resolve_sender_email(service)
            if not to_addr:
                raise UserError(
                    _("No recipient address: set Gmail address on the account or use Refresh profile first.")
                )
            body = (
                _("This is an automated self-test from Odoo (mail_gmail_connector).\nAccount: %s\n")
                % self.name
            )
            msg = MIMEText(body, "plain", "utf-8")
            msg["to"] = to_addr
            msg["subject"] = f"[Odoo Gmail test] {self.name}"
            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
            sent = service.users().messages().send(userId="me", body={"raw": raw}).execute()
            mid = sent.get("id", "?")
            self.write(
                {
                    "last_sync_at": fields.Datetime.now(),
                    "last_error": False,
                    "state": "connected",
                }
            )
            self.message_post(
                body=_("Test email sent to %(addr)s (message id %(mid)s)") % {"addr": to_addr, "mid": mid}
            )
        except UserError:
            raise
        except Exception as e:
            _logger.exception("Gmail send test failed for account %s", self.id)
            self.write({"state": "error", "last_error": str(e)})
            raise UserError(_("Could not send test email: %s") % e) from e
        return True
