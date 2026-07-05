import logging

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

_LI_API = "https://api.linkedin.com/rest"
_LI_VERSION = "202410"


class LinkedinStreamPost(models.Model):
    _name = "linkedin.stream.post"
    _description = "LinkedIn Feed Post"
    _order = "published_date desc, id desc"
    _rec_name = "message_preview"

    account_id = fields.Many2one(
        "linkedin.account", string="Account", required=True, ondelete="cascade", index=True
    )
    post_urn = fields.Char(string="Post URN", index=True)
    author_name = fields.Char(string="Author")
    author_image_url = fields.Char(string="Author Photo URL")
    message = fields.Text(string="Content")
    message_preview = fields.Char(
        string="Preview", compute="_compute_preview", store=True
    )
    published_date = fields.Datetime(string="Published")
    post_link = fields.Char(string="LinkedIn Link")
    likes_count = fields.Integer(string="Likes", default=0)
    comments_count = fields.Integer(string="Comments", default=0)
    reposts_count = fields.Integer(string="Reposts", default=0)
    image_urls = fields.Text(string="Image URLs (JSON)")
    last_fetched = fields.Datetime(string="Last Fetched", default=fields.Datetime.now)

    @api.depends("message")
    def _compute_preview(self):
        for rec in self:
            msg = (rec.message or "").replace("\n", " ")
            rec.message_preview = msg[:80] + ("…" if len(msg) > 80 else "")

    def _li_headers(self, account):
        if not account.access_token:
            raise UserError(_("LinkedIn account is not connected."))
        return {
            "Authorization": "Bearer %s" % account.access_token,
            "LinkedIn-Version": _LI_VERSION,
            "X-Restli-Protocol-Version": "2.0.0",
        }

    # ------------------------------------------------------------------
    # Fetch feed for one account
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # API note:
    # Reading a member's own posts via LinkedIn API requires the
    # "Marketing Developer Platform" Partner Program and r_member_social scope.
    # With w_member_social + openid profile (consumer app), the read endpoints
    # (/rest/posts, /v2/ugcPosts, /v2/shares) all return 403 ACCESS_DENIED.
    # Feed posts here are synced from linkedin.post records created through Odoo.
    # ------------------------------------------------------------------

    def _sync_from_odoo_posts(self, account):
        """Mirror published linkedin.post records into the feed view."""
        posted = self.env["linkedin.post"].search([
            ("account_id", "=", account.id),
            ("state", "=", "posted"),
            ("linkedin_post_urn", "!=", False),
        ])
        new_count = 0
        for post in posted:
            existing = self.search([
                ("post_urn", "=", post.linkedin_post_urn),
                ("account_id", "=", account.id),
            ], limit=1)
            vals = {
                "account_id": account.id,
                "post_urn": post.linkedin_post_urn,
                "author_name": account.name,
                "message": post.message,
                "published_date": post.published_date,
                "post_link": "https://www.linkedin.com/feed/update/%s/" % post.linkedin_post_urn,
                "last_fetched": fields.Datetime.now(),
            }
            if existing:
                existing.write(vals)
            else:
                self.create(vals)
                new_count += 1
        return new_count

    def _fetch_for_account(self, account):
        """Sync feed for account. Tries LinkedIn API first; falls back to Odoo posts mirror."""
        if not account.linkedin_member_urn:
            _logger.warning("linkedin.stream.post: skip %s — no member URN", account.id)
            return 0

        # Attempt live fetch (requires Partner API / r_member_social — 403 for consumer apps)
        headers = self._li_headers(account)
        tried_api = False
        for url, params in [
            ("%s/posts" % _LI_API, {"q": "author", "author": account.linkedin_member_urn, "count": 50, "LinkedIn-Version": "202504"}),
            ("https://api.linkedin.com/v2/ugcPosts", {"q": "authors", "authors": "List(%s)" % account.linkedin_member_urn, "count": 50}),
        ]:
            h = dict(headers)
            if "LinkedIn-Version" in params:
                h["LinkedIn-Version"] = params.pop("LinkedIn-Version")
            resp = requests.get(url, headers=h, params=params, timeout=20)
            tried_api = True
            if resp.status_code == 200:
                items = resp.json().get("elements", [])
                new_count = 0
                for item in items:
                    urn = item.get("id") or item.get("urn") or item.get("ugcPostUrn") or ""
                    if not urn:
                        continue
                    existing = self.search([("post_urn", "=", urn), ("account_id", "=", account.id)], limit=1)
                    text = item.get("commentary") or (item.get("specificContent") or {}).get(
                        "com.linkedin.ugc.ShareContent", {}).get("shareCommentary", {}).get("text") or ""
                    ts = item.get("publishedAt") or item.get("firstPublishedAt") or 0
                    vals = {
                        "account_id": account.id,
                        "post_urn": urn,
                        "author_name": account.name,
                        "message": text,
                        "published_date": fields.Datetime.to_string(
                            __import__("datetime").datetime.utcfromtimestamp(int(ts) / 1000)
                        ) if ts else False,
                        "post_link": "https://www.linkedin.com/feed/update/%s/" % urn,
                        "last_fetched": fields.Datetime.now(),
                    }
                    if existing:
                        existing.write(vals)
                    else:
                        self.create(vals)
                        new_count += 1
                _logger.info("linkedin.stream.post: fetched %d items from API for account %s", new_count, account.id)
                return new_count
            _logger.info("linkedin.stream.post: %s HTTP %s for account %s", url, resp.status_code, account.id)

        # API not available — mirror from linkedin.post records
        count = self._sync_from_odoo_posts(account)
        _logger.info("linkedin.stream.post: mirrored %d Odoo-created posts for account %s", count, account.id)
        return count

    # ------------------------------------------------------------------
    # Button / cron
    # ------------------------------------------------------------------
    @api.model
    def action_refresh_all(self):
        accounts = self.env["linkedin.account"].search([
            ("access_token", "!=", False),
            ("linkedin_member_urn", "!=", False),
        ])
        total = 0
        for acc in accounts:
            try:
                total += self._fetch_for_account(acc)
                self.env.cr.commit()
            except Exception as exc:
                _logger.error("linkedin.stream.post refresh failed acc=%s: %s", acc.id, exc)
                self.env.cr.rollback()
        _logger.info("linkedin.stream.post done: %d items across %d accounts", total, len(accounts))
        return total

    @api.model
    def _cron_refresh_feed(self):
        self.action_refresh_all()

    def action_open_on_linkedin(self):
        self.ensure_one()
        if not self.post_link:
            raise UserError(_("No LinkedIn link available."))
        return {"type": "ir.actions.act_url", "url": self.post_link, "target": "new"}
