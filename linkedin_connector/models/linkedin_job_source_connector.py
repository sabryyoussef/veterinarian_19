# -*- coding: utf-8 -*-
"""Reusable job-source connector registry and scheduler."""

from __future__ import annotations

import json
import logging
import random
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

_LOCK_KEY = 88220419  # advisory lock namespace for job-source scheduler


class LinkedinJobSourceConnector(models.Model):
    _name = "linkedin.job.source.connector"
    _description = "Job Source Connector"
    _order = "enabled desc, next_run_at asc, id"
    _inherit = ["mail.thread"]

    name = fields.Char(required=True, tracking=True)
    code = fields.Char(required=True, index=True, tracking=True)
    source_type = fields.Selection(
        [
            ("official_api", "Official API"),
            ("public_feed", "Public Feed"),
            ("public_ats", "Public ATS"),
            ("manual", "Manual Discovery"),
            ("email_alert", "Email Alert"),
            ("restricted", "Restricted"),
        ],
        required=True,
        default="public_feed",
        index=True,
    )
    adapter_key = fields.Char(required=True, index=True)
    base_url = fields.Char()
    api_key_param = fields.Char(
        help="ir.config_parameter key name holding the secret (never store the secret here)."
    )
    enabled = fields.Boolean(default=False, index=True, tracking=True)
    environment = fields.Selection(
        [("test", "TEST"), ("prod", "Production")],
        default="test",
        required=True,
        index=True,
    )
    fetch_interval_minutes = fields.Integer(default=1440)
    max_jobs_per_run = fields.Integer(default=25)
    daily_request_limit = fields.Integer(default=20)
    monthly_request_limit = fields.Integer(default=200)
    requests_used_day = fields.Integer(default=0)
    requests_used_month = fields.Integer(default=0)
    usage_day_key = fields.Char(copy=False)
    usage_month_key = fields.Char(copy=False)
    supported_countries = fields.Char(help="Comma-separated ISO country codes")
    keyword_set_json = fields.Text(
        default='["Odoo Developer","Senior Odoo","Odoo Technical Consultant"]'
    )
    keyword_set_id = fields.Char(
        help="Optional label for keyword set; keywords live in keyword_set_json."
    )
    last_success_at = fields.Datetime(tracking=True)
    last_error = fields.Char(tracking=True)
    rate_limit_until = fields.Datetime(index=True)
    cursor_json = fields.Text()
    trust_level = fields.Integer(default=50)
    compliance_class = fields.Selection(
        [
            ("APPROVED_API", "Approved API"),
            ("APPROVED_PUBLIC_FEED", "Approved Public Feed"),
            ("APPROVED_PUBLIC_ATS", "Approved Public ATS"),
            ("CONDITIONAL_PUBLIC_PAGE", "Conditional Public Page"),
            ("MANUAL_DISCOVERY_ONLY", "Manual Discovery Only"),
            ("REJECTED_AUTOMATION", "Rejected Automation"),
        ],
        default="APPROVED_PUBLIC_FEED",
        required=True,
    )
    compliance_notes = fields.Text()
    raw_archive_enabled = fields.Boolean(default=True)
    consecutive_failures = fields.Integer(default=0)
    auto_disable_after_failures = fields.Integer(default=5)
    next_run_at = fields.Datetime(index=True)
    last_http_status = fields.Integer()
    last_jobs_found = fields.Integer()
    board_token = fields.Char(
        help="ATS board token / site slug / company id used by public ATS adapters."
    )
    feed_url = fields.Char()
    ats_source_ids = fields.One2many(
        "linkedin.ats.source", "connector_id", string="Linked ATS sources"
    )
    health_json = fields.Text(copy=False)

    _sql_constraints = [
        (
            "linkedin_job_source_connector_code_env_uniq",
            "unique(code, environment)",
            "Connector code must be unique per environment.",
        )
    ]

    def action_run_now(self):
        for rec in self:
            self.env["linkedin.job.source.connector"].sudo()._run_connector(rec)
        return True

    def action_reset_failures(self):
        self.write({"consecutive_failures": 0, "last_error": False, "enabled": True})
        return True

    @api.model
    def _icp(self):
        return self.env["ir.config_parameter"].sudo()

    @api.model
    def _current_environment(self):
        """TEST DB → test; production DB → prod (override via ICP)."""
        forced = (self._icp().get_param("linkedin_connector.job_source_environment") or "").strip()
        if forced in ("test", "prod"):
            return forced
        db = self.env.cr.dbname or ""
        return "test" if db.endswith("_test") or "test" in db else "prod"

    @api.model
    def _global_caps_ok(self):
        icp = self._icp()
        day_cap = int(icp.get_param("linkedin_connector.job_discovery_max_requests_per_day", "80") or 80)
        month_cap = int(
            icp.get_param("linkedin_connector.job_discovery_max_requests_per_month", "1200") or 1200
        )
        usage = {}
        try:
            usage = json.loads(icp.get_param("linkedin_connector.job_discovery_usage_json", "{}") or "{}")
        except json.JSONDecodeError:
            usage = {}
        today = fields.Date.context_today(self)
        month = today.strftime("%Y-%m")
        day = fields.Date.to_string(today)
        if usage.get("day") != day:
            usage = {"day": day, "month": month, "day_count": 0, "month_count": 0}
        if usage.get("month") != month:
            usage["month"] = month
            usage["month_count"] = 0
        if usage.get("day_count", 0) >= day_cap or usage.get("month_count", 0) >= month_cap:
            return False, usage
        return True, usage

    @api.model
    def _bump_global_usage(self, usage):
        usage = dict(usage or {})
        usage["day_count"] = int(usage.get("day_count") or 0) + 1
        usage["month_count"] = int(usage.get("month_count") or 0) + 1
        self._icp().set_param("linkedin_connector.job_discovery_usage_json", json.dumps(usage))

    def _reset_usage_windows(self):
        today = fields.Date.context_today(self)
        day = fields.Date.to_string(today)
        month = today.strftime("%Y-%m")
        for rec in self:
            vals = {}
            if rec.usage_day_key != day:
                vals.update({"usage_day_key": day, "requests_used_day": 0})
            if rec.usage_month_key != month:
                vals.update({"usage_month_key": month, "requests_used_month": 0})
            if vals:
                rec.with_context(skip_job_source_mail=True).write(vals)

    def _quota_ok(self):
        self.ensure_one()
        self._reset_usage_windows()
        if self.requests_used_day >= self.daily_request_limit:
            return False
        if self.requests_used_month >= self.monthly_request_limit:
            return False
        if self.rate_limit_until and self.rate_limit_until > fields.Datetime.now():
            return False
        return True

    def _secret_value(self):
        self.ensure_one()
        if not self.api_key_param:
            return ""
        # Prefer environment-suffixed key when present
        icp = self._icp()
        env = self.environment or "test"
        keyed = f"{self.api_key_param}_{env}"
        val = icp.get_param(keyed) or icp.get_param(self.api_key_param) or ""
        return (val or "").strip()

    def _adapter_config(self):
        self.ensure_one()
        keywords = []
        try:
            keywords = json.loads(self.keyword_set_json or "[]")
        except json.JSONDecodeError:
            keywords = []
        if not isinstance(keywords, list):
            keywords = [str(keywords)]
        countries = [c.strip() for c in (self.supported_countries or "").split(",") if c.strip()]
        cfg = {
            "base_url": self.base_url or "",
            "api_key": self._secret_value(),
            "board_token": self.board_token or "",
            "feed_url": self.feed_url or "",
            "keywords": (keywords[0] if keywords else "Odoo Developer"),
            "keyword_list": keywords,
            "countries": countries,
            "country": countries[0] if countries else "",
            "max_jobs": self.max_jobs_per_run,
            "max_jobs_per_run": self.max_jobs_per_run,
            "environment": self.environment,
        }
        # Adzuna dual credentials
        icp = self._icp()
        cfg["app_id"] = (icp.get_param("linkedin_connector.adzuna_app_id") or "").strip()
        cfg["app_key"] = (
            (icp.get_param("linkedin_connector.adzuna_app_key") or "").strip()
            or cfg["api_key"]
        )
        return cfg

    def _schedule_next(self, *, backoff_minutes=None):
        self.ensure_one()
        base = backoff_minutes if backoff_minutes is not None else (self.fetch_interval_minutes or 1440)
        jitter = random.randint(0, min(7, max(1, base // 10)))
        nxt = fields.Datetime.now() + timedelta(minutes=base + jitter)
        self.with_context(skip_job_source_mail=True).write({"next_run_at": nxt})

    @api.model
    def _advisory_lock(self):
        self.env.cr.execute("SELECT pg_try_advisory_lock(%s)", (_LOCK_KEY,))
        row = self.env.cr.fetchone()
        return bool(row and row[0])

    @api.model
    def _advisory_unlock(self):
        self.env.cr.execute("SELECT pg_advisory_unlock(%s)", (_LOCK_KEY,))

    @api.model
    def _cron_scheduler(self):
        """Pick due connectors one-at-a-time; inactive until explicitly enabled."""
        if not self._advisory_lock():
            _logger.info("job.source.connector: scheduler lock busy; skip")
            return False
        try:
            live = (
                self._icp().get_param("linkedin_connector.live_job_search_enabled", "False") or "False"
            )
            if live.lower() not in ("1", "true", "yes"):
                _logger.info("job.source.connector: live_job_search_enabled=False; skip")
                return False
            env_name = self._current_environment()
            ok, usage = self._global_caps_ok()
            if not ok:
                _logger.warning("job.source.connector: global discovery caps reached")
                return False
            now = fields.Datetime.now()
            due = self.search(
                [
                    ("enabled", "=", True),
                    ("environment", "=", env_name),
                    "|",
                    ("next_run_at", "=", False),
                    ("next_run_at", "<=", now),
                    "|",
                    ("rate_limit_until", "=", False),
                    ("rate_limit_until", "<=", now),
                ],
                order="next_run_at asc, id asc",
                limit=1,
            )
            if not due:
                return False
            self._run_connector(due, usage=usage)
            return True
        finally:
            self._advisory_unlock()

    @api.model
    def _run_connector(self, connector, usage=None):
        from odoo.addons.linkedin_connector.services.job_sources.base import (
            AdapterError,
            ComplianceError,
            RateLimitError,
        )
        from odoo.addons.linkedin_connector.services.job_sources.registry import get_adapter
        from odoo.addons.linkedin_connector.services.job_sources.sanitize import (
            sanitize_payload_for_storage,
        )

        connector.ensure_one()
        if connector.compliance_class == "REJECTED_AUTOMATION":
            connector.write(
                {
                    "last_error": "rejected_automation",
                    "enabled": False,
                }
            )
            return {"error": "rejected_automation"}

        if not connector._quota_ok():
            connector._schedule_next()
            return {"error": "quota"}

        if usage is None:
            ok, usage = self._global_caps_ok()
            if not ok:
                return {"error": "global_quota"}

        checkpoint = {}
        try:
            checkpoint = json.loads(connector.cursor_json or "{}")
        except json.JSONDecodeError:
            checkpoint = {}

        stats = {"imported": 0, "duplicates": 0, "rejected": 0, "qualified": 0}
        try:
            adapter = get_adapter(connector, env=self.env, config=connector._adapter_config())
            if connector.source_type == "restricted" or connector.adapter_key in (
                "restricted",
                "linkedin",
                "indeed",
            ):
                raise ComplianceError("restricted_source_fetch_forbidden")

            # Public ATS without board_token: fan-out over linked/enabled ats.source rows
            raw_jobs = []
            result_meta = {}
            http_status = 200
            if (
                connector.source_type == "public_ats"
                and not (connector.board_token or "").strip()
                and connector.adapter_key
                in ("greenhouse", "lever", "ashby", "workable", "smartrecruiters", "recruitee")
            ):
                Ats = self.env["linkedin.ats.source"].sudo()
                boards = Ats.search(
                    [
                        ("enabled", "=", True),
                        ("ats_type", "=", connector.adapter_key),
                        "|",
                        ("connector_id", "=", connector.id),
                        ("connector_id", "=", False),
                    ],
                    limit=max(1, min(20, connector.max_jobs_per_run or 20)),
                )
                all_jobs = []
                for board in boards:
                    cfg = connector._adapter_config()
                    cfg["board_token"] = board.board_token or board.feed_url or ""
                    if not cfg["board_token"]:
                        continue
                    try:
                        ad = get_adapter(connector, env=self.env, config=cfg)
                        sub = ad.fetch_jobs(checkpoint)
                    except Exception as board_exc:  # noqa: BLE001 — per-board fail-closed
                        board.write(
                            {
                                "last_check_at": fields.Datetime.now(),
                                "last_error": str(board_exc)[:240],
                                "consecutive_failures": (board.consecutive_failures or 0) + 1,
                                "connector_id": connector.id,
                            }
                        )
                        continue
                    http_status = sub.http_status or http_status
                    for j in sub.jobs or []:
                        if isinstance(j, dict):
                            j = dict(j)
                            j["_board_token"] = cfg["board_token"]
                            all_jobs.append(j)
                    board.write(
                        {
                            "last_check_at": fields.Datetime.now(),
                            "last_http_status": sub.http_status or 0,
                            "last_jobs_found": len(sub.jobs or []),
                            "last_error": False,
                            "connector_id": connector.id,
                        }
                    )
                from odoo.addons.linkedin_connector.services.job_sources.base import FetchResult

                result = FetchResult(
                    jobs=all_jobs[: connector.max_jobs_per_run or 50],
                    checkpoint=checkpoint,
                    http_status=http_status,
                    meta={"boards": len(boards)},
                )
            else:
                result = adapter.fetch_jobs(checkpoint)
            connector.write(
                {
                    "requests_used_day": connector.requests_used_day + 1,
                    "requests_used_month": connector.requests_used_month + 1,
                    "last_http_status": result.http_status or 200,
                }
            )
            self._bump_global_usage(usage)

            # Raw archive policy
            self.env["linkedin.job.raw.payload"].sudo()._archive_fetch(
                connector=connector,
                result=result,
                sanitized=sanitize_payload_for_storage(result.raw_payload),
            )

            Pipeline = self.env["linkedin.job"].sudo()
            stats = Pipeline._ingest_normalized_jobs(
                connector=connector,
                raw_jobs=result.jobs,
                adapter=adapter,
            )

            new_cursor = result.checkpoint if result.checkpoint is not None else checkpoint
            if result.next_cursor:
                new_cursor = dict(new_cursor or {})
                new_cursor["cursor"] = result.next_cursor
            connector.write(
                {
                    "cursor_json": json.dumps(new_cursor or {}),
                    "last_success_at": fields.Datetime.now(),
                    "last_error": False,
                    "consecutive_failures": 0,
                    "last_jobs_found": result.count,
                    "health_json": json.dumps({"stats": stats, "at": fields.Datetime.to_string(fields.Datetime.now())}),
                }
            )
            connector._schedule_next()
            return stats
        except ComplianceError as exc:
            connector.write(
                {
                    "last_error": str(exc)[:240],
                    "enabled": False,
                    "consecutive_failures": connector.consecutive_failures + 1,
                }
            )
            connector._schedule_next(backoff_minutes=connector.fetch_interval_minutes)
            return {"error": "compliance"}
        except RateLimitError as exc:
            backoff = min(360, 15 * (2 ** min(connector.consecutive_failures, 5)))
            until = fields.Datetime.now() + timedelta(minutes=backoff)
            connector.write(
                {
                    "last_error": "rate_limit",
                    "rate_limit_until": until,
                    "consecutive_failures": connector.consecutive_failures + 1,
                }
            )
            connector._schedule_next(backoff_minutes=backoff)
            _logger.warning("job.source.connector %s rate limited: %s", connector.code, exc)
            return {"error": "rate_limit"}
        except AdapterError as exc:
            fails = connector.consecutive_failures + 1
            vals = {
                "last_error": str(exc)[:240],
                "consecutive_failures": fails,
            }
            if fails >= (connector.auto_disable_after_failures or 5):
                vals["enabled"] = False
                vals["last_error"] = (vals["last_error"] or "") + " [auto-disabled]"
            connector.write(vals)
            backoff = min(360, 10 * (2 ** min(fails, 5)))
            connector._schedule_next(backoff_minutes=backoff)
            return {"error": "adapter", "detail": str(exc)[:120]}
        except Exception as exc:  # noqa: BLE001
            _logger.exception("job.source.connector unexpected failure code=%s", connector.code)
            fails = connector.consecutive_failures + 1
            vals = {
                "last_error": ("unexpected:" + str(exc))[:240],
                "consecutive_failures": fails,
            }
            if fails >= (connector.auto_disable_after_failures or 5):
                vals["enabled"] = False
            connector.write(vals)
            connector._schedule_next(backoff_minutes=60)
            return {"error": "unexpected"}

    @api.model
    def _cron_raw_payload_cleanup(self):
        """Retention cleanup — inactive by default until TEST verification."""
        return self.env["linkedin.job.raw.payload"].sudo()._cron_cleanup()
