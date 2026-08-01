import base64
import datetime
import json
import logging
import re
import secrets
from urllib.parse import quote, urlencode

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)
# Bumped when OAuth/profile logic changes (helps confirm running code vs stale workers).
_CONNECTOR_REV = "19.0.2.8.0"

PERSONAL_PROFILE_URL_DEFAULT = "https://www.linkedin.com/in/sabry-youssef-56a878185/"


class LinkedinAccount(models.Model):
    _name = "linkedin.account"
    _description = "LinkedIn Account"

    name = fields.Char(required=True, default="LinkedIn Account")
    active = fields.Boolean(default=True)
    account_type = fields.Selection(
        [
            ("personal", "Personal (job branding)"),
            ("company", "Company page (marketing)"),
        ],
        string="Account type",
        required=True,
        index=True,
        help=(
            "Personal: posts as the connected member; job hunt + thought leadership only.\n"
            "Company: posts as the organization page; clinic/commercial marketing only.\n"
            "Never mix the two — validation blocks cross-posting."
        ),
    )
    profile_url = fields.Char(
        string="Profile / page URL",
        help="Personal LinkedIn profile URL, or company page URL for company accounts.",
    )

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
        string="Legacy fallback (disabled)",
        default=False,
        help=(
            "Deprecated. Personal accounts always post as the member; "
            "company accounts always post as the organization. Must stay False."
        ),
    )

    connected = fields.Boolean(compute="_compute_connected")

    post_count = fields.Integer(compute="_compute_counts")
    stream_post_count = fields.Integer(compute="_compute_counts")
    resume_count = fields.Integer(compute="_compute_counts")
    conversation_count = fields.Integer(compute="_compute_counts")
    application_count = fields.Integer(compute="_compute_counts")
    cv_version_count = fields.Integer(compute="_compute_counts")

    @api.constrains(
        "account_type",
        "linkedin_organization_id",
        "fallback_personal_post",
        "oauth_scopes",
    )
    def _check_account_type_isolation(self):
        for rec in self:
            if not rec.account_type:
                raise ValidationError(_("Account type is required (personal or company)."))
            if rec.fallback_personal_post:
                raise ValidationError(
                    _(
                        "fallback_personal_post is disabled. "
                        "Use account type Personal (member URN) or Company (organization URN)."
                    )
                )
            org = (rec.linkedin_organization_id or "").strip()
            if rec.account_type == "personal":
                if org:
                    raise ValidationError(
                        _(
                            "Personal accounts must not set a Company page ID. "
                            "Use a separate company account for PetSpot marketing."
                        )
                    )
                scopes = set(rec._normalize_oauth_scopes().split())
                if "w_organization_social" in scopes:
                    raise ValidationError(
                        _(
                            "Personal accounts must not request w_organization_social. "
                            "Use scopes: openid profile w_member_social"
                        )
                    )
            elif rec.account_type == "company":
                if not org:
                    raise ValidationError(
                        _("Company accounts require a Company page ID (e.g. 129944345).")
                    )

    @api.model_create_multi
    def create(self, vals_list):
        cleaned = []
        for vals in vals_list:
            v = dict(vals)
            if v.get("account_type") == "personal":
                v["fallback_personal_post"] = False
                v.setdefault("profile_url", PERSONAL_PROFILE_URL_DEFAULT)
                v["linkedin_organization_id"] = False
            elif v.get("account_type") == "company":
                v["fallback_personal_post"] = False
            cleaned.append(v)
        return super().create(cleaned)

    def write(self, vals):
        vals = dict(vals)
        if vals.get("fallback_personal_post"):
            raise ValidationError(
                _(
                    "fallback_personal_post is disabled. "
                    "Use account type Personal or Company — never PetSpot as personal fallback."
                )
            )
        becoming_personal = vals.get("account_type") == "personal"
        if becoming_personal:
            vals["linkedin_organization_id"] = False
            vals["fallback_personal_post"] = False
            vals.setdefault("profile_url", PERSONAL_PROFILE_URL_DEFAULT)
        elif "linkedin_organization_id" in vals and vals["linkedin_organization_id"]:
            for rec in self:
                atype = vals.get("account_type") or rec.account_type
                if atype == "personal":
                    raise ValidationError(
                        _("Cannot set Company page ID on a personal LinkedIn account.")
                    )
        return super().write(vals)

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
        App = self.env["linkedin.job.application"]
        Cv = self.env["linkedin.cv.version"]
        for rec in self:
            rec.post_count = Post.search_count([("account_id", "=", rec.id)])
            rec.stream_post_count = Feed.search_count([("account_id", "=", rec.id)])
            rec.resume_count = Resume.search_count([("account_id", "=", rec.id)])
            rec.conversation_count = Conv.search_count([("account_id", "=", rec.id)])
            rec.application_count = App.search_count([("account_id", "=", rec.id)])
            rec.cv_version_count = Cv.search_count([("account_id", "=", rec.id)])

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
        """Author URN: member for personal accounts, organization for company accounts."""
        self.ensure_one()
        if not self.access_token or not self.linkedin_member_urn:
            raise UserError(_("Connect the LinkedIn account first."))
        if self.account_type == "personal":
            return self.linkedin_member_urn
        if self.account_type == "company":
            urn = (self.linkedin_organization_urn or "").strip()
            if not urn:
                raise UserError(
                    _(
                        "Set Company page ID on this company account "
                        "(e.g. 129944345 from linkedin.com/company/129944345/)."
                    )
                )
            return urn
        raise UserError(_("Set Account type to Personal or Company before posting."))

    def _organization_post_error_hint(self, api_body):
        if self.account_type == "personal":
            return _(
                "LinkedIn rejected a personal profile post.\n\n"
                "Ensure scopes include w_member_social and reconnect.\n\n"
                "API response: %s"
            ) % (api_body or "")
        return _(
            "LinkedIn rejected a company page post.\n\n"
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
        if self.account_type == "personal":
            text = "Personal LinkedIn connector test post at %s." % ts
            ok_msg = _("Test post sent to your personal feed.")
        else:
            text = "PetSpot El Sahel — Odoo company page test post at %s." % ts
            ok_msg = _("Test post sent to the company page.")
        self._post_text(text)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("LinkedIn"),
                "message": ok_msg,
                "type": "success",
                "sticky": False,
            },
        }

    def action_verify_personal_connection(self):
        """UAT helper: report whether this personal account is connected for job hunt."""
        self.ensure_one()
        expected = (self.profile_url or PERSONAL_PROFILE_URL_DEFAULT).rstrip("/")
        lines = [
            "Account: %s" % self.name,
            "Type: %s" % (self.account_type or "(unset)"),
            "Profile URL: %s" % expected,
            "Connected: %s" % ("yes" if self.connected else "NO"),
            "Member URN: %s" % (self.linkedin_member_urn or "(none)"),
            "Org ID: %s" % (self.linkedin_organization_id or "(none)"),
            "Scopes: %s" % self._normalize_oauth_scopes(),
        ]
        if self.account_type != "personal":
            lines.append("RESULT: not a personal account — create/connect a separate personal record.")
            level = "warning"
        elif not self.connected:
            lines.append(
                "RESULT: personal account exists but is NOT connected. "
                "Use Connect with scopes: openid profile w_member_social "
                "(no w_organization_social)."
            )
            level = "warning"
        else:
            lines.append(
                "RESULT: personal account is connected. "
                "Confirm in LinkedIn that the OAuth user matches %s" % expected
            )
            level = "success"
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Personal LinkedIn verification"),
                "message": "\n".join(lines),
                "type": level,
                "sticky": True,
            },
        }

    @api.model
    def get_personal_account(self):
        """Return the (single) personal account or empty recordset."""
        return self.search([("account_type", "=", "personal"), ("active", "=", True)], limit=1)

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
