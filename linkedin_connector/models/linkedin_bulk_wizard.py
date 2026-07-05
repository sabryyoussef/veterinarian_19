# -*- coding: utf-8 -*-
import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class LinkedinPostBulkSchedule(models.Model):
    """Bulk schedule posts — separate file so it registers after linkedin.post."""

    _name = "linkedin.post.bulk.schedule"
    _description = "Bulk schedule LinkedIn posts from pasted text"

    account_id = fields.Many2one(
        "linkedin.account",
        string="LinkedIn account",
        required=True,
    )
    start_date = fields.Date(
        string="Start date",
        default=fields.Date.context_today,
        required=True,
        help="First calendar day for scheduling (first week / first month for weekly / monthly).",
    )
    recurrence_mode = fields.Selection(
        [
            ("twice_daily", "Twice per day"),
            ("daily", "Every day"),
            ("weekly", "Every week"),
            ("monthly", "Every month"),
        ],
        string="Repeat",
        default="twice_daily",
        required=True,
        help=(
            "Twice per day: uses morning and evening times, two pasted blocks per calendar day in order. "
            "Every day / week / month: one post per step at the morning time; set how many posts below."
        ),
    )
    schedule_count = fields.Integer(
        string="Number of posts",
        default=14,
        help="How many scheduled posts to create for Every day / week / month (text blocks repeat if needed).",
    )
    morning_hour = fields.Integer(string="Morning hour", default=10)
    morning_minute = fields.Integer(string="Morning minute", default=0)
    evening_hour = fields.Integer(string="Evening hour", default=18)
    evening_minute = fields.Integer(string="Evening minute", default=0)
    title_prefix = fields.Char(
        string="Internal title prefix",
        default="Scheduled paste",
        help="Stored in internal title as “Prefix 01”, “Prefix 02”, … (not sent to LinkedIn).",
    )
    post_text = fields.Text(
        string="Posts",
        required=True,
        help=(
            "Use one block per post (see “Repeat”). Twice per day: two blocks per calendar day. "
            "Every day / week / month: blocks are reused in order if you schedule more posts than blocks."
        ),
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if "account_id" in fields_list and not res.get("account_id"):
            acc = self.env["linkedin.account"].search([], limit=1)
            if acc:
                res["account_id"] = acc.id
        return res

    @api.constrains("morning_hour", "evening_hour")
    def _check_hours(self):
        for rec in self:
            for name, h in (("Morning hour", rec.morning_hour), ("Evening hour", rec.evening_hour)):
                if h < 0 or h > 23:
                    raise UserError(_("%s must be between 0 and 23.") % name)

    @api.constrains("morning_minute", "evening_minute")
    def _check_minutes(self):
        for rec in self:
            for name, m in (("Morning minute", rec.morning_minute), ("Evening minute", rec.evening_minute)):
                if m < 0 or m > 59:
                    raise UserError(_("%s must be between 0 and 59.") % name)

    @api.constrains("recurrence_mode", "schedule_count")
    def _check_schedule_count(self):
        for rec in self:
            if rec.recurrence_mode == "twice_daily":
                continue
            if not rec.schedule_count or rec.schedule_count < 1:
                raise UserError(_("Number of posts must be at least 1."))
            if rec.schedule_count > 500:
                raise UserError(_("Number of posts cannot exceed 500."))

    @staticmethod
    def _split_post_bodies(raw):
        raw = (raw or "").strip()
        if not raw:
            return []
        if not re.search(r"(?mi)^Post\s*\d+\s*$", raw):
            return [raw]
        bodies = []
        markers = list(re.finditer(r"(?mi)^Post\s*\d+\s*$", raw))
        for i, m in enumerate(markers):
            start = m.end()
            end = markers[i + 1].start() if i + 1 < len(markers) else len(raw)
            chunk = raw[start:end].strip()
            if chunk:
                bodies.append(chunk)
        return bodies

    def action_schedule(self):
        self.ensure_one()
        bodies = self._split_post_bodies(self.post_text)
        if not bodies:
            raise UserError(_("No post text found. Paste at least one post."))

        Post = self.env["linkedin.post"]
        count_kw = {}
        if self.recurrence_mode != "twice_daily":
            count_kw["schedule_count"] = self.schedule_count

        created = Post.schedule_bulk_pasted_posts(
            self.account_id,
            bodies,
            self.start_date,
            morning_h=self.morning_hour,
            morning_m=self.morning_minute,
            evening_h=self.evening_hour,
            evening_m=self.evening_minute,
            title_prefix=(self.title_prefix or "Scheduled paste").strip() or "Scheduled paste",
            recurrence_mode=self.recurrence_mode,
            **count_kw,
        )
        if not created:
            raise UserError(_("Nothing was created (empty bodies after parsing)."))

        return {
            "type": "ir.actions.act_window",
            "name": _("Scheduled posts"),
            "res_model": "linkedin.post",
            "view_mode": "list,form,calendar",
            "domain": [("id", "in", created.ids)],
            "context": {"create": False},
        }
