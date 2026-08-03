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
    max_submits_per_week = fields.Integer(default=15, tracking=True)
    max_submits_per_month = fields.Integer(default=20, tracking=True)
    min_minutes_between_submits = fields.Integer(default=30, tracking=True)
    company_cooldown_days = fields.Integer(default=14, tracking=True)

    # Dashboard KPIs (computed, personal account only)
    jobs_count = fields.Integer(compute="_compute_dashboard_kpis")
    applications_count = fields.Integer(compute="_compute_dashboard_kpis")
    attempts_count = fields.Integer(compute="_compute_dashboard_kpis")
    human_required_count = fields.Integer(compute="_compute_dashboard_kpis")
    submission_unknown_count = fields.Integer(compute="_compute_dashboard_kpis")
    applied_today_count = fields.Integer(compute="_compute_dashboard_kpis")
    remaining_daily_limit = fields.Integer(compute="_compute_dashboard_kpis")
    remaining_weekly_limit = fields.Integer(compute="_compute_dashboard_kpis")
    profile_id = fields.Many2one(
        "linkedin.candidate.profile",
        compute="_compute_dashboard_kpis",
        string="Application Profile",
    )
    ats_sources_checked = fields.Integer(compute="_compute_dashboard_kpis")
    new_direct_ats_jobs = fields.Integer(compute="_compute_dashboard_kpis")
    safe_canary_count = fields.Integer(compute="_compute_dashboard_kpis")
    last_discovery_run = fields.Char(compute="_compute_dashboard_kpis")
    next_discovery_run = fields.Char(compute="_compute_dashboard_kpis")

    @api.constrains("account_id")
    def _check_personal(self):
        for rec in self:
            if rec.account_id.account_type != "personal":
                raise ValidationError(_("Apply policy requires a personal account."))

    @api.constrains(
        "max_submits_per_day",
        "max_submits_per_week",
        "max_submits_per_month",
        "company_cooldown_days",
        "min_score",
        "min_minutes_between_submits",
    )
    def _check_limits(self):
        for rec in self:
            if rec.max_submits_per_day < 0 or rec.max_submits_per_month < 0:
                raise ValidationError(_("Submit caps cannot be negative."))
            if rec.max_submits_per_week < 0:
                raise ValidationError(_("Weekly submit cap cannot be negative."))
            if rec.company_cooldown_days < 0:
                raise ValidationError(_("Cooldown cannot be negative."))
            if rec.min_minutes_between_submits < 0:
                raise ValidationError(_("Spacing cannot be negative."))

    @api.depends(
        "account_id",
        "max_submits_per_day",
        "max_submits_per_week",
    )
    def _compute_dashboard_kpis(self):
        Job = self.env["linkedin.job"]
        App = self.env["linkedin.job.application"]
        Attempt = self.env["linkedin.apply.attempt"]
        Profile = self.env["linkedin.candidate.profile"]
        now = fields.Datetime.now()
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        from datetime import timedelta

        week_start = day_start - timedelta(days=day_start.weekday())
        for rec in self:
            aid = rec.account_id.id
            rec.jobs_count = Job.search_count([("account_id", "=", aid)])
            rec.applications_count = App.search_count([("account_id", "=", aid)])
            rec.attempts_count = Attempt.search_count([("account_id", "=", aid)])
            rec.human_required_count = App.search_count(
                [("account_id", "=", aid), ("state", "=", "human_required")]
            ) + Attempt.search_count(
                [("account_id", "=", aid), ("state", "=", "human_required")]
            )
            rec.submission_unknown_count = App.search_count(
                [("account_id", "=", aid), ("state", "=", "submission_unknown")]
            ) + Attempt.search_count(
                [("account_id", "=", aid), ("state", "=", "submission_unknown")]
            )
            applied_today = Attempt.search_count(
                [
                    ("account_id", "=", aid),
                    ("state", "in", ("submitted", "succeeded")),
                    ("create_date", ">=", fields.Datetime.to_string(day_start)),
                ]
            )
            rec.applied_today_count = applied_today
            week_count = Attempt.search_count(
                [
                    ("account_id", "=", aid),
                    ("state", "in", ("submitted", "succeeded")),
                    ("create_date", ">=", fields.Datetime.to_string(week_start)),
                ]
            )
            rec.remaining_daily_limit = max(0, (rec.max_submits_per_day or 0) - applied_today)
            rec.remaining_weekly_limit = max(0, (rec.max_submits_per_week or 0) - week_count)
            rec.profile_id = Profile.search(
                [("account_id", "=", aid), ("active", "=", True)], limit=1
            )
            ICP = self.env["ir.config_parameter"].sudo()
            import json

            stats_raw = ICP.get_param("linkedin_connector.ats_discovery_last_stats_json", "{}")
            try:
                stats = json.loads(stats_raw or "{}")
            except Exception:
                stats = {}
            rec.ats_sources_checked = int(stats.get("sources_checked") or 0)
            rec.new_direct_ats_jobs = int(stats.get("new_jobs") or 0)
            rec.safe_canary_count = Job.search_count(
                [
                    ("account_id", "=", aid),
                    ("discovery_class", "=", "safe_canary_candidate"),
                    ("is_duplicate", "=", False),
                ]
            )
            # Prefer live human_required from discovery class for KPI clarity
            rec.human_required_count = Job.search_count(
                [("account_id", "=", aid), ("discovery_class", "=", "human_required")]
            ) + App.search_count(
                [("account_id", "=", aid), ("state", "=", "human_required")]
            )
            rec.last_discovery_run = ICP.get_param(
                "linkedin_connector.ats_discovery_last_run", ""
            )
            rec.next_discovery_run = ICP.get_param(
                "linkedin_connector.ats_discovery_next_run", ""
            )

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
        from datetime import timedelta

        week_start = day_start - timedelta(days=day_start.weekday())
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if self.count_submits(day_start) >= self.max_submits_per_day:
            raise UserError(_("Daily submit cap reached (%s).") % self.max_submits_per_day)
        if self.count_submits(week_start) >= (self.max_submits_per_week or 15):
            raise UserError(_("Weekly submit cap reached (%s).") % self.max_submits_per_week)
        if self.count_submits(month_start) >= self.max_submits_per_month:
            raise UserError(_("Monthly submit cap reached (%s).") % self.max_submits_per_month)
        # Spacing between successful submits
        if self.min_minutes_between_submits:
            since = now - timedelta(minutes=self.min_minutes_between_submits)
            recent = self.count_submits(since)
            if recent:
                raise UserError(
                    _("Minimum spacing of %s minutes between submits not met.")
                    % self.min_minutes_between_submits
                )

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
            "max_submits_per_week": self.max_submits_per_week,
            "max_submits_per_month": self.max_submits_per_month,
            "min_minutes_between_submits": self.min_minutes_between_submits,
            "company_cooldown_days": self.company_cooldown_days,
            "applied_today": self.applied_today_count,
            "remaining_daily_limit": self.remaining_daily_limit,
            "remaining_weekly_limit": self.remaining_weekly_limit,
        }
