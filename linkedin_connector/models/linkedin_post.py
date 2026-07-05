import base64
import logging
from datetime import datetime as dt, time as time_cls, timedelta
from urllib.parse import quote

import pytz
import requests
from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# LinkedIn REST API — use v2/ugcPosts (proven working with w_member_social)
_LI_V2 = "https://api.linkedin.com/v2"


class LinkedinPost(models.Model):
    _name = "linkedin.post"
    _description = "LinkedIn Post"
    _order = "scheduled_date desc, id desc"
    _rec_name = "message_preview"

    account_id = fields.Many2one(
        "linkedin.account", string="Account", required=True, ondelete="cascade", index=True
    )
    internal_title = fields.Char(
        string="Internal title",
        help="Optional label for scheduling (not sent to LinkedIn).",
        index=True,
    )
    message = fields.Text(string="Message", required=True)
    message_preview = fields.Char(
        string="Preview", compute="_compute_message_preview", store=True
    )
    image_ids = fields.Many2many(
        "ir.attachment",
        "linkedin_post_attachment_rel",
        "post_id",
        "attachment_id",
        string="Images",
        domain=[("mimetype", "like", "image/%")],
    )
    visibility = fields.Selection(
        [("PUBLIC", "Public"), ("CONNECTIONS", "Connections only")],
        default="PUBLIC",
        required=True,
    )
    post_method = fields.Selection(
        [("now", "Post Now"), ("scheduled", "Schedule")],
        default="now",
        required=True,
        string="Method",
    )
    scheduled_date = fields.Datetime(
        string="Scheduled Date",
        help="Set Method to “Schedule”, choose date and time here, then click the Schedule button in the header.",
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("scheduled", "Scheduled"),
            ("posting", "Posting…"),
            ("posted", "Posted"),
            ("failed", "Failed"),
        ],
        default="draft",
        required=True,
        index=True,
    )
    linkedin_post_urn = fields.Char(string="LinkedIn Post URN", copy=False, readonly=True)
    linkedin_post_url = fields.Char(
        string="LinkedIn URL", compute="_compute_linkedin_post_url", store=False
    )
    published_date = fields.Datetime(string="Published Date", copy=False, readonly=True)
    failure_reason = fields.Text(string="Failure Reason", copy=False, readonly=True)

    @api.depends("message")
    def _compute_message_preview(self):
        for rec in self:
            msg = (rec.message or "").replace("\n", " ")
            rec.message_preview = msg[:80] + ("…" if len(msg) > 80 else "")

    @api.depends("linkedin_post_urn")
    def _compute_linkedin_post_url(self):
        for rec in self:
            urn = (rec.linkedin_post_urn or "").strip()
            if urn:
                rec.linkedin_post_url = (
                    "https://www.linkedin.com/feed/update/%s/" % quote(urn, safe="")
                )
            else:
                rec.linkedin_post_url = ""

    # ------------------------------------------------------------------
    # ORM helpers
    # ------------------------------------------------------------------
    @api.constrains("post_method", "scheduled_date")
    def _check_scheduled_date(self):
        for rec in self:
            if rec.post_method == "scheduled" and not rec.scheduled_date:
                raise UserError(_("Set a Scheduled Date when using Schedule method."))

    def _li_headers(self):
        self.ensure_one()
        account = self.account_id
        if not account.access_token:
            raise UserError(_("LinkedIn account is not connected. Connect it first."))
        return {
            "Authorization": "Bearer %s" % account.access_token,
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0",
        }

    # ------------------------------------------------------------------
    # Core publish — uses v2/ugcPosts (proven, no version header needed)
    # ------------------------------------------------------------------
    def _attachment_binary(self, attachment):
        """Return raw bytes for an ir.attachment (image)."""
        data = attachment.raw
        if not data and attachment.datas:
            data = base64.b64decode(attachment.datas)
        if not data:
            raise UserError(_("Image attachment \"%s\" has no file data.") % (attachment.name or attachment.id))
        return data

    def _linkedin_register_upload_image(self, attachment):
        """
        Register an image with LinkedIn, upload bytes, return digital media asset URN.
        See: POST /v2/assets?action=registerUpload (feedshare-image recipe).
        """
        self.ensure_one()
        owner = self.account_id._get_post_author_urn()

        reg_payload = {
            "registerUploadRequest": {
                "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
                "owner": owner,
                "serviceRelationships": [
                    {
                        "relationshipType": "OWNER",
                        "identifier": "urn:li:userGeneratedContent",
                    }
                ],
            }
        }
        reg = requests.post(
            "%s/assets?action=registerUpload" % _LI_V2,
            headers=self._li_headers(),
            json=reg_payload,
            timeout=60,
        )
        if reg.status_code not in (200, 201):
            raise UserError(_("LinkedIn could not start image upload: %s") % (reg.text or reg.status_code))

        body = reg.json() if reg.content else {}
        val = body.get("value") or body
        mechanism = (val.get("uploadMechanism") or {}).get(
            "com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest", {}
        )
        upload_url = mechanism.get("uploadUrl")
        extra_headers = mechanism.get("headers") or {}
        asset = val.get("asset")
        if not upload_url or not asset:
            raise UserError(_("Unexpected LinkedIn registerUpload response: %s") % body)

        raw = self._attachment_binary(attachment)
        ctype = attachment.mimetype or "image/jpeg"
        put_headers = {"Content-Type": ctype}
        if isinstance(extra_headers, dict):
            put_headers.update({str(k): str(v) for k, v in extra_headers.items()})

        up = requests.put(upload_url, data=raw, headers=put_headers, timeout=120)
        if up.status_code not in (200, 201, 204):
            raise UserError(_("LinkedIn image upload failed: %s") % (up.text or up.status_code))

        return asset

    def _build_post_payload(self, media_asset_urns=None):
        self.ensure_one()
        author = self.account_id._get_post_author_urn()
        vis_map = {"PUBLIC": "PUBLIC", "CONNECTIONS": "CONNECTIONS"}
        media_asset_urns = media_asset_urns or []

        share_content = {
            "shareCommentary": {"text": self.message or ""},
        }
        if media_asset_urns:
            # Image post: uploaded asset URNs from registerUpload + PUT
            share_content["shareMediaCategory"] = "IMAGE"
            share_content["media"] = [
                {
                    "status": "READY",
                    "description": {"text": ""},
                    "media": urn,
                }
                for urn in media_asset_urns[:9]
            ]
        else:
            share_content["shareMediaCategory"] = "NONE"

        payload = {
            "author": author,
            "lifecycleState": "PUBLISHED",
            "specificContent": {"com.linkedin.ugc.ShareContent": share_content},
            "visibility": {
                "com.linkedin.ugc.MemberNetworkVisibility": vis_map.get(self.visibility, "PUBLIC")
            },
        }
        return payload

    def _do_publish(self):
        self.ensure_one()
        self.state = "posting"
        try:
            media_urns = []
            if self.image_ids:
                for att in self.image_ids:
                    media_urns.append(self._linkedin_register_upload_image(att))

            payload = self._build_post_payload(media_asset_urns=media_urns)
            resp = requests.post(
                "%s/ugcPosts" % _LI_V2,
                headers=self._li_headers(),
                json=payload,
                timeout=30,
            )
            if resp.status_code not in (200, 201):
                raise UserError(_("LinkedIn post failed: %s") % resp.text)
            # ugcPosts returns URN in x-restli-id header OR in the response body id field
            post_urn = (
                resp.headers.get("x-restli-id")
                or resp.headers.get("X-RestLi-Id")
                or resp.json().get("id")
                or ""
            )
            self.write({
                "state": "posted",
                "linkedin_post_urn": post_urn,
                "published_date": fields.Datetime.now(),
                "failure_reason": False,
            })
            _logger.info("linkedin.post %s published urn=%s", self.id, post_urn)
        except Exception as exc:
            self.write({"state": "failed", "failure_reason": str(exc)})
            raise

    # ------------------------------------------------------------------
    # Button actions
    # ------------------------------------------------------------------
    def action_post_now(self):
        for rec in self:
            rec._do_publish()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {"title": _("LinkedIn"), "message": _("Post published."), "type": "success"},
        }

    def action_schedule(self):
        for rec in self:
            if not rec.scheduled_date:
                raise UserError(_("Set a Scheduled Date first."))
            rec.state = "scheduled"
        return True

    def action_set_draft(self):
        for rec in self:
            if rec.state not in ("scheduled", "failed"):
                raise UserError(_("Only scheduled or failed posts can be reset to draft."))
            rec.state = "draft"
        return True

    def action_open_on_linkedin(self):
        self.ensure_one()
        if not self.linkedin_post_url:
            raise UserError(_("Post has not been published yet."))
        return {"type": "ir.actions.act_url", "url": self.linkedin_post_url, "target": "new"}

    # ------------------------------------------------------------------
    # Scheduled publishing cron
    # ------------------------------------------------------------------
    @api.model
    def _cron_publish_scheduled(self):
        due = self.search([
            ("state", "=", "scheduled"),
            ("scheduled_date", "<=", fields.Datetime.now()),
        ])
        _logger.info("linkedin.post cron: %d posts due", len(due))
        for post in due:
            try:
                post._do_publish()
                self.env.cr.commit()
            except Exception as exc:
                _logger.error("linkedin.post cron failed for id=%s: %s", post.id, exc)
                self.env.cr.rollback()

    @api.model
    def _odoo_tips_local_to_utc_naive(self, day, hour, minute):
        """Combine local calendar day + time using current user's tz; return naive UTC."""
        tzname = self.env.user.tz or "UTC"
        try:
            user_tz = pytz.timezone(tzname)
        except pytz.exceptions.UnknownTimeZoneError:
            user_tz = pytz.UTC
        local_dt = user_tz.localize(dt.combine(day, time_cls(hour, minute)))
        return local_dt.astimezone(pytz.UTC).replace(tzinfo=None)

    @api.model
    def _odoo_tips_slot_free(self, account, utc_naive):
        """True if no other post for this account uses the same minute slot."""
        margin = timedelta(minutes=1)
        return not self.search_count([
            ("account_id", "=", account.id),
            ("scheduled_date", "!=", False),
            ("scheduled_date", ">=", utc_naive - margin),
            ("scheduled_date", "<=", utc_naive + margin),
            ("state", "not in", ("posted", "failed")),
        ])

    @api.model
    def _odoo_tips_pick_time(self, account, day, prefer_morning, primary=None):
        """Prefer morning or evening local slots; optional primary (hour, minute) tried first."""
        if prefer_morning:
            candidates = [
                (10, 0), (9, 30), (10, 30), (11, 0), (9, 0), (11, 30),
                (14, 0), (15, 0), (16, 0),
            ]
        else:
            candidates = [
                (18, 0), (17, 30), (18, 30), (17, 0), (19, 0), (16, 30),
                (15, 30), (14, 30),
            ]
        if primary:
            candidates = [primary] + [c for c in candidates if c != primary]
        for hour, minute in candidates:
            utc_naive = self._odoo_tips_local_to_utc_naive(day, hour, minute)
            if self._odoo_tips_slot_free(account, utc_naive):
                return utc_naive
        return None

    @api.model
    def create_odoo_tips_schedule_batch(self, account_id=None, start_date=None):
        """Create 14 scheduled LinkedIn posts (2/day) with fixed copy from linkedin_odoo_tips_data.

        Uses the first linkedin.account if account_id is omitted.
        start_date defaults to today in the user's timezone.
        Skips tips whose internal_title already exists for that account.
        """
        from .linkedin_odoo_tips_data import ODOO_TIPS_POSTS

        Account = self.env["linkedin.account"].sudo()
        if account_id:
            account = Account.browse(account_id)
        else:
            account = Account.search([], limit=1)
        if not account:
            raise UserError(_("Create or connect a LinkedIn account first."))

        if start_date is None:
            start_date = fields.Date.context_today(self)

        created = self.env["linkedin.post"]

        for idx, item in enumerate(ODOO_TIPS_POSTS):
            if self.search_count([
                ("account_id", "=", account.id),
                ("internal_title", "=", item["internal_title"]),
            ]):
                continue

            current_day = start_date + timedelta(days=idx // 2)
            prefer_morning = idx % 2 == 0

            scheduled_utc = None
            for extra in range(21):
                try_day = current_day + timedelta(days=extra)
                scheduled_utc = self._odoo_tips_pick_time(account, try_day, prefer_morning)
                if scheduled_utc:
                    break
            if not scheduled_utc:
                raise UserError(_("Could not find a free schedule slot for %s") % item["internal_title"])

            post = self.create({
                "account_id": account.id,
                "internal_title": item["internal_title"],
                "message": item["message"],
                "post_method": "scheduled",
                "scheduled_date": scheduled_utc,
                "state": "scheduled",
                "visibility": "PUBLIC",
            })
            created |= post

        return created

    @api.model
    def schedule_bulk_pasted_posts(
        self,
        account,
        bodies,
        start_date,
        morning_h=10,
        morning_m=0,
        evening_h=18,
        evening_m=0,
        title_prefix="Scheduled paste",
        recurrence_mode="twice_daily",
        schedule_count=None,
    ):
        """Create scheduled linkedin.post records from pasted bodies.

        * ``twice_daily``: pairs posts on the same calendar day (morning / evening); one row
          per pasted block; ``schedule_count`` is ignored.
        * ``daily`` / ``weekly`` / ``monthly``: one post per step at the morning local time;
          ``schedule_count`` is how many posts to create; bodies rotate if there are fewer
          blocks than posts.

        :param account: linkedin.account record
        :param bodies: list of str
        :param start_date: date
        :param morning_h, morning_m, evening_h, evening_m: local wall-clock slots
        :param title_prefix: internal_title = prefix + zero-padded index
        :param recurrence_mode: twice_daily | daily | weekly | monthly
        :param schedule_count: used when recurrence_mode is not twice_daily (defaults to len(bodies))
        :returns: linkedin.post recordset
        """
        clean_bodies = [(message or "").strip() for message in bodies if (message or "").strip()]
        if not clean_bodies:
            raise UserError(_("No post bodies to schedule."))
        account.ensure_one()
        created = self.env["linkedin.post"]
        primary_am = (max(0, min(23, int(morning_h))), max(0, min(59, int(morning_m))))
        primary_pm = (max(0, min(23, int(evening_h))), max(0, min(59, int(evening_m))))
        mode = recurrence_mode or "twice_daily"

        def _create_one(seq, msg, current_day, prefer_morning, primary):
            scheduled_utc = None
            for extra in range(21):
                try_day = current_day + timedelta(days=extra)
                scheduled_utc = self._odoo_tips_pick_time(
                    account, try_day, prefer_morning, primary=primary
                )
                if scheduled_utc:
                    break
            if not scheduled_utc:
                raise UserError(
                    _("Could not find a free schedule slot for post %(n)d") % {"n": seq}
                )
            title = "%s %02d" % (title_prefix.strip() or "Scheduled paste", seq)
            return self.create({
                "account_id": account.id,
                "internal_title": title,
                "message": msg,
                "post_method": "scheduled",
                "scheduled_date": scheduled_utc,
                "state": "scheduled",
                "visibility": "PUBLIC",
            })

        if mode == "twice_daily":
            for idx, msg in enumerate(clean_bodies):
                seq = idx + 1
                day_off = idx // 2
                current_day = start_date + timedelta(days=day_off)
                prefer_morning = idx % 2 == 0
                primary = primary_am if prefer_morning else primary_pm
                created |= _create_one(seq, msg, current_day, prefer_morning, primary)
            return created

        n = int(schedule_count) if schedule_count is not None else len(clean_bodies)
        if n < 1:
            raise UserError(_("Set the number of posts to at least 1."))
        if n > 500:
            raise UserError(_("Too many posts at once (maximum 500)."))
        nb = len(clean_bodies)
        for idx in range(n):
            seq = idx + 1
            msg = clean_bodies[idx % nb]
            if mode == "daily":
                current_day = start_date + timedelta(days=idx)
            elif mode == "weekly":
                current_day = start_date + timedelta(weeks=idx)
            elif mode == "monthly":
                current_day = start_date + relativedelta(months=idx)
            else:
                raise UserError(_("Unknown recurrence mode: %s") % mode)
            created |= _create_one(seq, msg, current_day, True, primary_am)

        return created
