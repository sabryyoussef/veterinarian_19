# -*- coding: utf-8 -*-
import json
import logging
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class LinkedinAtsSource(models.Model):
    _name = "linkedin.ats.source"
    _description = "Direct ATS Employer Registry"
    _order = "enabled desc, last_check_at desc, id"

    name = fields.Char(required=True)
    ats_type = fields.Selection(
        [
            ("greenhouse", "Greenhouse"),
            ("lever", "Lever"),
            ("ashby", "Ashby"),
            ("workable", "Workable"),
            ("company_ats", "Employer career site"),
            ("jsearch", "JSearch"),
        ],
        required=True,
        index=True,
    )
    board_token = fields.Char(
        string="Board / site token",
        help="Greenhouse board token, Lever site slug, Ashby board, Workable account, or career index URL.",
    )
    company = fields.Char()
    region = fields.Char(help="egypt|uae|gulf|remote|europe|global")
    feed_url = fields.Char(string="Optional feed URL")
    enabled = fields.Boolean(default=True, index=True)
    last_check_at = fields.Datetime()
    last_http_status = fields.Integer()
    last_error = fields.Char()
    last_jobs_found = fields.Integer()
    consecutive_failures = fields.Integer(default=0)
    notes = fields.Text()

    def action_run_now(self):
        self.env["linkedin.ats.source"].sudo().run_discovery_cycle(source_ids=self.ids)
        return True

    @api.model
    def _personal_account(self):
        Account = self.env["linkedin.account"]
        personal = Account.browse(2).exists()
        if personal and personal.account_type == "personal":
            return personal
        personal = Account.get_personal_account()
        if not personal or personal.account_type != "personal" or personal.id == 1:
            raise UserError(_("Direct ATS discovery requires personal account id=2."))
        return personal

    @api.model
    def run_discovery_cycle(self, source_ids=None, try_canary=True):
        """Fetch public ATS feeds → import/score for account 2 → preflight classify.

        Does not require live_submit_enabled. Never writes company account id=1.
        """
        from odoo.addons.linkedin_connector.services import ats_feeds
        from odoo.addons.linkedin_connector.services.ats_preflight import classify_preflight
        from odoo.addons.linkedin_connector.services.platform_classifier import (
            classify_apply_url,
        )

        personal = self._personal_account()
        if personal.id == 1:
            raise UserError(_("Refusing discovery write to company account."))

        domain = [("enabled", "=", True)]
        if source_ids:
            domain.append(("id", "in", list(source_ids)))
        sources = self.search(domain)
        Job = self.env["linkedin.job"].sudo()
        stats = {
            "sources_checked": 0,
            "new_jobs": 0,
            "safe_canary": 0,
            "human_required": 0,
            "ineligible": 0,
            "unsupported_ats": 0,
            "errors": 0,
        }
        now = fields.Datetime.now()

        for src in sources:
            stats["sources_checked"] += 1
            status = 0
            jobs = []
            err = ""
            try:
                if src.ats_type == "greenhouse":
                    status, jobs = ats_feeds.fetch_greenhouse_jobs(src.board_token)
                elif src.ats_type == "lever":
                    status, jobs = ats_feeds.fetch_lever_jobs(src.board_token)
                elif src.ats_type == "ashby":
                    status, jobs = ats_feeds.fetch_ashby_jobs(src.board_token)
                elif src.ats_type == "workable":
                    if src.feed_url:
                        status, jobs = ats_feeds.fetch_workable_xml(src.feed_url)
                    else:
                        status, jobs = ats_feeds.fetch_workable_widget(src.board_token)
                elif src.ats_type == "company_ats":
                    status, jobs = ats_feeds.fetch_company_career_links(
                        src.feed_url or src.board_token
                    )
                elif src.ats_type == "jsearch":
                    # Discovery cycle does not burn JSearch quota; daily cron owns that.
                    status, jobs = 204, []
                else:
                    status, jobs = 0, []
            except Exception as exc:  # noqa: BLE001 — fail closed per source
                err = str(exc)[:240]
                status = 0
                jobs = []
                stats["errors"] += 1
                _logger.exception("ATS source %s failed", src.id)

            enriched = []
            for item in jobs[:30]:
                if item.get("needs_detail_fetch") and item.get("apply_url"):
                    apply_url = item.get("apply_url") or ""
                    detail_url = apply_url
                    if "/jobs/apply/" in apply_url:
                        detail_url = apply_url.replace("/jobs/apply/", "/jobs/")
                    detail = ats_feeds.fetch_job_detail(detail_url)
                    if not detail or detail.get("http_status") != 200:
                        detail = ats_feeds.fetch_job_detail(apply_url)
                    if detail and detail.get("http_status") == 200:
                        item["title"] = detail.get("title") or item.get("title")
                        item["description"] = detail.get("description") or item.get(
                            "description"
                        )
                if src.company:
                    item["company"] = src.company
                # Region hint: treat empty-location postings from remote boards as remote
                region = (src.region or "").lower()
                if "remote" in region and not (item.get("location") or "").strip():
                    item["remote"] = True
                enriched.append(item)
            jobs = enriched

            fails = src.consecutive_failures
            if status == 200:
                fails = 0
            else:
                fails = (fails or 0) + 1
            vals_src = {
                "last_check_at": now,
                "last_http_status": status or 0,
                "last_error": err,
                "last_jobs_found": len(jobs),
                "consecutive_failures": fails,
            }
            # Auto-disable after repeated hard failures (404 boards)
            if fails >= 5 and status in (404, 410):
                vals_src["enabled"] = False
                vals_src["last_error"] = (err or "") + " auto-disabled after failures"
            src.write(vals_src)

            for item in jobs:
                apply_url = (item.get("apply_url") or "").strip()
                if not apply_url:
                    continue
                canon = Job._canonical_apply_url(apply_url)
                if not canon:
                    continue
                # Dedupe: existing fingerprint/url for account 2
                existing = Job.search(
                    [
                        ("account_id", "=", personal.id),
                        ("apply_url", "ilike", canon.split("://")[-1][:180]),
                    ],
                    limit=5,
                )
                match = existing.filtered(
                    lambda j, c=canon: Job._canonical_apply_url(j.apply_url) == c
                )[:1]
                platform = item.get("ats") or classify_apply_url(apply_url)
                job_vals = {
                    "account_id": personal.id,
                    "title": (item.get("title") or "")[:200],
                    "company": (item.get("company") or src.company or src.name or "")[:200],
                    "location": (item.get("location") or "")[:200],
                    "remote": bool(item.get("remote")),
                    "description": item.get("description") or "",
                    "apply_url": apply_url,
                    "apply_platform": platform
                    if platform
                    in dict(Job._fields["apply_platform"].selection)
                    else classify_apply_url(apply_url),
                    "source": item.get("source") or f"ats:{src.ats_type}",
                    "job_id": (item.get("external_id") or "")[:120] or False,
                    "listed_at": now,
                    "external_ats_id": (item.get("external_id") or "")[:120],
                    "ats_source_id": src.id,
                }
                # Map ashby/workable onto selection — ensure fields allow
                if job_vals["apply_platform"] not in dict(Job._fields["apply_platform"].selection):
                    job_vals["apply_platform"] = "company_ats"

                if match:
                    job = match
                    # Refresh description/score if thin
                    write_vals = {}
                    if not job.description and job_vals.get("description"):
                        write_vals["description"] = job_vals["description"]
                    if write_vals:
                        job.with_context(skip_application_create=True).write(write_vals)
                        job._score_and_dedupe()
                else:
                    job = Job.with_context(
                        skip_application_create=True,
                        skip_job_postprocess=False,
                    ).create(job_vals)
                    stats["new_jobs"] += 1

                # Preflight / classify when score >= 65 or after scoring
                job.invalidate_recordset()
                score = job.score or 0.0
                classification = classify_preflight(
                    title=job.title or "",
                    location=job.location or "",
                    description=job._plain_text_blob() if hasattr(job, "_plain_text_blob") else (job.description or ""),
                    apply_url=job.apply_url or "",
                    remote=bool(job.remote),
                    score=score,
                    ats_hint=job.apply_platform or platform,
                )
                job.write(
                    {
                        "discovery_class": classification["discovery_class"],
                        "discovery_blocker": classification.get("blocker") or "",
                        "last_preflight_at": now,
                        "preflight_json": json.dumps(
                            {
                                "preflight": classification.get("preflight") or {},
                                "http_status": classification.get("http_status"),
                                "platform": classification.get("platform"),
                            },
                            sort_keys=True,
                        ),
                    }
                )
                dc = classification["discovery_class"]
                if dc in stats:
                    stats[dc] = stats.get(dc, 0) + 1
                elif dc == "safe_canary_candidate":
                    stats["safe_canary"] += 1

        # Reclassify existing personal jobs not touched this cycle (e.g. JSearch imports)
        untouched = Job.search(
            [
                ("account_id", "=", personal.id),
                ("is_duplicate", "=", False),
                ("discovery_class", "in", (False, "unchecked")),
            ]
        )
        for job in untouched:
            classification = classify_preflight(
                title=job.title or "",
                location=job.location or "",
                description=job._plain_text_blob()
                if hasattr(job, "_plain_text_blob")
                else (job.description or ""),
                apply_url=job.apply_url or "",
                remote=bool(job.remote),
                score=job.score or 0.0,
                ats_hint=job.apply_platform or "",
            )
            job.write(
                {
                    "discovery_class": classification["discovery_class"],
                    "discovery_blocker": classification.get("blocker") or "",
                    "last_preflight_at": now,
                }
            )
            dc = classification["discovery_class"]
            if dc == "safe_canary_candidate":
                stats["safe_canary"] = stats.get("safe_canary", 0) + 1
            elif dc in stats:
                stats[dc] = stats.get(dc, 0) + 1

        # Persist run stats on policy KPIs via ICP
        ICP = self.env["ir.config_parameter"].sudo()
        ICP.set_param(
            "linkedin_connector.ats_discovery_last_run",
            fields.Datetime.to_string(now),
        )
        ICP.set_param(
            "linkedin_connector.ats_discovery_last_stats_json",
            json.dumps(stats, sort_keys=True),
        )
        ICP.set_param(
            "linkedin_connector.ats_discovery_next_run",
            fields.Datetime.to_string(now + timedelta(hours=6)),
        )

        # Digest snippet for discovery
        self._post_discovery_digest(stats, personal)

        canary_result = None
        if try_canary and stats.get("safe_canary"):
            canary_result = self.env["linkedin.job"].sudo().try_execute_safe_canary()

        def _clean(obj):
            if obj is None:
                return False
            if isinstance(obj, dict):
                return {k: _clean(v) for k, v in obj.items()}
            if isinstance(obj, (list, tuple)):
                return [_clean(v) for v in obj]
            return obj

        return _clean(
            {
                "ok": True,
                "stats": stats,
                "account_id": personal.id,
                "canary": canary_result or {},
                "operating_state": self._operating_state(canary_result),
            }
        )

    @api.model
    def _operating_state(self, canary_result):
        if canary_result and canary_result.get("verdict") == "PERSONAL_JOB_APPLICATION_ORCHESTRATOR_PRODUCTION_LIVE":
            return "PERSONAL_JOB_APPLICATION_ORCHESTRATOR_PRODUCTION_LIVE"
        live = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("linkedin_connector.live_submit_enabled", "False")
        )
        if str(live).lower() in ("1", "true", "yes"):
            return "PERSONAL_JOB_APPLICATION_ORCHESTRATOR_PRODUCTION_LIVE"
        return "ATS_DISCOVERY_LIVE_WAITING_FOR_SAFE_CANARY"

    @api.model
    def _post_discovery_digest(self, stats, personal):
        Job = self.env["linkedin.job"].sudo()
        safe = Job.search(
            [
                ("account_id", "=", personal.id),
                ("discovery_class", "=", "safe_canary_candidate"),
                ("is_duplicate", "=", False),
            ],
            limit=10,
            order="score desc, id desc",
        )
        lines = [
            _("Direct ATS discovery run: sources=%s new=%s safe=%s human=%s ineligible=%s")
            % (
                stats.get("sources_checked"),
                stats.get("new_jobs"),
                stats.get("safe_canary"),
                stats.get("human_required"),
                stats.get("ineligible"),
            )
        ]
        for job in safe:
            lines.append(
                "- [SAFE %.0f] %s @ %s | %s | %s"
                % (job.score or 0, job.title, job.company, job.location, job.apply_url)
            )
        human = Job.search(
            [
                ("account_id", "=", personal.id),
                ("discovery_class", "=", "human_required"),
            ],
            limit=5,
            order="write_date desc",
        )
        for job in human:
            lines.append(
                "- [HUMAN] %s @ %s — %s"
                % (job.title, job.company, job.discovery_blocker or "")
            )
        body = "<br/>".join(lines)
        for partner in Job._digest_recipient_partners():
            partner.message_post(
                body=body,
                subject=_("Direct ATS discovery digest (internal)"),
                message_type="notification",
                subtype_xmlid="mail.mt_note",
            )

    @api.model
    def _cron_direct_ats_discovery(self):
        """Backup 6h cron (Africa/Cairo aligned via nextcall). Kill switch may stay ON."""
        return self.run_discovery_cycle(try_canary=True)
