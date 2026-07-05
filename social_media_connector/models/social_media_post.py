# -*- coding: utf-8 -*-
import base64
import json
import logging
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .social_media_remote import (
    fetch_all_feed_posts,
    fetch_all_remote_posts,
    fetch_remote_sahel_posts,
    get_remote_client,
)

_logger = logging.getLogger(__name__)

MAX_IMAGE_BYTES = 5 * 1024 * 1024
CAMPAIGN_CONTACT_MARKER = "[PetSpot Contact]"
PRICE_LINE_RE = re.compile(
    r"(?i)^\s*(?:"
    r"from\s+\d[\d,.]*\s*(?:egp|le|جنيه|ج\.م)"
    r"|من\s+\d[\d,.]*\s*جنيه"
    r"|\d[\d,.]*\s*(?:egp|le)(?:\s*/\s*(?:hour|day))?"
    r"|\d[\d,.]*\s*جنيه(?:\s*/\s*(?:ساعة|يوم))?"
    r").*$"
)
PRICE_INLINE_RE = re.compile(
    r"(?i)\s*(?:·\s*)?"
    r"(?:from|من)\s+\d[\d,.]*(?:\s*[-–·/]\s*\d[\d,.]*)?\s*"
    r"(?:egp|le|جنيه|ج\.م)"
    r"(?:\s*[/+]\s*(?:hour|day|transport|ساعة|يوم|انتقالات))?"
)


class SocialMediaPost(models.Model):
    _name = "social.media.post"
    _description = "Local Facebook Post (push to Odoo Online)"
    _order = "scheduled_date desc, id desc"

    title = fields.Char(required=True, string="Internal Title")
    page_id = fields.Many2one(
        "social.media.page",
        string="Facebook Page",
        required=True,
        ondelete="restrict",
    )
    message = fields.Text(required=True)
    image_ids = fields.Many2many(
        "ir.attachment",
        "social_media_post_attachment_rel",
        "post_id",
        "attachment_id",
        string="Images",
    )
    post_method = fields.Selection(
        [("now", "Post Now"), ("scheduled", "Schedule")],
        default="scheduled",
        required=True,
    )
    scheduled_date = fields.Datetime(string="Scheduled Date")
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("ready", "Ready"),
            ("pushed", "Pushed"),
            ("failed", "Failed"),
        ],
        default="draft",
        required=True,
        tracking=True,
    )
    remote_post_id = fields.Integer(string="Remote Post ID", readonly=True, copy=False)
    remote_stream_post_id = fields.Integer(
        string="Remote Feed Post ID", readonly=True, copy=False, index=True
    )
    facebook_post_id = fields.Char(string="Facebook Post ID", readonly=True, copy=False)
    remote_state = fields.Char(string="Remote State", readonly=True)
    failure_reason = fields.Text(readonly=True)
    pushed_date = fields.Datetime(readonly=True)
    message_preview = fields.Char(compute="_compute_message_preview", store=True)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if "page_id" in fields_list and not res.get("page_id"):
            remote_id = int(
                self.env["ir.config_parameter"]
                .sudo()
                .get_param("social_media_connector.default_remote_account_id", "4")
                or 0
            )
            if remote_id:
                page = self.env["social.media.page"].search(
                    [("remote_account_id", "=", remote_id)], limit=1
                )
                if page:
                    res["page_id"] = page.id
        return res

    @api.depends("message")
    def _compute_message_preview(self):
        for rec in self:
            text = (rec.message or "").replace("\n", " ").strip()
            rec.message_preview = text[:80] + ("…" if len(text) > 80 else "")

    @api.constrains("post_method", "scheduled_date")
    def _check_scheduled_date(self):
        for rec in self:
            if rec.post_method == "scheduled" and not rec.scheduled_date:
                raise ValidationError(_("Scheduled posts require a scheduled date."))

    def _get_campaign_prefix(self):
        return (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("social_media_connector.campaign_prefix", "[PetSpot FB]")
            .strip()
        )

    def _build_remote_message(self):
        self.ensure_one()
        prefix = self._get_campaign_prefix()
        title = (self.title or "").strip()
        body = (self.message or "").strip()
        if prefix and title:
            return f"{prefix} {title}\n\n{body}"
        if title:
            return f"{title}\n\n{body}"
        return body

    def _validate_for_push(self):
        self.ensure_one()
        if not self.page_id:
            raise UserError(_("Select a Facebook page."))
        if not (self.message or "").strip():
            raise UserError(_("Post message is required."))
        if not self.image_ids:
            raise UserError(_("Attach at least one image."))
        if self.post_method == "scheduled" and not self.scheduled_date:
            raise UserError(_("Set a scheduled date or switch to Post Now."))
        if self.page_id and not self.page_id.has_token:
            raise UserError(
                _("Page “%s” has no Facebook token on remote. Re-fetch pages or reconnect on Online.")
                % self.page_id.name
            )
        if self.page_id and self.page_id.is_disconnected:
            raise UserError(
                _(
                    "Page “%s” is disconnected on Odoo Online. "
                    "Open Social Marketing on the remote instance and reconnect Facebook, "
                    "then Fetch Facebook Pages again."
                )
                % self.page_id.name
            )

    def action_mark_ready(self):
        for rec in self:
            rec._validate_for_push()
            rec.write({"state": "ready", "failure_reason": False})

    def action_reset_draft(self):
        self.write({"state": "draft", "failure_reason": False})

    def action_push_to_remote(self):
        return self._push_to_remote(force_now=False)

    def action_push_now(self):
        return self._push_to_remote(force_now=True)

    def action_repush(self):
        for rec in self:
            if rec.remote_post_id:
                rec._unlink_remote_post(rec.remote_post_id)
            rec.write({"remote_post_id": False, "remote_state": False, "state": "ready"})
        return self._push_to_remote(force_now=False)

    def action_push_selected(self):
        posts = self.filtered(lambda p: p.state == "ready")
        if not posts:
            raise UserError(_("No ready posts selected."))
        return posts._push_to_remote(force_now=False)

    def _unlink_remote_post(self, remote_id):
        client = get_remote_client(self.env)
        client.authenticate()
        rows = client.search_read(
            "social.post",
            [("id", "=", remote_id)],
            ["id", "state"],
            limit=1,
        )
        if rows and rows[0].get("state") in ("draft", "scheduled"):
            client.unlink("social.post", [remote_id])

    def _upload_attachments_to_remote(self, client):
        self.ensure_one()
        att_ids = []
        for att in self.image_ids:
            datas = att.datas
            if isinstance(datas, bytes):
                datas = datas.decode("ascii")
            if not datas:
                raise UserError(_("Image “%s” has no data.") % att.name)
            raw = base64.b64decode(datas)
            if len(raw) > MAX_IMAGE_BYTES:
                raise UserError(
                    _("Image “%s” is larger than 5 MB. Resize before pushing.") % att.name
                )
            remote_id = client.create(
                "ir.attachment",
                {
                    "name": att.name,
                    "type": "binary",
                    "datas": datas,
                    "mimetype": att.mimetype or "image/png",
                    "res_model": "social.post",
                },
            )
            att_ids.append(remote_id)
        return att_ids

    def _push_to_remote(self, force_now=False):
        success = 0
        errors = []
        for rec in self:
            if force_now:
                if rec.state == "pushed" and rec.remote_post_id:
                    errors.append(_("%s: already pushed (use Re-push)") % rec.title)
                    continue
            elif rec.state not in ("ready", "failed"):
                errors.append(_("%s: not in Ready state") % rec.title)
                continue
            if rec.remote_post_id and rec.state == "pushed":
                errors.append(_("%s: already pushed (use Re-push)") % rec.title)
                continue
            try:
                rec._validate_for_push()
                remote_id = rec._do_push(force_now=force_now)
                rec.write(
                    {
                        "remote_post_id": remote_id,
                        "state": "pushed",
                        "pushed_date": fields.Datetime.now(),
                        "failure_reason": False,
                    }
                )
                rec._refresh_remote_state()
                success += 1
            except Exception as exc:
                _logger.exception("Push failed for post %s", rec.id)
                rec.write({"state": "failed", "failure_reason": str(exc)})
                errors.append("%s: %s" % (rec.title, exc))

        if len(self) == 1:
            if errors:
                raise UserError(errors[0])
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Pushed"),
                    "message": _("Post pushed to remote Odoo (id=%s).") % self.remote_post_id,
                    "type": "success",
                },
            }

        msg = _("Pushed %s post(s).") % success
        if errors:
            msg += "\n" + "\n".join(errors)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Push Complete"),
                "message": msg,
                "type": "warning" if errors else "success",
                "sticky": bool(errors),
            },
        }

    def _do_push(self, force_now=False):
        self.ensure_one()
        client = get_remote_client(self.env)
        client.authenticate()

        if self.remote_post_id:
            self._unlink_remote_post(self.remote_post_id)

        remote_att_ids = self._upload_attachments_to_remote(client)
        account_id = self.page_id.remote_account_id
        message = self._build_remote_message()
        post_method = "now" if force_now else self.post_method
        vals = {
            "post_method": post_method,
            "account_ids": [(6, 0, [account_id])],
            "message": message,
            "image_ids": [(6, 0, remote_att_ids)],
        }
        if post_method == "scheduled":
            vals["scheduled_date"] = fields.Datetime.to_string(self.scheduled_date)

        remote_id = client.create("social.post", vals)
        if post_method == "now":
            client.execute("social.post", "action_post", [remote_id])
        else:
            client.execute("social.post", "action_schedule", [remote_id])
        return remote_id

    def _refresh_remote_state(self):
        for rec in self.filtered("remote_post_id"):
            try:
                client = get_remote_client(self.env)
                rows = client.search_read(
                    "social.post",
                    [("id", "=", rec.remote_post_id)],
                    ["state"],
                    limit=1,
                )
                if rows:
                    rec.remote_state = rows[0].get("state") or ""
            except Exception:
                pass

    @api.model
    def _cron_auto_push_ready(self):
        ICP = self.env["ir.config_parameter"].sudo()
        if ICP.get_param("social_media_connector.auto_push_enabled") != "True":
            return

        lead = int(ICP.get_param("social_media_connector.auto_push_lead_minutes", "15") or 15)
        deadline = fields.Datetime.add(fields.Datetime.now(), minutes=lead)
        posts = self.search(
            [
                ("state", "=", "ready"),
                ("post_method", "=", "scheduled"),
                ("scheduled_date", "<=", deadline),
                ("remote_post_id", "=", False),
            ]
        )
        for post in posts:
            try:
                post._push_to_remote(force_now=False)
            except Exception:
                _logger.exception("Auto-push failed for post %s", post.id)

    @api.model
    def _parse_remote_message(self, message):
        """Split remote social.post message into local title + body."""
        message = (message or "").strip()
        prefix = self._get_campaign_prefix()
        title = _("Imported post")
        body = message
        first_line = message.split("\n", 1)[0].strip()
        if prefix and first_line.startswith(prefix):
            remainder = first_line[len(prefix) :].strip()
            if " — " in remainder:
                title = remainder.split(" — ", 1)[1].strip()
            elif remainder:
                title = remainder
            parts = message.split("\n\n", 1)
            body = parts[1].strip() if len(parts) > 1 else ""
        elif "\n\n" in message:
            title = first_line[:120]
            body = message.split("\n\n", 1)[1].strip()
        return title, body

    def _download_remote_attachments(self, client, remote_image_ids):
        if not remote_image_ids:
            return self.env["ir.attachment"]
        rows = client.search_read(
            "ir.attachment",
            [("id", "in", list(remote_image_ids))],
            ["name", "datas", "mimetype"],
        )
        attachments = self.env["ir.attachment"]
        for row in rows:
            datas = row.get("datas") or ""
            if isinstance(datas, bytes):
                datas = datas.decode("ascii")
            attachments |= attachments.create(
                {
                    "name": row.get("name") or "image.png",
                    "type": "binary",
                    "datas": datas,
                    "mimetype": row.get("mimetype") or "image/png",
                    "res_model": "social.media.post",
                }
            )
        return attachments

    def _resolve_page_for_remote_account(self, remote_account_id):
        page = self.env["social.media.page"].search(
            [("remote_account_id", "=", remote_account_id)], limit=1
        )
        if page:
            return page
        remote_id = int(
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("social_media_connector.default_remote_account_id", "0")
            or 0
        )
        if remote_id:
            page = self.env["social.media.page"].search(
                [("remote_account_id", "=", remote_id)], limit=1
            )
        return page or self.env["social.media.page"].search([("active", "=", True)], limit=1)

    @api.model
    def _import_remote_post_rows(self, remote_posts, client):
        imported = self.browse()
        skipped = 0
        for row in remote_posts:
            remote_id = row["id"]
            if self.search([("remote_post_id", "=", remote_id)], limit=1):
                skipped += 1
                continue

            title, body = self._parse_remote_message(row.get("message"))
            remote_account_id = (row.get("account_ids") or [None])[0]
            page = self._resolve_page_for_remote_account(remote_account_id)
            if not page:
                raise UserError(
                    _("No local Facebook page for remote account %s. Fetch Facebook Pages first.")
                    % remote_account_id
                )

            images = self._download_remote_attachments(client, row.get("image_ids"))
            post_method = row.get("post_method") or "scheduled"
            remote_state = row.get("state") or ""
            imported |= self.create(
                {
                    "title": title,
                    "message": body,
                    "page_id": page.id,
                    "post_method": post_method,
                    "scheduled_date": row.get("scheduled_date") or False,
                    "image_ids": [(6, 0, images.ids)],
                    "remote_post_id": remote_id,
                    "remote_state": remote_state,
                    "state": "pushed" if remote_state == "posted" else "draft",
                    "pushed_date": row.get("published_date") or row.get("scheduled_date") or False,
                }
            )
        return imported, skipped

    @api.model
    def _m2o_id(self, value):
        if isinstance(value, (list, tuple)):
            return value[0]
        return value

    @api.model
    def _title_from_feed_row(self, row):
        text = (row.get("message") or row.get("link_title") or "").strip()
        if not text:
            return _("Feed post %s") % row.get("id")
        first_line = text.split("\n", 1)[0].strip()
        if len(first_line) > 100:
            return first_line[:97] + "…"
        return first_line

    @api.model
    def _feed_message_body(self, row):
        parts = []
        if row.get("message"):
            parts.append(row["message"].strip())
        if row.get("link_title"):
            parts.append(row["link_title"].strip())
        if row.get("link_description"):
            parts.append(row["link_description"].strip())
        if row.get("link_image_url") and not row.get("stream_post_image_ids"):
            parts.append(row["link_image_url"])
        return "\n\n".join(parts) if parts else _("Imported from Facebook feed.")

    @api.model
    def _get_remote_account_token(self, client, account_id, cache):
        if account_id in cache:
            return cache[account_id]
        rows = client.search_read(
            "social.account",
            [("id", "=", account_id)],
            ["facebook_access_token"],
            limit=1,
        )
        cache[account_id] = rows[0].get("facebook_access_token") if rows else ""
        return cache[account_id]

    @api.model
    def _download_feed_image(self, facebook_post_id, access_token):
        Attachment = self.env["ir.attachment"]
        if not facebook_post_id or not access_token:
            return Attachment
        ctx = ssl.create_default_context()
        api_url = (
            f"https://graph.facebook.com/v17.0/{facebook_post_id}"
            f"?fields=full_picture&access_token={urllib.parse.quote(access_token)}"
        )
        try:
            with urllib.request.urlopen(
                urllib.request.Request(api_url), context=ctx, timeout=60
            ) as resp:
                payload = json.loads(resp.read().decode())
        except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
            _logger.warning("Graph API image lookup failed for %s: %s", facebook_post_id, exc)
            return Attachment

        picture_url = payload.get("full_picture")
        if not picture_url:
            return Attachment
        try:
            with urllib.request.urlopen(
                urllib.request.Request(picture_url, headers={"User-Agent": "Mozilla/5.0"}),
                context=ctx,
                timeout=60,
            ) as resp:
                raw = resp.read()
        except urllib.error.URLError as exc:
            _logger.warning("Image download failed for %s: %s", facebook_post_id, exc)
            return Attachment

        if len(raw) > MAX_IMAGE_BYTES:
            _logger.warning("Feed image too large for %s (%s bytes)", facebook_post_id, len(raw))
            return Attachment

        mimetype = resp.headers.get("Content-Type", "image/jpeg").split(";")[0]
        ext = "jpg" if "jpeg" in mimetype or "jpg" in mimetype else "png"
        return Attachment.create(
            {
                "name": f"feed_{facebook_post_id.replace('/', '_')}.{ext}",
                "type": "binary",
                "datas": base64.b64encode(raw).decode("ascii"),
                "mimetype": mimetype,
                "res_model": "social.media.post",
            }
        )

    @api.model
    def _import_feed_post_rows(self, feed_posts, client):
        imported = self.browse()
        skipped = 0
        token_cache = {}
        for row in feed_posts:
            stream_id = row["id"]
            if self.search([("remote_stream_post_id", "=", stream_id)], limit=1):
                skipped += 1
                continue

            account_id = self._m2o_id(row.get("account_id"))
            page = self._resolve_page_for_remote_account(account_id)
            if not page:
                skipped += 1
                continue

            title = self._title_from_feed_row(row)
            if self.search(
                [("title", "=", title), ("remote_stream_post_id", "=", False)], limit=1
            ):
                title = f"{title} (#{stream_id})"

            token = self._get_remote_account_token(client, account_id, token_cache)
            images = self._download_feed_image(row.get("facebook_post_id"), token)
            published = row.get("published_date") or False

            imported |= self.create(
                {
                    "title": title,
                    "message": self._feed_message_body(row),
                    "page_id": page.id,
                    "post_method": "now",
                    "scheduled_date": published,
                    "image_ids": [(6, 0, images.ids)] if images else False,
                    "remote_stream_post_id": stream_id,
                    "facebook_post_id": row.get("facebook_post_id") or False,
                    "remote_state": "posted",
                    "state": "pushed",
                    "pushed_date": published,
                }
            )
        return imported, skipped

    @api.model
    def import_feed_posts_from_remote(self, account_ids=None):
        """Import Facebook feed posts (social.stream.post) from Odoo Online."""
        client = get_remote_client(self.env)
        feed_posts = fetch_all_feed_posts(client, account_ids)
        if not feed_posts:
            raise UserError(_("No Facebook feed posts found on Odoo Online."))
        imported, skipped = self._import_feed_post_rows(feed_posts, client)
        return self._import_action_result(imported, skipped, _("feed post(s)"))

    def _import_action_result(self, imported, skipped, label):
        msg = _("Imported %s %s.") % (len(imported), label)
        if skipped:
            msg += _(" Skipped %s already present.") % skipped
        if imported:
            return {
                "type": "ir.actions.act_window",
                "name": _("Imported Posts"),
                "res_model": "social.media.post",
                "view_mode": "list,form",
                "domain": [("id", "in", imported.ids)],
                "target": "current",
            }
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Import Complete"),
                "message": msg or _("Nothing new to import."),
                "type": "info",
            },
        }

    @api.model
    def import_all_posts_from_remote(self):
        """Pull all social.post records from Odoo Online with images."""
        client = get_remote_client(self.env)
        prefix = self._get_campaign_prefix()
        remote_posts = fetch_all_remote_posts(client, prefix)
        if not remote_posts:
            raise UserError(_("No posts found on Odoo Online."))
        imported, skipped = self._import_remote_post_rows(remote_posts, client)
        return self._import_action_result(imported, skipped, _("post(s) from Online"))

    @api.model
    def import_sahel_posts_from_remote(self):
        """Pull Sahel social.post records from Odoo Online with images."""
        client = get_remote_client(self.env)
        remote_posts = fetch_remote_sahel_posts(client)
        if not remote_posts:
            raise UserError(
                _("No Sahel posts found on Odoo Online (search: message contains “Sahel” or “الساحل”).")
            )
        imported, skipped = self._import_remote_post_rows(remote_posts, client)
        return self._import_action_result(imported, skipped, _("Sahel post(s)"))

    def _module_root(self):
        return Path(__file__).resolve().parents[1]

    def _attachment_from_image_path(self, rel_path):
        """Load image file or reuse an existing attachment with the same filename."""
        rel_path = (rel_path or "").strip()
        if not rel_path:
            return self.env["ir.attachment"]
        full = self._module_root() / rel_path
        name = Path(rel_path).name
        Attachment = self.env["ir.attachment"]
        if full.is_file():
            datas = base64.b64encode(full.read_bytes()).decode("ascii")
            mimetype = "image/png" if name.endswith(".png") else "image/jpeg"
            return Attachment.create(
                {
                    "name": name,
                    "type": "binary",
                    "datas": datas,
                    "mimetype": mimetype,
                    "res_model": "social.media.post",
                }
            )
        existing = Attachment.search(
            [("name", "=", name), ("res_model", "=", "social.media.post")],
            limit=1,
        )
        if existing:
            return existing
        linked = self.search([("image_ids", "!=", False)], limit=1).image_ids[:1]
        return linked

    @api.model
    def import_posts_from_json(self):
        """Import campaign posts from data/posts.json (fills gaps not on Online)."""
        data_file = self._module_root() / "data" / "posts.json"
        if not data_file.is_file():
            raise UserError(_("Missing %s") % data_file)

        with data_file.open(encoding="utf-8") as fh:
            data = json.load(fh)

        posts = data.get("posts", [])
        defaults = data.get("defaults", {})
        default_image = defaults.get("image", "assets/images/petspot-opening-hero.png")
        page = self._resolve_page_for_remote_account(
            int(
                self.env["ir.config_parameter"]
                .sudo()
                .get_param("social_media_connector.default_remote_account_id", "4")
                or 4
            )
        )
        if not page:
            raise UserError(_("Fetch Facebook Pages first, then set a default page in Settings."))

        imported = self.browse()
        skipped = 0
        interval = int(defaults.get("interval_minutes", 60) or 60)
        base_schedule = fields.Datetime.now() + timedelta(hours=1)
        index = 0
        for post in posts:
            title = (post.get("topic") or "").strip()
            if not title:
                continue
            if self.search([("title", "=", title)], limit=1):
                skipped += 1
                continue

            image_rel = post.get("image") or default_image
            image = self._attachment_from_image_path(image_rel)
            if not image:
                raise UserError(
                    _("No image for “%s”. Import from Online first or add %s.")
                    % (title, image_rel)
                )

            if post.get("scheduled_at"):
                scheduled_date = post["scheduled_at"]
            else:
                scheduled_date = base_schedule + timedelta(minutes=interval * index)
            index += 1

            imported |= self.create(
                {
                    "title": title,
                    "message": (post.get("message") or "").strip(),
                    "page_id": page.id,
                    "post_method": "scheduled",
                    "scheduled_date": scheduled_date,
                    "image_ids": [(6, 0, image.ids)],
                    "state": "draft",
                }
            )
        return imported, skipped

    @api.model
    def import_all_posts(self):
        """Fetch feed + scheduled Online posts, then fill gaps from posts.json."""
        client = get_remote_client(self.env)

        imported_feed, skipped_feed = self._import_feed_post_rows(
            fetch_all_feed_posts(client), client
        )

        prefix = self._get_campaign_prefix()
        imported_remote, skipped_remote = self._import_remote_post_rows(
            fetch_all_remote_posts(client, prefix), client
        )

        imported_json, skipped_json = self.import_posts_from_json()
        all_imported = imported_feed | imported_remote | imported_json
        skipped = skipped_feed + skipped_remote + skipped_json
        if not all_imported and skipped:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Import Complete"),
                    "message": _("All posts already imported (%s skipped).") % skipped,
                    "type": "info",
                },
            }
        return self._import_action_result(
            all_imported,
            skipped,
            _("post(s) (feeds + Online + posts.json)"),
        )

    def action_import_sahel_from_remote(self):
        return self.import_sahel_posts_from_remote()

    def action_import_all_from_remote(self):
        return self.import_all_posts()

    @api.model
    def _get_campaign_contact_config(self):
        ICP = self.env["ir.config_parameter"].sudo()
        whatsapp = ICP.get_param("social_media_connector.campaign_whatsapp", "01000059085")
        wa_digits = re.sub(r"\D", "", whatsapp or "")
        if wa_digits.startswith("0"):
            wa_digits = "20" + wa_digits[1:]
        elif not wa_digits.startswith("20"):
            wa_digits = "20" + wa_digits
        return {
            "whatsapp": whatsapp,
            "whatsapp_link": f"https://wa.me/{wa_digits}" if wa_digits else "",
            "call_center": ICP.get_param(
                "social_media_connector.campaign_call_center", "01201568888"
            ),
            "website": ICP.get_param(
                "social_media_connector.campaign_website", "https://petspot.odoo.com"
            ),
            "facebook_url": ICP.get_param(
                "social_media_connector.campaign_facebook_url",
                "https://www.facebook.com/1378190768902001",
            ),
            "linkedin_url": ICP.get_param(
                "social_media_connector.campaign_linkedin_url",
                "https://www.linkedin.com/company/129944345",
            ),
            "location_en": ICP.get_param(
                "social_media_connector.campaign_location_en",
                "Beside Amwaj 1 gate, Main Road, Sidi Abdel Rahman, North Coast",
            ),
            "location_ar": ICP.get_param(
                "social_media_connector.campaign_location_ar",
                "بجوار بوابة أمواج 1، الطريق الرئيسي، سيدي عبد الرحمن، الساحل الشمالي",
            ),
            "maps_url": ICP.get_param(
                "social_media_connector.campaign_maps_url",
                "https://maps.app.goo.gl/AaHup6NEFodZEs7S7",
            ),
            "interval": int(
                ICP.get_param("social_media_connector.campaign_schedule_interval", "60") or 60
            ),
            "timezone": ICP.get_param(
                "social_media_connector.campaign_schedule_timezone", "Africa/Cairo"
            ),
            "window_start_hour": int(
                ICP.get_param("social_media_connector.campaign_schedule_start_hour", "13") or 13
            ),
            "window_end_hour": int(
                ICP.get_param("social_media_connector.campaign_schedule_end_hour", "3") or 3
            ),
            "start_date": ICP.get_param(
                "social_media_connector.campaign_schedule_start_date", ""
            ),
        }

    @api.model
    def _local_now(self, tz_name):
        utc_now = fields.Datetime.now().replace(tzinfo=ZoneInfo("UTC"))
        return utc_now.astimezone(ZoneInfo(tz_name))

    @api.model
    def _campaign_window_bounds(self, day, cfg, tz):
        start_local = datetime.combine(
            day, time(cfg["window_start_hour"], 0), tzinfo=tz
        )
        end_local = datetime.combine(
            day + timedelta(days=1), time(cfg["window_end_hour"], 0), tzinfo=tz
        )
        return start_local, end_local

    @api.model
    def _next_campaign_start_day(self, cfg):
        tz = ZoneInfo(cfg["timezone"])
        if cfg.get("start_date"):
            return fields.Date.from_string(cfg["start_date"])
        local_now = self._local_now(cfg["timezone"])
        today_start, _today_end = self._campaign_window_bounds(local_now.date(), cfg, tz)
        if local_now < today_start:
            return local_now.date()
        return local_now.date() + timedelta(days=1)

    @api.model
    def _compute_campaign_schedule_datetimes(self, count):
        if count <= 0:
            return []
        cfg = self._get_campaign_contact_config()
        tz = ZoneInfo(cfg["timezone"])
        interval = max(int(cfg["interval"] or 60), 1)
        day = self._next_campaign_start_day(cfg)
        slots = []
        while len(slots) < count:
            start_local, end_local = self._campaign_window_bounds(day, cfg, tz)
            current = start_local
            while current <= end_local and len(slots) < count:
                slots.append(
                    current.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
                )
                current += timedelta(minutes=interval)
            day += timedelta(days=1)
        return slots

    @api.model
    def _strip_price_mentions(self, message):
        if not message:
            return message or ""
        body = message
        footer = ""
        if CAMPAIGN_CONTACT_MARKER in body:
            body, _, footer = body.partition(CAMPAIGN_CONTACT_MARKER)
            footer = CAMPAIGN_CONTACT_MARKER + footer

        lines = []
        for line in body.splitlines():
            if PRICE_LINE_RE.match(line.strip()):
                continue
            cleaned = PRICE_INLINE_RE.sub("", line)
            cleaned = re.sub(r"\s*·\s*·", " · ", cleaned)
            cleaned = cleaned.strip(" ·")
            if cleaned.strip():
                lines.append(cleaned)

        result = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
        return f"{result}{footer}" if footer else result

    @api.model
    def _normalize_location_mentions(self, message):
        if not message:
            return message or ""
        cfg = self._get_campaign_contact_config()
        body = message
        footer = ""
        if CAMPAIGN_CONTACT_MARKER in body:
            body, _, footer = body.partition(CAMPAIGN_CONTACT_MARKER)
            footer = CAMPAIGN_CONTACT_MARKER + footer

        replacements = (
            (
                r"عيادتنا البيطرية الموثوقة\s*\*{0,2}موجودة داخل مول سكاي كورت،?\s*أمام أمواج\s*[-–]\s*الساحل الشمالي\.?\*{0,2}",
                f"عيادتنا البيطرية الموثوقة **{cfg['location_ar']}**",
            ),
            (
                r"📍\s*مول سكاي كورت،?\s*أمام(?:\s*بوابة)?\s*أمواج",
                f"📍 {cfg['location_ar']}",
            ),
            (
                r"📍\s*Sky Court Mall,?\s*in front of Amwaj",
                f"📍 {cfg['location_en']}",
            ),
            (
                r"📍\s*Sky Court Mall،?\s*أمام\s*Amwaj",
                f"📍 {cfg['location_ar']}",
            ),
            (r"(?i)inside\s+sky\s+court\s+mall[^.\n]*", cfg["location_en"]),
            (r"#عيادة_بيطرية_سكاي_كورت", "#عيادة_بيطرية_الساحل"),
            (r"(?i)(?:\\#|#)عيادة\\?_بيطرية\\?_سكاي\\?_كورت", "#عيادة_بيطرية_الساحل"),
            (r"(?i)#sky_court[^#\s]*", "#PetSpot_El_Sahel"),
        )
        for pattern, repl in replacements:
            body = re.sub(pattern, repl, body)

        body = re.sub(r"https://share\.google/[^\s\)\]`]+", cfg["maps_url"], body)
        body = re.sub(r"https://external[^\s\)\]`]+", "", body)
        body = re.sub(r"^Pet Spot Clinic ·.*$", "", body, flags=re.M)
        body = re.sub(r"\n{3,}", "\n\n", body).strip()
        return f"{body}{footer}" if footer else body

    @api.model
    def _strip_campaign_footer(self, message):
        if CAMPAIGN_CONTACT_MARKER not in (message or ""):
            return (message or "").rstrip()
        return (message or "").split(CAMPAIGN_CONTACT_MARKER)[0].rstrip()

    @api.model
    def _apply_campaign_footer(self, message):
        body = self._normalize_location_mentions(
            self._strip_price_mentions(self._strip_campaign_footer(message))
        )
        return body + self._build_campaign_footer()

    @api.model
    def _build_campaign_footer(self):
        """Plain-text footer without https:// links so Odoo link-tracker won't
        replace petspot/facebook/maps URLs with deebvet.com/r/... short links."""
        cfg = self._get_campaign_contact_config()
        website = (cfg.get("website") or "").replace("https://", "").replace("http://", "")
        return (
            f"\n\n---\n"
            f"📞 Call: {cfg['call_center']}\n"
            f"💬 WhatsApp: {cfg['whatsapp']}\n"
            f"🌐 {website}\n"
            f"📘 Facebook: بيت الدواء البيطري -pet spot\n"
            f"📍 {cfg['location_en']}\n"
            f"🗺️ Google Maps: PetSpot Amwaj 1 gate\n\n"
            f"---\n"
            f"📞 اتصل: {cfg['call_center']}\n"
            f"💬 واتساب: {cfg['whatsapp']}\n"
            f"🌐 {website}\n"
            f"📘 فيسبوك: بيت الدواء البيطري -pet spot\n"
            f"📍 {cfg['location_ar']}\n"
            f"🗺️ خرائط جوجل: بجوار بوابة أمواج 1"
        )

    @api.model
    def _normalize_message_key(self, message):
        return re.sub(r"\s+", " ", (message or "").strip().lower())[:400]

    @api.model
    def _select_campaign_candidates(self):
        posts = self.search([("image_ids", "!=", False)], order="id desc")
        groups = {}
        for post in posts:
            key = self._normalize_message_key(post.message)
            if not key:
                continue
            existing = groups.get(key)
            if not existing or post.id > existing.id:
                groups[key] = post
        return self.browse([p.id for p in groups.values()])

    @api.model
    def prepare_campaign_reposts(self):
        """Dedupe fetched posts with images, append contact footer, reset to draft."""
        candidates = self._select_campaign_candidates()
        if not candidates:
            raise UserError(_("No posts with images found. Run Fetch All Posts first."))

        page = self._resolve_page_for_remote_account(
            int(
                self.env["ir.config_parameter"]
                .sudo()
                .get_param("social_media_connector.default_remote_account_id", "4")
                or 4
            )
        )
        if not page:
            raise UserError(_("Set default Facebook page in Settings first."))

        schedule_slots = self._compute_campaign_schedule_datetimes(len(candidates))
        prepared = self.browse()

        for index, post in enumerate(sorted(candidates, key=lambda p: p.id)):
            message = self._apply_campaign_footer(post.message or "")

            post.write(
                {
                    "message": message,
                    "page_id": page.id,
                    "state": "draft",
                    "post_method": "scheduled",
                    "scheduled_date": schedule_slots[index],
                    "remote_post_id": False,
                    "remote_stream_post_id": False,
                    "facebook_post_id": False,
                    "remote_state": False,
                    "failure_reason": False,
                    "pushed_date": False,
                }
            )
            prepared |= post

        return {
            "type": "ir.actions.act_window",
            "name": _("Campaign Draft Posts"),
            "res_model": "social.media.post",
            "view_mode": "list,form",
            "domain": [("id", "in", prepared.ids)],
            "target": "current",
        }

    def action_prepare_campaign_reposts(self):
        return self.prepare_campaign_reposts()

    @api.model
    def scrape_facebook_gallery_to_website(self, max_photos=200, fill_slots=True):
        """Download page photos from Facebook Graph API into website/assets/gallery."""
        from pathlib import Path

        from .facebook_gallery_scraper import scrape_facebook_gallery
        from .social_media_remote import get_remote_client

        module_root = Path(__file__).resolve().parents[1]
        remote_account_id = int(
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("social_media_connector.default_remote_account_id", "4")
            or 4
        )
        page = self._resolve_page_for_remote_account(remote_account_id)
        if not page or not page.facebook_page_id:
            raise UserError(
                _("Facebook page not linked. Run Fetch Facebook Pages first.")
            )

        try:
            result = scrape_facebook_gallery(
                get_remote_client(self.env),
                page_facebook_id=page.facebook_page_id,
                remote_account_id=remote_account_id,
                module_root=module_root,
                max_photos=max_photos,
                fill_slots=fill_slots,
            )
        except RuntimeError as exc:
            raise UserError(str(exc)) from exc

        slot_note = ""
        if result.get("slots_filled"):
            slot_note = _(" Homepage slots: %s.") % ", ".join(
                result["slots_filled"].keys()
            )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Facebook Gallery"),
                "message": _(
                    "Downloaded %(count)s photo(s) from %(page)s to %(dir)s.%(slots)s "
                    "Run website deploy to publish."
                )
                % {
                    "count": result["downloaded"],
                    "page": result["page_name"],
                    "dir": result["gallery_dir"],
                    "slots": slot_note,
                },
                "type": "success",
                "sticky": True,
            },
        }

    def action_scrape_facebook_gallery(self):
        return self.scrape_facebook_gallery_to_website()
