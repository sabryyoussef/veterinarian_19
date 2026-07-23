# -*- coding: utf-8 -*-
import logging
import os

from werkzeug.exceptions import BadRequest, Forbidden, HTTPException

from odoo import _, fields, http
from odoo.addons.google_gmail.controllers.main import GoogleGmailController
from odoo.exceptions import AccessError, UserError
from odoo.http import request

_logger = logging.getLogger(__name__)


def _web_base_url():
    base = request.env["ir.config_parameter"].sudo().get_param("web.base.url", "").rstrip("/")
    if not base:
        base = request.httprequest.url_root.rstrip("/")
    return base


def _oauth_redirect_uri():
    # Same /google_gmail/ prefix as core Odoo (see /google_gmail/confirm) so routing matches
    # the installed google_gmail controller chain — avoids website 404 on custom /web/... paths.
    return f"{_web_base_url()}/google_gmail/mail_connector_oauth/callback"


def _form_redirect_url(account_id):
    return f"{_web_base_url()}/odoo/mail.gmail.account/{account_id}"


class GoogleGmailControllerMailConnector(GoogleGmailController):
    """Extend core Gmail OAuth controller; routes register with the same merge as /google_gmail/confirm."""

    @http.route(
        "/google_gmail/mail_connector_oauth/start",
        type="http",
        auth="user",
        methods=["GET"],
        csrf=False,
        readonly=False,
    )
    def mail_connector_oauth_start(self, account_id=None, **kw):
        """Redirect to Google; never leak a bare 500 — log and redirect back to the account."""
        aid = None
        try:
            if not request.env.user.has_group("mail_gmail_connector.group_gmail_manager"):
                raise Forbidden()
            if not account_id:
                raise BadRequest("Missing account_id")
            try:
                aid = int(account_id)
            except (TypeError, ValueError) as e:
                raise BadRequest("Invalid account_id") from e

            account = request.env["mail.gmail.account"].browse(aid).exists()
            if not account:
                return request.not_found()
            account.check_access("write")

            if not (account.oauth_client_id and account.oauth_client_secret):
                account.write(
                    {
                        "state": "error",
                        "last_error": "Set OAuth Client ID and Client secret before connecting.",
                    }
                )
                return request.redirect(_form_redirect_url(account.id))

            account._gmail_ensure_libraries()
            from google_auth_oauthlib.flow import Flow

            redirect_uri = _oauth_redirect_uri()
            # Allow HTTP redirect URIs in non-production (localhost) environments.
            if redirect_uri.startswith("http://"):
                os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
            flow = Flow.from_client_config(
                account._gmail_oauth_web_client_config(redirect_uri),
                scopes=account._gmail_scope_list(),
                redirect_uri=redirect_uri,
                autogenerate_code_verifier=False,
            )
            authorization_url, state = flow.authorization_url(
                access_type="offline",
                prompt="consent",
            )
            request.session["mail_gmail_oauth_flow_state"] = state
            request.session["mail_gmail_oauth_account_id"] = aid
            return request.redirect(authorization_url, local=False)
        except (UserError, AccessError, HTTPException):
            raise
        except Exception as e:
            _logger.exception("mail_connector_oauth_start failed (account_id=%r)", account_id)
            if aid:
                try:
                    acc = request.env["mail.gmail.account"].browse(aid).exists()
                    if acc and acc.has_access("write"):
                        acc.write({"state": "error", "last_error": str(e)})
                        acc.message_post(
                            body=_("OAuth start failed: %s") % str(e),
                        )
                    return request.redirect(_form_redirect_url(aid))
                except Exception:
                    _logger.exception("mail_connector_oauth_start error handler failed")
            return request.redirect(_web_base_url() + "/odoo")

    @http.route(
        "/google_gmail/mail_connector_oauth/callback",
        type="http",
        auth="user",
        methods=["GET"],
        csrf=False,
        readonly=False,
    )
    def mail_connector_oauth_callback(self, **kw):
        try:
            return self._mail_connector_oauth_callback_impl(**kw)
        except (UserError, AccessError, HTTPException):
            raise
        except Exception:
            _logger.exception("mail_connector_oauth_callback failed")
            return request.redirect(_web_base_url() + "/odoo")

    def _mail_connector_oauth_callback_impl(self, **kw):
        if not request.env.user.has_group("mail_gmail_connector.group_gmail_manager"):
            raise Forbidden()

        if kw.get("error"):
            err = kw.get("error_description") or kw.get("error")
            aid = request.session.pop("mail_gmail_oauth_account_id", None)
            request.session.pop("mail_gmail_oauth_flow_state", None)
            if aid:
                acc = request.env["mail.gmail.account"].browse(aid).exists()
                if acc and acc.has_access("write"):
                    acc.write({"state": "error", "last_error": err})
                    acc.message_post(body=_("OAuth declined or failed: %s") % err)
            return request.redirect(_form_redirect_url(aid) if aid else _web_base_url() + "/odoo")

        state = request.session.pop("mail_gmail_oauth_flow_state", None)
        account_id = request.session.pop("mail_gmail_oauth_account_id", None)
        if not state or not account_id:
            raise BadRequest(
                str(
                    _(
                        "OAuth session expired or missing. Open the Gmail account and click "
                        "“Connect with Google” again."
                    )
                )
            )

        account = request.env["mail.gmail.account"].browse(account_id).exists()
        if not account:
            return request.not_found()
        account.check_access("write")

        redirect_uri = _oauth_redirect_uri()
        # Allow HTTP redirect URIs in non-production (localhost) environments.
        if redirect_uri.startswith("http://"):
            os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
        account._gmail_ensure_libraries()
        from google_auth_oauthlib.flow import Flow

        flow = Flow.from_client_config(
            account._gmail_oauth_web_client_config(redirect_uri),
            scopes=account._gmail_scope_list(),
            state=state,
            redirect_uri=redirect_uri,
            autogenerate_code_verifier=False,
        )
        try:
            # OAUTHLIB_RELAX_TOKEN_SCOPE makes requests-oauthlib log scope
            # changes instead of raising a Warning when Google returns extra
            # scopes (e.g. 'openid') or omits scopes already granted.
            os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"
            flow.fetch_token(authorization_response=request.httprequest.url)
        except Exception as e:
            _logger.exception("Gmail OAuth token exchange failed for account %s", account.id)
            account.write({"state": "error", "last_error": str(e)})
            account.message_post(body=_("OAuth token exchange failed: %s") % str(e))
            return request.redirect(_form_redirect_url(account.id))

        creds = flow.credentials
        vals = {
            "state": "connected",
            "last_error": False,
            "last_sync_at": fields.Datetime.now(),
        }
        if creds.refresh_token:
            vals["refresh_token"] = creds.refresh_token
        if creds.scopes:
            vals["scopes"] = " ".join(sorted(creds.scopes))

        account.write(vals)
        account.message_post(body=_("Gmail connected via browser OAuth (refresh token stored)."))
        return request.redirect(_form_redirect_url(account.id))

