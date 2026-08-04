# -*- coding: utf-8 -*-
"""Dedicated partner website probe queue (not res.partner, not ATS miss registry)."""

from __future__ import annotations

import json
import logging
import time
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from psycopg2 import IntegrityError

_logger = logging.getLogger(__name__)

# Stable advisory lock key for partner probe cron (must fit signed int4 for pg_try_advisory_lock)
_PROBE_LOCK_KEY = 72840193

_TIER_PRIORITY = {"gold": 300, "silver": 200, "ready": 150, "bronze": 120}
_DEFAULT_PRIORITY = 100

_BACKOFF_MINUTES = (15, 60, 360, 1440, 10080, 43200)  # up to 30d


class LinkedinPartnerAtsProbe(models.Model):
    _name = "linkedin.partner.ats.probe"
    _description = "Partner ATS website probe queue"
    _order = "priority desc, next_probe_at asc, id asc"
    # Intentionally NOT mail.thread — no chatter / mail.message from probing

    partner_id = fields.Many2one(
        "res.partner",
        required=True,
        index=True,
        ondelete="cascade",
    )
    company_id = fields.Many2one(
        "res.company",
        required=True,
        index=True,
        default=lambda self: self.env.company,
    )
    website_normalized = fields.Char(required=True, index=True)
    website_fingerprint = fields.Char(index=True)
    state = fields.Selection(
        [
            ("pending", "Pending"),
            ("processing", "Processing"),
            ("hit", "Hit"),
            ("miss", "Miss"),
            ("retry", "Retry"),
            ("error", "Error"),
            ("disabled", "Disabled"),
        ],
        required=True,
        default="pending",
        index=True,
    )
    priority = fields.Integer(default=100, index=True)
    next_probe_at = fields.Datetime(index=True, default=fields.Datetime.now)
    last_probe_at = fields.Datetime(index=True)
    locked_at = fields.Datetime(index=True)
    attempt_count = fields.Integer(default=0)
    consecutive_error_count = fields.Integer(default=0)
    last_http_status = fields.Integer()
    last_error_code = fields.Char(index=True)
    last_error_message = fields.Char()
    careers_url = fields.Char()
    careers_url_normalized = fields.Char(index=True)
    detected_ats_type = fields.Selection(
        [
            ("greenhouse", "Greenhouse"),
            ("lever", "Lever"),
            ("ashby", "Ashby"),
            ("workable", "Workable"),
            ("company_ats", "Company career site"),
        ],
        index=True,
    )
    detected_board_token = fields.Char(index=True)
    source_id = fields.Many2one("linkedin.ats.source", index=True, ondelete="set null")
    active = fields.Boolean(default=True, index=True)
    detected_pattern = fields.Char()

    _sql_constraints = [
        (
            "partner_website_uniq",
            "unique(partner_id, website_normalized)",
            "Probe queue already exists for this partner website.",
        ),
    ]

    def init(self):
        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS linkedin_partner_probe_ready_idx
            ON linkedin_partner_ats_probe (state, next_probe_at, priority, id)
            WHERE active IS TRUE
            """
        )

    # ------------------------------------------------------------------ config
    @api.model
    def _probe_config(self):
        ICP = self.env["ir.config_parameter"].sudo()

        def _bool(key, default=False):
            raw = ICP.get_param(key, "True" if default else "False")
            return str(raw).lower() in ("1", "true", "yes")

        def _int(key, default, lo, hi):
            try:
                val = int(ICP.get_param(key, str(default)) or default)
            except (TypeError, ValueError):
                val = default
            return max(lo, min(hi, val))

        def _float(key, default, lo, hi):
            try:
                val = float(ICP.get_param(key, str(default)) or default)
            except (TypeError, ValueError):
                val = default
            return max(lo, min(hi, val))

        return {
            "enabled": _bool("linkedin_connector.partner_probe_enabled", False),
            "batch_size": _int("linkedin_connector.partner_probe_batch_size", 40, 1, 200),
            "concurrency": _int("linkedin_connector.partner_probe_max_concurrent", 4, 1, 10),
            "connect_timeout": _float(
                "linkedin_connector.partner_probe_connect_timeout", 3.0, 2.0, 20.0
            ),
            "read_timeout": _float(
                "linkedin_connector.partner_probe_read_timeout", 7.0, 2.0, 20.0
            ),
            "sync_batch": _int("linkedin_connector.partner_probe_sync_batch", 500, 50, 2000),
            "discovery_cap": _int(
                "linkedin_connector.ats_discovery_per_cycle_cap", 20, 1, 200
            ),
        }

    @api.model
    def _partner_priority(self, partner):
        tier = getattr(partner, "odoo_partner_tier", False) or False
        if tier in _TIER_PRIORITY:
            return _TIER_PRIORITY[tier]
        names = {c.name for c in partner.category_id}
        if "Gold" in names:
            return 300
        if "Silver" in names:
            return 200
        if "Ready for Outreach" in names:
            return 150
        if "Bronze" in names:
            return 120
        return _DEFAULT_PRIORITY

    @api.model
    def _backoff_delta(self, attempt_count):
        idx = max(0, min(len(_BACKOFF_MINUTES) - 1, int(attempt_count or 0)))
        return timedelta(minutes=_BACKOFF_MINUTES[idx])

    @api.model
    def _safe_commit(self):
        """Commit only outside unit tests (HTTP must not hold long TX in prod)."""
        # Odoo forbids commit inside TransactionCase
        if getattr(self.env, "testing", False) or self.env.context.get("test_mode"):
            return
        try:
            from odoo.tools import config

            if config.get("test_enable") or config.get("test_file"):
                # Still allow commits during standalone UAT scripts; only block
                # when a test cursor is active (raises AssertionError).
                pass
        except Exception:
            pass
        try:
            self.env.cr.commit()
        except AssertionError:
            # Inside TransactionCase — skip
            return

    # ------------------------------------------------------------------ locking
    @api.model
    def _try_advisory_lock(self):
        self.env.cr.execute("SELECT pg_try_advisory_lock(%s)", (_PROBE_LOCK_KEY,))
        return bool(self.env.cr.fetchone()[0])

    @api.model
    def _advisory_unlock(self):
        self.env.cr.execute("SELECT pg_advisory_unlock(%s)", (_PROBE_LOCK_KEY,))

    # ------------------------------------------------------------------ sync A
    @api.model
    def cron_sync_partner_queue(self):
        """Low-frequency enqueue from res.partner directory (bounded batch)."""
        cfg = self._probe_config()
        if not cfg["enabled"]:
            return {"ok": False, "reason": "partner_probe_disabled"}

        from odoo.addons.linkedin_connector.services.url_normalize import (
            normalize_website,
            website_fingerprint,
        )

        Partner = self.env["res.partner"].sudo()
        # Prefer Odoo Partner category by name (xml id may vary across DBs)
        domain = [
            ("active", "=", True),
            ("website", "!=", False),
            ("website", "!=", ""),
            ("category_id.name", "=", "Odoo Partner"),
        ]
        # Prefer companies when flag present
        if "is_company" in Partner._fields:
            domain.append(("is_company", "=", True))

        already = set(
            self.search([("active", "=", True)]).mapped("partner_id").ids
        )
        partners = Partner.search(domain, order="id asc", limit=cfg["sync_batch"] * 3)
        created = 0
        updated = 0
        deactivated = 0
        now = fields.Datetime.now()
        for partner in partners[: cfg["sync_batch"]]:
            website = normalize_website(partner.website or "")
            if not website:
                continue
            fp = website_fingerprint(partner.website or "")
            existing = self.search(
                [("partner_id", "=", partner.id), ("website_normalized", "=", website)],
                limit=1,
            )
            priority = self._partner_priority(partner)
            if existing:
                vals = {}
                if existing.website_fingerprint != fp:
                    vals.update(
                        {
                            "website_fingerprint": fp,
                            "state": "pending",
                            "attempt_count": 0,
                            "consecutive_error_count": 0,
                            "next_probe_at": now,
                            "careers_url": False,
                            "careers_url_normalized": False,
                            "detected_ats_type": False,
                            "detected_board_token": False,
                        }
                    )
                if existing.priority != priority:
                    vals["priority"] = priority
                if not existing.active:
                    vals["active"] = True
                if vals:
                    existing.write(vals)
                    updated += 1
                continue
            # New queue row
            self.create(
                {
                    "partner_id": partner.id,
                    "company_id": self.env.company.id,
                    "website_normalized": website,
                    "website_fingerprint": fp,
                    "state": "pending",
                    "priority": priority,
                    "next_probe_at": now,
                    "active": True,
                }
            )
            created += 1
            already.add(partner.id)

        # Deactivate queue rows whose partners no longer eligible (sampled)
        stale = self.search(
            [
                ("active", "=", True),
                ("partner_id.active", "=", False),
            ],
            limit=200,
        )
        if stale:
            stale.write({"active": False, "state": "disabled"})
            deactivated += len(stale)

        return {
            "ok": True,
            "created": created,
            "updated": updated,
            "deactivated": deactivated,
        }

    # ------------------------------------------------------------------ probe B
    @api.model
    def cron_probe_due(self, force=False, limit=None):
        """Claim due probe rows, HTTP outside TX, write results in chunks."""
        cfg = self._probe_config()
        if not cfg["enabled"] and not force:
            return {"ok": False, "reason": "partner_probe_disabled"}

        if not self._try_advisory_lock():
            return {"ok": False, "reason": "lock_not_acquired"}

        Run = self.env["linkedin.partner.ats.probe.run"].sudo()
        started = fields.Datetime.now()
        t0 = time.monotonic()
        write_count = 0
        stats = {
            "selected_count": 0,
            "processed_count": 0,
            "hit_count": 0,
            "miss_count": 0,
            "retry_count": 0,
            "error_count": 0,
            "source_created_count": 0,
            "source_reused_count": 0,
            "dedupe_collisions": 0,
            "http_2xx": 0,
            "http_3xx": 0,
            "http_4xx": 0,
            "http_5xx": 0,
            "timeouts": 0,
            "dns_errors": 0,
            "ssl_errors": 0,
            "rate_limited": 0,
        }
        run = Run.create(
            {
                "started_at": started,
                "selected_count": 0,
            }
        )
        write_count += 1

        try:
            batch = int(limit or cfg["batch_size"])
            batch = max(1, min(200, batch))
            now = fields.Datetime.now()
            # Claim in short transaction
            due = self.search(
                [
                    ("active", "=", True),
                    ("state", "in", ("pending", "retry")),
                    ("next_probe_at", "<=", now),
                ],
                order="priority desc, next_probe_at asc, id asc",
                limit=batch,
            )
            if not due:
                run.write(
                    {
                        "finished_at": fields.Datetime.now(),
                        "duration_seconds": time.monotonic() - t0,
                        "selected_count": 0,
                        "processed_count": 0,
                    }
                )
                write_count += 1
                return {"ok": True, "stats": stats, "run_id": run.id, "write_count": write_count}

            due.write(
                {
                    "state": "processing",
                    "locked_at": now,
                }
            )
            write_count += 1  # single ORM write for claimed set
            stats["selected_count"] = len(due)
            self._safe_commit()

            from odoo.addons.linkedin_connector.services.partner_careers_probe import (
                probe_many,
            )

            websites = [r.website_normalized for r in due]
            results = probe_many(
                websites,
                concurrency=cfg["concurrency"],
                connect_timeout=cfg["connect_timeout"],
                read_timeout=cfg["read_timeout"],
            )

            # Process writes in chunks of 5–10
            chunk = []
            for rec, res in zip(due, results):
                chunk.append((rec, res))
                if len(chunk) >= 8:
                    write_count += self._apply_probe_chunk(chunk, stats)
                    chunk = []
                    self._safe_commit()
                    self.env.invalidate_all()
            if chunk:
                write_count += self._apply_probe_chunk(chunk, stats)
                self._safe_commit()

            duration = time.monotonic() - t0
            run.write(
                {
                    "finished_at": fields.Datetime.now(),
                    "selected_count": stats["selected_count"],
                    "processed_count": stats["processed_count"],
                    "hit_count": stats["hit_count"],
                    "miss_count": stats["miss_count"],
                    "retry_count": stats["retry_count"],
                    "error_count": stats["error_count"],
                    "source_created_count": stats["source_created_count"],
                    "source_reused_count": stats["source_reused_count"],
                    "dedupe_collisions": stats["dedupe_collisions"],
                    "http_2xx": stats["http_2xx"],
                    "http_4xx": stats["http_4xx"],
                    "http_5xx": stats["http_5xx"],
                    "timeouts": stats["timeouts"],
                    "dns_errors": stats["dns_errors"],
                    "ssl_errors": stats["ssl_errors"],
                    "rate_limited": stats["rate_limited"],
                    "database_write_count": write_count + 1,
                    "duration_seconds": duration,
                    "notes": json.dumps({"concurrency": cfg["concurrency"]}, sort_keys=True),
                }
            )
            write_count += 1
            ICP = self.env["ir.config_parameter"].sudo()
            ICP.set_param(
                "linkedin_connector.partner_probe_last_run_json",
                json.dumps(
                    {
                        "run_id": run.id,
                        "finished_at": fields.Datetime.to_string(fields.Datetime.now()),
                        "stats": stats,
                        "write_count": write_count,
                    },
                    sort_keys=True,
                ),
            )
            write_count += 1
            self._safe_commit()
            return {
                "ok": True,
                "stats": stats,
                "run_id": run.id,
                "write_count": write_count,
                "duration_seconds": duration,
            }
        finally:
            try:
                self._advisory_unlock()
            except Exception:  # noqa: BLE001
                _logger.exception("probe advisory unlock failed")

    def _apply_probe_chunk(self, chunk, stats):
        """Apply probe results; return approximate write count."""
        writes = 0
        now = fields.Datetime.now()
        Source = self.env["linkedin.ats.source"].sudo()
        for rec, res in chunk:
            stats["processed_count"] += 1
            http_status = int(res.get("http_status") or 0)
            if 200 <= http_status < 300:
                stats["http_2xx"] += 1
            elif 400 <= http_status < 500:
                stats["http_4xx"] += 1
            elif http_status >= 500:
                stats["http_5xx"] += 1
            code = res.get("error_code") or ""
            if code == "timeout":
                stats["timeouts"] += 1
            elif code == "dns_error":
                stats["dns_errors"] += 1
            elif code == "ssl_error":
                stats["ssl_errors"] += 1
            elif code == "rate_limited":
                stats["rate_limited"] += 1

            outcome = res.get("outcome") or "error"
            vals = {
                "last_probe_at": now,
                "locked_at": False,
                "last_http_status": http_status or False,
                "last_error_code": (code or "")[:64] or False,
                "last_error_message": (res.get("error_message") or "")[:500] or False,
                "detected_pattern": (res.get("detected_pattern") or "")[:120] or False,
                "attempt_count": (rec.attempt_count or 0) + 1,
            }

            if outcome == "hit":
                stats["hit_count"] += 1
                vals.update(
                    {
                        "state": "hit",
                        "consecutive_error_count": 0,
                        "next_probe_at": False,
                        "detected_ats_type": res.get("ats_type") or False,
                        "detected_board_token": (res.get("board_token") or "")[:200] or False,
                        "careers_url": (res.get("careers_url") or "")[:500] or False,
                        "careers_url_normalized": (res.get("careers_url_normalized") or "")[
                            :500
                        ]
                        or False,
                    }
                )
                rec.write(vals)
                writes += 1
                created, reused, collision = Source.create_or_reuse_from_probe(rec, res)
                if created:
                    stats["source_created_count"] += 1
                    writes += 1
                if reused:
                    stats["source_reused_count"] += 1
                    writes += 1
                if collision:
                    stats["dedupe_collisions"] += 1
                if rec.source_id:
                    # link already set inside create_or_reuse
                    pass
            elif outcome == "miss":
                stats["miss_count"] += 1
                vals.update(
                    {
                        "state": "miss",
                        "consecutive_error_count": 0,
                        "next_probe_at": now + timedelta(days=30),
                    }
                )
                rec.write(vals)
                writes += 1
            else:
                # retry / error — never create source
                if outcome == "retry":
                    stats["retry_count"] += 1
                else:
                    stats["error_count"] += 1
                attempt = vals["attempt_count"]
                vals.update(
                    {
                        "state": "retry",
                        "consecutive_error_count": (rec.consecutive_error_count or 0) + 1,
                        "next_probe_at": now + self._backoff_delta(attempt),
                    }
                )
                rec.write(vals)
                writes += 1
        return writes

    # ------------------------------------------------------------------ recovery D
    @api.model
    def cron_recover_stuck_processing(self):
        cutoff = fields.Datetime.now() - timedelta(minutes=30)
        stuck = self.search(
            [("state", "=", "processing"), ("locked_at", "<=", cutoff)]
        )
        if not stuck:
            return {"ok": True, "recovered": 0}
        now = fields.Datetime.now()
        for rec in stuck:
            rec.write(
                {
                    "state": "retry",
                    "locked_at": False,
                    "next_probe_at": now + self._backoff_delta(rec.attempt_count or 0),
                    "last_error_code": "stuck_processing",
                    "last_error_message": "recovered_from_processing_timeout",
                }
            )
        return {"ok": True, "recovered": len(stuck)}


class LinkedinPartnerAtsProbeRun(models.Model):
    _name = "linkedin.partner.ats.probe.run"
    _description = "Partner ATS probe batch run audit"
    _order = "id desc"

    started_at = fields.Datetime(required=True, index=True)
    finished_at = fields.Datetime(index=True)
    selected_count = fields.Integer()
    processed_count = fields.Integer()
    hit_count = fields.Integer()
    miss_count = fields.Integer()
    retry_count = fields.Integer()
    error_count = fields.Integer()
    source_created_count = fields.Integer()
    source_reused_count = fields.Integer()
    dedupe_collisions = fields.Integer()
    duration_seconds = fields.Float()
    database_write_count = fields.Integer()
    http_2xx = fields.Integer()
    http_4xx = fields.Integer()
    http_5xx = fields.Integer()
    timeouts = fields.Integer()
    dns_errors = fields.Integer()
    ssl_errors = fields.Integer()
    rate_limited = fields.Integer()
    notes = fields.Char()
