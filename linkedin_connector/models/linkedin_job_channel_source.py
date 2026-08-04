# -*- coding: utf-8 -*-
"""Allowlisted external discovery channels (Telegram / Facebook)."""

from __future__ import annotations

import json
import logging
import os
import re
from urllib.parse import urlparse

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.I)
_JOB_HINT_RE = re.compile(
    r"\b(odoo|erp|python|developer|job|hiring|vacancy|career|remote)\b",
    re.I,
)


class LinkedinJobChannelSource(models.Model):
    _name = "linkedin.job.channel.source"
    _description = "Allowlisted job discovery channel (Telegram / Facebook)"
    _order = "enabled desc, channel_type, name"

    name = fields.Char(required=True)
    channel_type = fields.Selection(
        [
            ("telegram", "Telegram"),
            ("facebook", "Facebook"),
        ],
        required=True,
        index=True,
    )
    enabled = fields.Boolean(default=False, index=True)
    external_id = fields.Char(
        string="Chat / Page ID",
        help="Telegram chat_id (e.g. -100…) or Facebook page/group id or slug.",
    )
    url = fields.Char(
        string="URL",
        help="Optional public URL for Facebook page/group or Telegram invite.",
    )
    title = fields.Char(help="Human label / channel title.")
    last_message_id = fields.Char(
        string="Last message cursor",
        help="Telegram last update/message id processed.",
    )
    last_scan_at = fields.Datetime()
    last_error = fields.Char()
    last_jobs_found = fields.Integer()
    notes = fields.Text()
    account_id = fields.Many2one(
        "linkedin.account",
        string="Target account",
        default=lambda self: self.env["linkedin.account"].browse(2).exists(),
        domain="[('account_type', '=', 'personal')]",
    )

    def action_run_now(self):
        self.ensure_one()
        if self.channel_type == "telegram":
            return self.env["linkedin.job.channel.source"].run_telegram_ingest(
                source_ids=self.ids
            )
        return self.env["linkedin.job.channel.source"].run_facebook_scan(
            source_ids=self.ids
        )

    @api.model
    def _personal_account(self):
        Account = self.env["linkedin.account"]
        personal = Account.browse(2).exists()
        if personal and personal.account_type == "personal":
            return personal
        raise UserError(_("Channel ingest requires personal account id=2."))

    @api.model
    def _telegram_bot_token(self):
        for env_name in ("TELEGRAM_JOB_BOT_TOKEN", "LINKEDIN_TELEGRAM_BOT_TOKEN"):
            val = (os.environ.get(env_name) or "").strip()
            if val:
                return val
        return (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("linkedin_connector.telegram_bot_token", "")
            or ""
        ).strip()

    @api.model
    def _extract_urls(self, text):
        return [u.rstrip(").,]") for u in _URL_RE.findall(text or "")]

    @api.model
    def _looks_like_job(self, text):
        return bool(_JOB_HINT_RE.search(text or ""))

    @api.model
    def _upsert_job_from_channel(self, *, account, title, company, apply_url, channel, source_label, description=""):
        Job = self.env["linkedin.job"].sudo()
        from odoo.addons.linkedin_connector.services.platform_classifier import (
            classify_apply_url,
        )
        from odoo.addons.linkedin_connector.services.ats_preflight import (
            classify_preflight,
        )

        apply_url = (apply_url or "").strip()
        if not apply_url:
            return False
        canon = Job._canonical_apply_url(apply_url)
        if not canon:
            return False
        existing = Job.search(
            [
                ("account_id", "=", account.id),
                ("apply_url", "ilike", canon.split("://")[-1][:180]),
            ],
            limit=8,
        )
        match = existing.filtered(
            lambda j, c=canon: Job._canonical_apply_url(j.apply_url) == c
        )[:1]
        platform = classify_apply_url(apply_url)
        vals = {
            "account_id": account.id,
            "title": (title or "Job posting")[:200],
            "company": (company or "")[:200],
            "location": "",
            "remote": "remote" in ((title or "") + (description or "")).lower(),
            "description": description or "",
            "apply_url": apply_url,
            "apply_platform": platform
            if platform in dict(Job._fields["apply_platform"].selection)
            else "unknown",
            "source": source_label,
            "source_channel": channel,
            "listed_at": fields.Datetime.now(),
        }
        if match:
            job = match
            write_vals = {}
            if not job.description and vals.get("description"):
                write_vals["description"] = vals["description"]
            if write_vals:
                job.with_context(skip_application_create=True).write(write_vals)
                job._score_and_dedupe()
        else:
            job = Job.with_context(
                skip_application_create=True,
                skip_job_postprocess=False,
            ).create(vals)
        classification = classify_preflight(
            title=job.title or "",
            location=job.location or "",
            description=job.description or "",
            apply_url=job.apply_url or "",
            remote=bool(job.remote),
            score=job.score or 0.0,
            ats_hint=job.apply_platform or "",
        )
        job.write(
            {
                "discovery_class": classification["discovery_class"],
                "discovery_blocker": classification.get("blocker") or "",
                "last_preflight_at": fields.Datetime.now(),
                "preflight_json": json.dumps(
                    {
                        "preflight": classification.get("preflight") or {},
                        "platform": classification.get("platform"),
                        "channel": channel,
                    },
                    sort_keys=True,
                ),
            }
        )
        return job

    @api.model
    def run_telegram_ingest(self, source_ids=None):
        """Pull new messages from allowlisted Telegram chats the bot can read.

        Requires TELEGRAM_JOB_BOT_TOKEN and enabled sources with external_id.
        Never auto-applies — jobs go through preflight only.
        """
        token = self._telegram_bot_token()
        if not token:
            _logger.info(
                "telegram ingest skipped: TELEGRAM_JOB_BOT_TOKEN not configured"
            )
            return {"ok": False, "error": "bot_token_missing", "created": 0}

        personal = self._personal_account()
        domain = [("channel_type", "=", "telegram"), ("enabled", "=", True)]
        if source_ids:
            domain.append(("id", "in", list(source_ids)))
        sources = self.search(domain)
        if not sources:
            return {
                "ok": True,
                "skipped": "no_enabled_telegram_sources",
                "created": 0,
                "hint": "Add allowlisted channels and enable them after bot membership.",
            }

        created = 0
        for src in sources:
            chat_id = (src.external_id or "").strip()
            if not chat_id:
                src.write({"last_error": "missing_chat_id"})
                continue
            params = {"chat_id": chat_id, "limit": 50}
            if src.last_message_id:
                try:
                    params["offset"] = int(src.last_message_id) + 1
                except ValueError:
                    pass
            try:
                # getUpdates is global; prefer getChatHistory via Bot API is not public.
                # Use getUpdates filtered client-side by chat_id.
                resp = requests.get(
                    f"https://api.telegram.org/bot{token}/getUpdates",
                    params={"timeout": 0, "limit": 100},
                    timeout=30,
                )
                data = resp.json() if resp.content else {}
            except Exception as exc:  # noqa: BLE001
                src.write(
                    {
                        "last_error": str(exc)[:240],
                        "last_scan_at": fields.Datetime.now(),
                    }
                )
                continue
            if not data.get("ok"):
                src.write(
                    {
                        "last_error": (data.get("description") or "telegram_api_error")[
                            :240
                        ],
                        "last_scan_at": fields.Datetime.now(),
                    }
                )
                continue

            max_update = src.last_message_id or ""
            found = 0
            for upd in data.get("result") or []:
                msg = upd.get("message") or upd.get("channel_post") or {}
                chat = msg.get("chat") or {}
                if str(chat.get("id")) != str(chat_id):
                    continue
                text = msg.get("text") or msg.get("caption") or ""
                mid = str(msg.get("message_id") or upd.get("update_id") or "")
                if mid and (not max_update or mid > str(max_update)):
                    max_update = mid
                if not self._looks_like_job(text):
                    continue
                urls = self._extract_urls(text)
                title_line = (text.strip().splitlines() or [src.title or src.name])[0][
                    :200
                ]
                if not urls:
                    # Store for human review with telegram deep link when possible
                    continue
                for url in urls[:3]:
                    host = urlparse(url).netloc.lower()
                    if "t.me" in host:
                        continue
                    job = self._upsert_job_from_channel(
                        account=personal,
                        title=title_line,
                        company=src.title or src.name or "",
                        apply_url=url,
                        channel="telegram",
                        source_label=f"telegram:{src.name}",
                        description=text[:4000],
                    )
                    if job:
                        found += 1
                        created += 1
            src.write(
                {
                    "last_message_id": max_update or src.last_message_id,
                    "last_scan_at": fields.Datetime.now(),
                    "last_jobs_found": found,
                    "last_error": False,
                }
            )
        return {"ok": True, "created": created}

    @api.model
    def run_facebook_scan(self, source_ids=None):
        """Phase 3 stub: record scan intent; live Glass browser ingest needs named pages.

        Does not mass-automate. When sources are enabled with URLs, marks them for
        human/browser-assisted collection and returns Needs Action guidance.
        """
        personal = self._personal_account()
        domain = [("channel_type", "=", "facebook"), ("enabled", "=", True)]
        if source_ids:
            domain.append(("id", "in", list(source_ids)))
        sources = self.search(domain)
        if not sources:
            return {
                "ok": True,
                "skipped": "no_enabled_facebook_sources",
                "created": 0,
                "hint": "Provide named Pages/groups + which FB account to use.",
            }

        results = []
        for src in sources:
            src.write(
                {
                    "last_scan_at": fields.Datetime.now(),
                    "last_error": "browser_ingest_pending_named_pages",
                    "notes": (
                        (src.notes or "")
                        + "\n[scan] Browser-assisted Facebook ingest pending. "
                        "Use facebook-account-manager / Glass for allowlisted pages only."
                    ).strip()[:4000],
                }
            )
            results.append(
                {
                    "id": src.id,
                    "name": src.name,
                    "url": src.url or "",
                    "status": "manual_browser_required",
                    "account_id": personal.id,
                }
            )
        return {
            "ok": True,
            "created": 0,
            "sources": results,
            "message": "Facebook sources logged for browser-assisted ingest; no auto-apply.",
        }

    @api.model
    def _cron_telegram_ingest(self):
        if (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("linkedin_connector.live_job_search_enabled", "False")
            .lower()
            not in ("1", "true", "yes")
        ):
            return {"ok": True, "skipped": "live_job_search_disabled"}
        return self.run_telegram_ingest()

    @api.model
    def _cron_facebook_scan(self):
        if (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("linkedin_connector.live_job_search_enabled", "False")
            .lower()
            not in ("1", "true", "yes")
        ):
            return {"ok": True, "skipped": "live_job_search_disabled"}
        return self.run_facebook_scan()
