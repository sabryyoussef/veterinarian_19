import base64
import datetime
import json
import logging
import re
import secrets
from urllib.parse import quote, urlencode

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)
# Bumped when OAuth/profile logic changes (helps confirm running code vs stale workers).
_CONNECTOR_REV = "19.0.2.7.0"


class LinkedinAccount(models.Model):
    _name = "linkedin.account"
    _description = "LinkedIn Account"

    name = fields.Char(required=True, default="LinkedIn Account")
    active = fields.Boolean(default=True)

    oauth_public_base_url = fields.Char(
        string="Public base URL",
        help=(
            "HTTPS origin where Odoo is reachable (no path), e.g. https://odoo.example.com. "
            "Used for OAuth redirect_uri instead of web.base.url. Required when web.base.url is localhost."
        ),
    )
    oauth_scopes = fields.Char(
        string="OAuth scopes",
        default="openid profile w_member_social",
        help=(
            "Space-separated OAuth scopes for Connect.\n"
            "Start with: openid profile w_member_social\n"
            "After Community Management API is Approved, add: w_organization_social\n"
            "Requesting w_organization_social before approval causes unauthorized_scope_error."
        ),
    )
    client_id = fields.Char(required=True)
    client_secret = fields.Char(required=True)
    redirect_uri = fields.Char(
        compute="_compute_redirect_uri",
        readonly=False,
        store=False,
    )
    state_token = fields.Char(copy=False)

    access_token = fields.Char(copy=False)
    refresh_token = fields.Char(copy=False)
    token_expires_at = fields.Datetime(copy=False)
    linkedin_member_urn = fields.Char(copy=False)
    linkedin_organization_id = fields.Char(
        string="Company page ID",
        help="Numeric LinkedIn company id from the page URL, e.g. 129944345 for /company/129944345/",
    )
    linkedin_organization_urn = fields.Char(
        string="Company page URN",
        compute="_compute_linkedin_organization_urn",
        store=True,
    )
    fallback_personal_post = fields.Boolean(
        string="Allow personal feed if no company page ID",
        default=False,
        help="When company page ID is missing, post to the connected member profile instead.",
    )

    connected = fields.Boolean(compute="_compute_connected")

    post_count = fields.Integer(compute="_compute_counts")
    stream_post_count = fields.Integer(compute="_compute_counts")
    resume_count = fields.Integer(compute="_compute_counts")
    conversation_count = fields.Integer(compute="_compute_counts")

    @api.depends("linkedin_organization_id")
    def _compute_linkedin_organization_urn(self):
        for rec in self:
            oid = (rec.linkedin_organization_id or "").strip()
            rec.linkedin_organization_urn = (
                "urn:li:organization:%s" % oid if oid else False
            )

    @api.depends("access_token", "linkedin_member_urn")
    def _compute_connected(self):
        for rec in self:
            rec.connected = bool(rec.access_token and rec.linkedin_member_urn)

    def _compute_counts(self):
        Post = self.env["linkedin.post"]
        Feed = self.env["linkedin.stream.post"]
        Resume = self.env["linkedin.resume"]
        Conv = self.env["linkedin.conversation"]
        for rec in self:
            rec.post_count = Post.search_count([("account_id", "=", rec.id)])
            rec.stream_post_count = Feed.search_count([("account_id", "=", rec.id)])
            rec.resume_count = Resume.search_count([("account_id", "=", rec.id)])
            rec.conversation_count = Conv.search_count([("account_id", "=", rec.id)])

    def _oauth_base_url(self):
        self.ensure_one()
        raw = (self.oauth_public_base_url or "").strip().rstrip("/")
        if raw:
            return raw
        icp = self.env["ir.config_parameter"].sudo()
        raw = (icp.get_param("linkedin_connector.oauth_public_base_url") or "").strip().rstrip("/")
        if raw:
            return raw
        return (icp.get_param("web.base.url") or "").strip().rstrip("/")

    @api.depends("oauth_public_base_url")
    def _compute_redirect_uri(self):
        for rec in self:
            base = rec._oauth_base_url()
            if not base:
                rec.redirect_uri = ""
                continue
            # Multi-database: LinkedIn must redirect to a URL that selects the DB (no session cookie yet).
            dbname = rec.env.cr.dbname
            rec.redirect_uri = "%s/linkedin_connector/callback?db=%s" % (base, quote(dbname, safe=""))

    def _normalize_oauth_scopes(self):
        self.ensure_one()
        raw = (self.oauth_scopes or "").strip()
        if not raw:
            return "openid profile w_member_social"
        return re.sub(r"\s+", " ", raw)

    def _get_post_author_urn(self):
        """Author for API posts — company page only (not personal feed)."""
        self.ensure_one()
        if not self.access_token or not self.linkedin_member_urn:
            raise UserError(_("Connect the LinkedIn account first."))
        urn = (self.linkedin_organization_urn or "").strip()
        if not urn:
            if self.fallback_personal_post and self.linkedin_member_urn:
                return self.linkedin_member_urn
            raise UserError(
                _(
                    "Set Company page ID on this account (e.g. 129944345 from "
                    "linkedin.com/company/129944345/). Odoo posts to the company page only, "
                    "not your personal feed."
                )
            )
        return urn

    def _organization_post_error_hint(self, api_body):
        return _(
            "LinkedIn rejected a company page post (personal feed is disabled in this connector).\n\n"
            "Ensure your app has:\n"
            "  • Community Management API product (LinkedIn Developers → Products)\n"
            "  • Scope w_organization_social\n"
            "  • You are admin of the company page\n\n"
            "Then Disconnect → Connect again.\n\n"
            "API response: %s"
        ) % (api_body or "")

    def action_connect(self):
        self.ensure_one()
        if not self.redirect_uri:
            raise UserError(
                _("Set Public base URL (or system parameter linkedin_connector.oauth_public_base_url / web.base.url).")
            )
        self.state_token = secrets.token_urlsafe(32)
        scope = self._normalize_oauth_scopes()
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "state": self.state_token,
            "scope": scope,
        }
        query = urlencode(params)
        url = "https://www.linkedin.com/oauth/v2/authorization?%s" % query
        _logger.info("LinkedIn OAuth start redirect_uri=%s scopes=%s", self.redirect_uri, scope)
        # Callback runs in a new request; ensure state is visible immediately.
        self.env.cr.commit()
        return {"type": "ir.actions.act_url", "url": url, "target": "self"}

    def _exchange_code(self, code):
        self.ensure_one()
        payload = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }
        response = requests.post(
            "https://www.linkedin.com/oauth/v2/accessToken",
            data=payload,
            timeout=15,
        )
        if response.status_code != 200:
            raise UserError(_("LinkedIn token exchange failed: %s") % response.text)
        data = response.json()
        self.access_token = data.get("access_token")
        self.refresh_token = data.get("refresh_token") or self.refresh_token
        expires_in = int(data.get("expires_in", 0) or 0)
        if expires_in:
            self.token_expires_at = fields.Datetime.to_string(
                datetime.datetime.utcnow() + datetime.timedelta(seconds=expires_in)
            )
        # Fast path: OIDC id_token contains sub without an extra HTTP round-trip.
        id_token = data.get("id_token")
        if id_token and self._try_set_member_urn_from_id_token(id_token):
            _logger.info("linkedin_connector %s: member URN from OIDC id_token", _CONNECTOR_REV)

    def _try_set_member_urn_from_id_token(self, id_token):
        """Parse JWT payload (no signature verify) for OIDC sub after code exchange."""
        self.ensure_one()
        if not id_token or id_token.count(".") != 2:
            return False
        try:
            payload_b64 = id_token.split(".")[1]
            pad = "=" * (-len(payload_b64) % 4)
            payload = json.loads(base64.urlsafe_b64decode(payload_b64 + pad))
            sub = payload.get("sub")
            if not sub:
                return False
            self.linkedin_member_urn = (
                sub if sub.startswith("urn:li:person:") else "urn:li:person:%s" % sub
            )
            return True
        except Exception:
            _logger.debug("linkedin_connector %s: id_token parse failed", _CONNECTOR_REV, exc_info=True)
            return False

    def _person_urn_from_sub(self, sub):
        if not sub:
            return ""
        return sub if sub.startswith("urn:li:person:") else "urn:li:person:%s" % sub

    def _introspect_member_urn(self):
        """Resolve member sub via token introspection.

        Works for any valid 3-legged token including w_member_social-only tokens
        that cannot call /v2/me or /v2/userinfo. Uses client credentials.
        Returns (sub_or_None, http_status, body_snippet).
        """
        self.ensure_one()
        resp = requests.post(
            "https://www.linkedin.com/oauth/v2/introspectToken",
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "token": self.access_token,
            },
            timeout=15,
        )
        _logger.info("linkedin_connector %s: introspect HTTP %s body=%s",
                     _CONNECTOR_REV, resp.status_code, resp.text[:300])
        if resp.status_code != 200:
            return None, resp.status_code, resp.text[:500]
        data = resp.json()
        if not data.get("active"):
            return None, resp.status_code, "token not active: %s" % data
        sub = (
            data.get("sub")
            or data.get("authorized_person")
            or data.get("member_id")
            or data.get("user_id")
        )
        return sub, resp.status_code, resp.text[:500]

    def _scopes_include_openid(self):
        self.ensure_one()
        parts = set(self._normalize_oauth_scopes().split())
        return "openid" in parts

    def _member_resolution_help(self, intr_body=""):
        self.ensure_one()
        scopes = self._normalize_oauth_scopes()
        if self._scopes_include_openid():
            return _(
                "Token is valid but LinkedIn did not return a member id.\n\n"
                "In LinkedIn Developers → your app → Products, ensure BOTH are added:\n"
                "  • Sign In with LinkedIn using OpenID Connect\n"
                "  • Share on LinkedIn\n\n"
                "Then Disconnect → Connect again with scopes:\n"
                "  openid profile w_member_social\n\n"
                "introspectToken: %(body)s"
            ) % {"body": intr_body}
        return _(
            "Your token has only w_member_social — LinkedIn does not return a member id "
            "with that scope alone (userinfo/me return 403; introspect has no sub).\n\n"
            "Required fix:\n"
            "  1. LinkedIn Developers → your app → Products\n"
            "  2. Add: Sign In with LinkedIn using OpenID Connect\n"
            "  3. In Odoo set OAuth scopes to: openid profile w_member_social\n"
            "  4. Disconnect → Connect again\n\n"
            "See linkedin_connector/LINKEDIN_SETUP.md\n\n"
            "introspectToken: %(body)s"
        ) % {"body": intr_body}

    def _fetch_member_urn(self):
        self.ensure_one()
        if self.linkedin_member_urn:
            return
        bearer = {"Authorization": "Bearer %s" % self.access_token}
        _logger.info("linkedin_connector %s: resolving member URN — userinfo -> /v2/me -> introspect",
                     _CONNECTOR_REV)

        # 1. OIDC /v2/userinfo — requires openid + profile scopes on the token.
        ui = requests.get("https://api.linkedin.com/v2/userinfo", headers=bearer, timeout=15)
        _logger.info("linkedin_connector %s: userinfo HTTP %s", _CONNECTOR_REV, ui.status_code)
        if ui.status_code == 200:
            sub = ui.json().get("sub")
            urn = self._person_urn_from_sub(sub)
            if urn:
                _logger.info("linkedin_connector %s: URN via /v2/userinfo sub=%s", _CONNECTOR_REV, sub)
                self.linkedin_member_urn = urn
                return
            raise UserError(
                _("[%s] LinkedIn /v2/userinfo returned no sub: %s") % (_CONNECTOR_REV, ui.json())
            )

        # 2. Legacy /v2/me — requires r_liteprofile / profile; 403 for w_member_social-only tokens.
        headers_me = dict(bearer, **{"X-Restli-Protocol-Version": "2.0.0"})
        me_status, me_body = ui.status_code, ui.text or ""
        for params in ({"projection": "(id)"}, {}):
            r = requests.get(
                "https://api.linkedin.com/v2/me",
                headers=headers_me,
                params=params or None,
                timeout=15,
            )
            me_status, me_body = r.status_code, r.text or ""
            _logger.info("linkedin_connector %s: /v2/me HTTP %s params=%s", _CONNECTOR_REV, me_status, params)
            if r.status_code == 200:
                lid = r.json().get("id")
                if lid:
                    _logger.info("linkedin_connector %s: URN via /v2/me id=%s", _CONNECTOR_REV, lid)
                    self.linkedin_member_urn = "urn:li:person:%s" % lid
                    return

        # 3. Token introspection — works for w_member_social-only tokens; authenticated with client creds.
        sub, intr_status, intr_body = self._introspect_member_urn()
        if sub:
            urn = self._person_urn_from_sub(sub)
            if urn:
                _logger.info("linkedin_connector %s: URN via introspectToken sub=%s", _CONNECTOR_REV, sub)
                self.linkedin_member_urn = urn
                return

        raise UserError(
            _(
                "[%(rev)s] Could not resolve LinkedIn member id after trying:\n"
                "  - /v2/userinfo        HTTP %(ui_status)s\n"
                "  - /v2/me              HTTP %(me_status)s\n"
                "  - introspectToken     HTTP %(intr_status)s: %(intr_body)s\n\n"
                "%(help)s"
            ) % {
                "rev": _CONNECTOR_REV,
                "ui_status": ui.status_code,
                "me_status": me_status,
                "intr_status": intr_status,
                "intr_body": intr_body,
                "help": self._member_resolution_help(intr_body),
            }
        )

    def action_fetch_posts(self):
        """Sync feed posts for this account and return a notification."""
        self.ensure_one()
        if not self.access_token or not self.linkedin_member_urn:
            raise UserError(_("Connect the LinkedIn account first."))
        StreamPost = self.env["linkedin.stream.post"]
        count = StreamPost._fetch_for_account(self)
        total = StreamPost.search_count([("account_id", "=", self.id)])
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("LinkedIn Feed"),
                "message": _("%d new post(s) fetched. Total in feed: %d.") % (count, total),
                "type": "success" if count else "info",
                "sticky": False,
            },
        }

    def action_disconnect(self):
        for rec in self:
            rec.access_token = False
            rec.refresh_token = False
            rec.token_expires_at = False
            rec.linkedin_member_urn = False
            rec.state_token = False

    def action_test_post(self):
        self.ensure_one()
        ts = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        self._post_text(
            "PetSpot El Sahel — Odoo company page test post at %s." % ts
        )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("LinkedIn"),
                "message": _("Test post sent to the company page."),
                "type": "success",
                "sticky": False,
            },
        }

    def _post_text(self, text):
        self.ensure_one()
        author = self._get_post_author_urn()
        headers = {
            "Authorization": "Bearer %s" % self.access_token,
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0",
        }
        payload = {
            "author": author,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": text},
                    "shareMediaCategory": "NONE",
                }
            },
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
        }
        response = requests.post(
            "https://api.linkedin.com/v2/ugcPosts",
            json=payload,
            headers=headers,
            timeout=20,
        )
        if response.status_code not in (200, 201):
            raise UserError(self._organization_post_error_hint(response.text))
