# -*- coding: utf-8 -*-
import json
import logging
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from psycopg2 import IntegrityError

_logger = logging.getLogger(__name__)


class LinkedinAtsSource(models.Model):
    _name = "linkedin.ats.source"
    _description = "Direct ATS Employer Registry"
    _order = "enabled desc, discovery_priority desc, next_discovery_at asc, id"

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
        index=True,
    )
    board_token_normalized = fields.Char(index=True)
    company = fields.Char()
    region = fields.Char(help="egypt|uae|gulf|remote|europe|global")
    feed_url = fields.Char(string="Optional feed URL")
    careers_url_normalized = fields.Char(index=True)
    enabled = fields.Boolean(default=True, index=True)
    last_check_at = fields.Datetime()
    last_http_status = fields.Integer()
    last_error = fields.Char()
    last_jobs_found = fields.Integer()
    consecutive_failures = fields.Integer(default=0)
    notes = fields.Text()
    # Confirmed-registry link to partner (optional; manual seeds may omit)
    partner_id = fields.Many2one("res.partner", index=True, ondelete="set null")
    connector_id = fields.Many2one(
        "linkedin.job.source.connector",
        index=True,
        ondelete="set null",
        help="Optional job-source connector that owns this ATS board.",
    )
    is_primary_partner_source = fields.Boolean(
        default=False,
        index=True,
        help="Auto-discovered primary source for partner; manual seeds leave False.",
    )
    last_discovery_at = fields.Datetime(index=True)
    next_discovery_at = fields.Datetime(index=True, default=fields.Datetime.now)
    discovery_interval_minutes = fields.Integer(default=360)
    discovery_priority = fields.Integer(default=100, index=True)

    def init(self):
        cr = self.env.cr
        cr.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS linkedin_ats_source_primary_partner_uniq
            ON linkedin_ats_source (partner_id)
            WHERE is_primary_partner_source IS TRUE AND partner_id IS NOT NULL
            """
        )
        cr.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS linkedin_ats_source_board_uniq
            ON linkedin_ats_source (ats_type, board_token_normalized)
            WHERE board_token_normalized IS NOT NULL AND board_token_normalized <> ''
              AND ats_type IN ('greenhouse', 'lever', 'ashby', 'workable')
            """
        )
        cr.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS linkedin_ats_source_careers_uniq
            ON linkedin_ats_source (careers_url_normalized)
            WHERE careers_url_normalized IS NOT NULL AND careers_url_normalized <> ''
              AND ats_type = 'company_ats'
            """
        )

    @api.model_create_multi
    def create(self, vals_list):
        from odoo.addons.linkedin_connector.services.url_normalize import (
            normalize_board_token,
            normalize_website,
        )

        for vals in vals_list:
            token = vals.get("board_token") or ""
            if token and not vals.get("board_token_normalized"):
                if vals.get("ats_type") == "company_ats":
                    vals["board_token_normalized"] = normalize_website(token)
                    vals.setdefault("careers_url_normalized", vals["board_token_normalized"])
                else:
                    vals["board_token_normalized"] = normalize_board_token(token)
            if vals.get("careers_url_normalized"):
                vals["careers_url_normalized"] = normalize_website(
                    vals["careers_url_normalized"]
                )
            if not vals.get("next_discovery_at"):
                vals["next_discovery_at"] = fields.Datetime.now()
        return super().create(vals_list)

    def write(self, vals):
        from odoo.addons.linkedin_connector.services.url_normalize import (
            normalize_board_token,
            normalize_website,
        )

        if "board_token" in vals and "board_token_normalized" not in vals:
            token = vals.get("board_token") or ""
            # Per-record ats_type may differ; normalize conservatively
            vals["board_token_normalized"] = (
                normalize_website(token)
                if any(r.ats_type == "company_ats" for r in self)
                else normalize_board_token(token)
            )
        if vals.get("careers_url_normalized"):
            vals["careers_url_normalized"] = normalize_website(
                vals["careers_url_normalized"]
            )
        return super().write(vals)

    @api.model
    def create_or_reuse_from_probe(self, probe_rec, probe_res):
        """Create enabled ATS source on hit, or reuse by normalized keys.

        Returns (created: bool, reused: bool, collision: bool).
        Misses/errors must never call this.
        """
        from odoo.addons.linkedin_connector.services.url_normalize import (
            normalize_board_token,
            normalize_website,
        )

        ats_type = (probe_res.get("ats_type") or "").strip()
        if ats_type not in ("greenhouse", "lever", "ashby", "workable", "company_ats"):
            return False, False, False

        token_raw = (probe_res.get("board_token") or "").strip()
        careers = normalize_website(
            probe_res.get("careers_url_normalized")
            or probe_res.get("careers_url")
            or (token_raw if ats_type == "company_ats" else "")
        )
        token_norm = (
            careers
            if ats_type == "company_ats"
            else normalize_board_token(token_raw)
        )
        if not token_norm:
            return False, False, False

        # Search existing
        existing = self.browse()
        if ats_type == "company_ats":
            existing = self.search(
                [("careers_url_normalized", "=", careers), ("ats_type", "=", "company_ats")],
                limit=1,
            )
        else:
            existing = self.search(
                [
                    ("ats_type", "=", ats_type),
                    ("board_token_normalized", "=", token_norm),
                ],
                limit=1,
            )
        if not existing and probe_rec.partner_id:
            existing = self.search(
                [
                    ("partner_id", "=", probe_rec.partner_id.id),
                    ("is_primary_partner_source", "=", True),
                ],
                limit=1,
            )

        partner = probe_rec.partner_id
        company_name = (partner.name if partner else "") or ""
        name = f"{company_name} ({ats_type})" if company_name else f"Partner ATS {ats_type}"
        now = fields.Datetime.now()

        if existing:
            vals = {
                "enabled": True,
                "next_discovery_at": now,
                "discovery_priority": max(existing.discovery_priority or 0, 250),
            }
            if partner and not existing.partner_id:
                vals["partner_id"] = partner.id
            existing.write(vals)
            probe_rec.write({"source_id": existing.id})
            return False, True, False

        vals = {
            "name": name[:200],
            "ats_type": ats_type,
            "board_token": careers if ats_type == "company_ats" else token_raw,
            "board_token_normalized": token_norm,
            "careers_url_normalized": careers if ats_type == "company_ats" else False,
            "company": company_name[:200] or False,
            "enabled": True,
            "partner_id": partner.id if partner else False,
            "is_primary_partner_source": bool(partner),
            "discovery_priority": 250,
            "next_discovery_at": now,
            "discovery_interval_minutes": 360,
            "notes": f"auto_from_partner_probe:{probe_rec.id}",
        }
        try:
            with self.env.cr.savepoint():
                source = self.create(vals)
            probe_rec.write({"source_id": source.id})
            return True, False, False
        except IntegrityError:
            # savepoint rolled back automatically; re-search and link
            if ats_type == "company_ats":
                existing = self.search(
                    [
                        ("careers_url_normalized", "=", careers),
                        ("ats_type", "=", "company_ats"),
                    ],
                    limit=1,
                )
            else:
                existing = self.search(
                    [
                        ("ats_type", "=", ats_type),
                        ("board_token_normalized", "=", token_norm),
                    ],
                    limit=1,
                )
            if existing:
                probe_rec.write({"source_id": existing.id})
                return False, True, True
            _logger.warning(
                "ATS source create collision unresolved partner=%s ats=%s",
                partner.id if partner else None,
                ats_type,
            )
            return False, False, True

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
    def _discovery_cap(self):
        ICP = self.env["ir.config_parameter"].sudo()
        try:
            cap = int(ICP.get_param("linkedin_connector.ats_discovery_per_cycle_cap", "20") or 20)
        except (TypeError, ValueError):
            cap = 20
        return max(1, min(200, cap))

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

        now = fields.Datetime.now()
        if source_ids:
            sources = self.search(
                [("id", "in", list(source_ids)), ("enabled", "=", True)]
            )
        else:
            # Due + capped discovery (independent of probe)
            cap = self._discovery_cap()
            sources = self.search(
                [
                    ("enabled", "=", True),
                    "|",
                    ("next_discovery_at", "=", False),
                    ("next_discovery_at", "<=", now),
                ],
                order="discovery_priority desc, next_discovery_at asc, id asc",
                limit=cap,
            )
        Job = self.env["linkedin.job"].sudo()
        stats = {
            "sources_checked": 0,
            "new_jobs": 0,
            "safe_canary": 0,
            "human_required": 0,
            "ineligible": 0,
            "unsupported_ats": 0,
            "errors": 0,
            "discovery_cap": self._discovery_cap() if not source_ids else len(sources),
        }

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
                "last_discovery_at": now,
                "last_http_status": status or 0,
                "last_error": err,
                "last_jobs_found": len(jobs),
                "consecutive_failures": fails,
                "next_discovery_at": now
                + timedelta(minutes=max(30, int(src.discovery_interval_minutes or 360))),
                "discovery_priority": min(src.discovery_priority or 100, 200)
                if status == 200
                else (src.discovery_priority or 100),
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
                channel = Job._normalize_source_channel(
                    ats_type=src.ats_type,
                    source=item.get("source") or f"ats:{src.ats_type}",
                    apply_platform=platform,
                )
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
                    "source_channel": channel,
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

                # Preflight / classify after scoring (score is informational only)
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
        if canary_result and canary_result.get("verdict") == "ALL_SCORES_APPLICATION_POLICY_LIVE":
            return "ALL_SCORES_APPLICATION_POLICY_LIVE"
        if canary_result and canary_result.get("verdict") == "ALL_SCORES_APPLICATION_POLICY_BLOCKED":
            return "ALL_SCORES_APPLICATION_POLICY_BLOCKED"
        live = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("linkedin_connector.live_submit_enabled", "False")
        )
        if str(live).lower() in ("1", "true", "yes"):
            return "ALL_SCORES_APPLICATION_POLICY_LIVE"
        return "ALL_SCORES_POLICY_ACTIVE_WAITING_FOR_SAFE_CANARY"

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
