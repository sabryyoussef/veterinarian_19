# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class LinkedinApplyPolicy(models.Model):
    _name = "linkedin.apply.policy"
    _description = "Job Application Orchestrator Policy"
    _inherit = ["mail.thread"]

    name = fields.Char(required=True, default="Personal apply policy")
    active = fields.Boolean(default=True)
    account_id = fields.Many2one(
        "linkedin.account",
        string="Personal account",
        required=True,
        ondelete="cascade",
        domain="[('account_type', '=', 'personal')]",
        tracking=True,
    )
    # Global kill switch — when True, all orchestrator automation is blocked
    kill_switch = fields.Boolean(
        string="Kill switch (block all orchestration)",
        default=True,
        tracking=True,
        help="Default ON for safety. Turn OFF only for controlled UAT/live phases.",
    )
    auto_track_enabled = fields.Boolean(default=False, tracking=True)
    browser_submit_enabled = fields.Boolean(
        default=False,
        tracking=True,
        help="Must stay False until live canary approval.",
    )
    email_submit_enabled = fields.Boolean(default=False, tracking=True)
    allowed_platforms = fields.Char(
        string="Allowed platforms (comma-separated)",
        default="bebee,greenhouse,lever,company_ats,aggregator,unknown",
        help="linkedin is never auto-submitted; use manual task only.",
    )
    min_score = fields.Float(default=65.0, tracking=True)
    max_submits_per_day = fields.Integer(default=2, tracking=True)
    max_submits_per_month = fields.Integer(default=20, tracking=True)
    company_cooldown_days = fields.Integer(default=14, tracking=True)

    @api.constrains("account_id")
    def _check_personal(self):
        for rec in self:
            if rec.account_id.account_type != "personal":
                raise ValidationError(_("Apply policy requires a personal account."))

    @api.constrains(
        "max_submits_per_day",
        "max_submits_per_month",
        "company_cooldown_days",
        "min_score",
    )
    def _check_limits(self):
        for rec in self:
            if rec.max_submits_per_day < 0 or rec.max_submits_per_month < 0:
                raise ValidationError(_("Submit caps cannot be negative."))
            if rec.company_cooldown_days < 0:
                raise ValidationError(_("Cooldown cannot be negative."))

    @api.model
    def get_policy_for_account(self, account):
        if not account or account.account_type != "personal":
            raise UserError(_("Apply policy is only available for personal accounts."))
        policy = self.search([("account_id", "=", account.id), ("active", "=", True)], limit=1)
        if not policy:
            policy = self.create(
                {
                    "name": _("Policy for %s") % account.name,
                    "account_id": account.id,
                    "kill_switch": True,
                    "auto_track_enabled": False,
                    "browser_submit_enabled": False,
                    "email_submit_enabled": False,
                }
            )
        return policy

    def allowed_platform_set(self):
        self.ensure_one()
        return {
            p.strip().lower()
            for p in (self.allowed_platforms or "").split(",")
            if p.strip()
        }

    def assert_orchestration_allowed(self, platform=None, for_submit=False):
        self.ensure_one()
        if self.kill_switch:
            raise UserError(_("Orchestrator kill switch is ON."))
        if for_submit and not self.browser_submit_enabled and not self.email_submit_enabled:
            raise UserError(_("All submit channels are disabled by policy."))
        if platform:
            plat = (platform or "").lower()
            if plat == "linkedin":
                raise UserError(_("LinkedIn auto-submit is prohibited; use manual task only."))
            if plat not in self.allowed_platform_set():
                raise UserError(_("Platform %s is not allowed by policy.") % platform)

    def count_submits(self, since_dt):
        self.ensure_one()
        Attempt = self.env["linkedin.apply.attempt"]
        return Attempt.search_count(
            [
                ("account_id", "=", self.account_id.id),
                ("state", "in", ("submitted", "succeeded")),
                ("create_date", ">=", since_dt),
            ]
        )

    def assert_submit_caps(self):
        self.ensure_one()
        now = fields.Datetime.now()
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if self.count_submits(day_start) >= self.max_submits_per_day:
            raise UserError(_("Daily submit cap reached (%s).") % self.max_submits_per_day)
        if self.count_submits(month_start) >= self.max_submits_per_month:
            raise UserError(_("Monthly submit cap reached (%s).") % self.max_submits_per_month)

    def assert_company_cooldown(self, company_name):
        self.ensure_one()
        if not company_name:
            return
        from datetime import timedelta

        since = fields.Datetime.now() - timedelta(days=self.company_cooldown_days or 14)
        Attempt = self.env["linkedin.apply.attempt"]
        recent = Attempt.search_count(
            [
                ("account_id", "=", self.account_id.id),
                ("company_name", "=ilike", company_name.strip()),
                ("state", "in", ("submitted", "succeeded", "drafted")),
                ("create_date", ">=", fields.Datetime.to_string(since)),
            ]
        )
        if recent:
            raise UserError(
                _("Company cooldown active for %s (%s days).")
                % (company_name, self.company_cooldown_days)
            )

    def to_public_dict(self):
        self.ensure_one()
        return {
            "id": self.id,
            "kill_switch": self.kill_switch,
            "auto_track_enabled": self.auto_track_enabled,
            "browser_submit_enabled": self.browser_submit_enabled,
            "email_submit_enabled": self.email_submit_enabled,
            "allowed_platforms": sorted(self.allowed_platform_set()),
            "min_score": self.min_score,
            "max_submits_per_day": self.max_submits_per_day,
            "max_submits_per_month": self.max_submits_per_month,
            "company_cooldown_days": self.company_cooldown_days,
        }
