# -*- coding: utf-8 -*-
"""E3: read-only Discuss Hub health checks (no routing mutations)."""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import timedelta

from odoo import api, fields, models
_logger = logging.getLogger(__name__)

PENDING_AGE_MINUTES = 15
LEAKAGE_LOOKBACK_DAYS = 30
DUP_LOOKBACK_DAYS = 7


def _parse_allowlist(env):
    raw = (
        env["ir.config_parameter"]
        .sudo()
        .get_param("whatsapp_hub.discuss_hub_allowed_channel_ids")
        or ""
    ).strip()
    if not raw:
        return None  # empty = fail-closed semantic for cutover; treat as []
    ids = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if not part.isdigit():
            return False  # malformed
        ids.append(int(part))
    return ids


class WhatsappDiscussHubHealth(models.Model):
    _name = "whatsapp.discuss.hub.health"
    _description = "Discuss Hub Health Status"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _rec_name = "display_name"

    display_name = fields.Char(default="Discuss Hub Health", readonly=True)
    last_run_at = fields.Datetime(readonly=True)
    last_status = fields.Selection(
        [
            ("healthy", "Healthy"),
            ("warning", "Warning"),
            ("critical", "Critical"),
            ("unknown", "Unknown"),
        ],
        default="unknown",
        readonly=True,
    )
    last_issue_count = fields.Integer(readonly=True)
    last_critical_count = fields.Integer(readonly=True)
    last_warning_count = fields.Integer(readonly=True)
    last_result_json = fields.Text(readonly=True)
    last_issue_fingerprint = fields.Char(
        readonly=True,
        help="Hash of open critical issue keys for duplicate activity suppression.",
    )
    active = fields.Boolean(default=True)

    @api.model
    def _get_singleton(self):
        rec = self.sudo().search([], limit=1)
        if not rec:
            rec = self.sudo().create({"display_name": "Discuss Hub Health"})
        return rec

    @api.model
    def _responsible_user(self):
        """Prefer Hub manager with system rights; fall back to admin partner."""
        Users = self.env["res.users"].sudo()
        managers = Users.search(
            [("group_ids", "in", self.env.ref("whatsapp_hub.group_whatsapp_manager").id)],
            order="id",
            limit=20,
        )
        for user in managers:
            if user.has_group("base.group_system") and user.active:
                return user
        if managers:
            return managers[0]
        admin = self.env.ref("base.user_admin", raise_if_not_found=False)
        if admin and admin.active:
            return admin
        return Users.browse()

    @api.model
    def _current_hub_activation_floor(self, Log, channel_id):
        """
        Start of the trailing contiguous hub_unified streak for a channel.

        Returns (create_date, id) of the oldest hub_unified in that streak, or
        (False, False) when no Hub sends exist.

        Migration may briefly return a Hub channel to shadow (legacy path) between
        pilot and soak. Those intentional mid-migration legacy logs must not be
        treated as current leakage once a newer Hub streak is active.
        """
        logs = Log.search(
            [("channel_id", "=", channel_id)],
            order="create_date desc, id desc",
            limit=500,
        )
        floor_dt = False
        floor_id = False
        saw_hub = False
        for log in logs:
            origin = log.send_origin or ""
            if origin == "hub_unified":
                saw_hub = True
                floor_dt = log.create_date
                floor_id = log.id
                continue
            if saw_hub:
                break
        return floor_dt, floor_id

    @api.model
    def service_run_health_check(self, notify=True, create_activities=True):
        """
        Read-only Discuss Hub health scan.

        Never changes modes, allowlist, flags, or sends WhatsApp traffic.
        """
        Channel = self.env["discuss.channel"].sudo()
        Out = self.env["whatsapp.outbound.message"].sudo()
        Message = self.env["whatsapp.message"].sudo()
        Log = self.env["wa.message.log"].sudo() if "wa.message.log" in self.env else None
        now = fields.Datetime.now()
        issues = []

        allow_raw = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("whatsapp_hub.discuss_hub_allowed_channel_ids")
            or ""
        )
        allow = _parse_allowlist(self.env)
        if allow is False:
            issues.append(
                {
                    "severity": "critical",
                    "type": "allowlist_malformed",
                    "channel_id": False,
                    "ref": allow_raw,
                    "message": "discuss_hub_allowed_channel_ids is malformed",
                    "action": "Fix ICP to comma-separated integers (e.g. 10,5)",
                }
            )
            allow_ids = []
        elif allow is None:
            allow_ids = []
        else:
            allow_ids = list(allow)
        allow_set = set(allow_ids)

        wa_channels = Channel.search(
            [("wa_phone", "!=", False), ("wa_phone", "!=", "")]
        )
        hub_channels = wa_channels.filtered(lambda c: c.wa_outbound_mode == "hub")

        # 1) Hub mode must be allowlisted
        for ch in hub_channels:
            if ch.id not in allow_set:
                issues.append(
                    {
                        "severity": "critical",
                        "type": "hub_not_allowlisted",
                        "channel_id": ch.id,
                        "ref": ch.id,
                        "message": f"Channel {ch.id} is hub but not in allowlist",
                        "action": "Add to allowlist or set mode to shadow/legacy",
                    }
                )

        # 2–4) Allowlisted ids exist, have JID, resolve instance
        for cid in allow_ids:
            ch = Channel.browse(cid)
            if not ch.exists():
                issues.append(
                    {
                        "severity": "critical",
                        "type": "allowlist_missing_channel",
                        "channel_id": cid,
                        "ref": cid,
                        "message": f"Allowlisted channel {cid} does not exist",
                        "action": "Remove from allowlist",
                    }
                )
                continue
            if not (ch.wa_phone or "").strip():
                issues.append(
                    {
                        "severity": "critical",
                        "type": "allowlist_missing_jid",
                        "channel_id": cid,
                        "ref": cid,
                        "message": f"Allowlisted channel {cid} has empty wa_phone",
                        "action": "Fix JID/phone or remove from allowlist",
                    }
                )
            if ch.wa_outbound_mode == "hub":
                try:
                    inst = ch._wa_resolve_hub_instance()
                except Exception:
                    inst = False
                if not inst:
                    issues.append(
                        {
                            "severity": "warning",
                            "type": "hub_instance_unresolved",
                            "channel_id": cid,
                            "ref": cid,
                            "message": f"Hub channel {cid} could not resolve Hub instance",
                            "action": "Check whatsapp.instance / Evolution default",
                        }
                    )

        # 5) Jobs outside allowlist (when allowlist configured)
        if allow_ids or allow is None:
            # empty allowlist: any discuss unified job with channel is "outside" while cutover ON
            outs = Out.search(
                [
                    ("transport_mode", "=", "unified_bridge"),
                    ("discuss_channel_id", "!=", False),
                ]
            )
            for job in outs:
                cid = job.discuss_channel_id
                if not cid:
                    continue
                if allow_ids and cid not in allow_set:
                    sev = (
                        "critical"
                        if job.state in ("pending", "processing")
                        else "warning"
                    )
                    issues.append(
                        {
                            "severity": sev,
                            "type": "job_outside_allowlist",
                            "channel_id": cid,
                            "ref": job.id,
                            "message": (
                                f"unified_bridge job {job.id} state={job.state} "
                                f"for channel {cid} outside allowlist {allow_ids}"
                            ),
                            "action": (
                                "Quarantine if incomplete; investigate admission path"
                                if sev == "critical"
                                else "Historical sent job outside current allowlist — review"
                            ),
                        }
                    )
                elif not allow_ids:
                    # fail-closed empty allowlist: any discuss hub job is unexpected if cutover on
                    cutover = (
                        self.env["ir.config_parameter"]
                        .sudo()
                        .get_param("whatsapp_hub.discuss_cutover_enabled")
                        or ""
                    ).lower() in ("1", "true", "yes", "on")
                    if cutover and job.state in ("pending", "processing"):
                        issues.append(
                            {
                                "severity": "critical",
                                "type": "job_with_empty_allowlist",
                                "channel_id": cid,
                                "ref": job.id,
                                "message": (
                                    f"Incomplete unified job {job.id} while allowlist empty"
                                ),
                                "action": "Quarantine and restore allowlist or disable cutover",
                            }
                        )

        # 6) Stale pending/processing
        cutoff = now - timedelta(minutes=PENDING_AGE_MINUTES)
        stale = Out.search(
            [
                ("transport_mode", "=", "unified_bridge"),
                ("discuss_channel_id", "!=", False),
                ("state", "in", ("pending", "processing")),
                ("create_date", "<=", cutoff),
            ]
        )
        for job in stale:
            issues.append(
                {
                    "severity": "critical",
                    "type": "stale_pending",
                    "channel_id": job.discuss_channel_id,
                    "ref": job.id,
                    "message": (
                        f"Job {job.id} pending/processing older than "
                        f"{PENDING_AGE_MINUTES}m (state={job.state})"
                    ),
                    "action": "Reconcile provider id or quarantine channel jobs",
                }
            )

        # 7) Duplicate recent provider IDs
        since_dup = now - timedelta(days=DUP_LOOKBACK_DAYS)
        recent_jobs = Out.search(
            [
                ("transport_mode", "=", "unified_bridge"),
                ("evolution_message_id", "!=", False),
                ("create_date", ">=", since_dup),
            ]
        )
        by_provider = {}
        for job in recent_jobs:
            pid = (job.evolution_message_id or "").strip()
            if not pid:
                continue
            by_provider.setdefault(pid, []).append(job.id)
        for pid, jids in by_provider.items():
            if len(jids) > 1:
                issues.append(
                    {
                        "severity": "critical",
                        "type": "duplicate_provider_id",
                        "channel_id": False,
                        "ref": pid,
                        "message": f"Provider id {pid} on jobs {jids}",
                        "action": "Investigate duplicate send; do not legacy-resend",
                    }
                )

        # 8) Duplicate business keys on recent messages (soft check)
        recent_msgs = Message.search(
            [
                ("business_key", "!=", False),
                ("source_app", "=", "discuss"),
                ("create_date", ">=", since_dup),
            ]
        )
        by_biz = {}
        for msg in recent_msgs:
            by_biz.setdefault(msg.business_key, []).append(msg.id)
        for biz, mids in by_biz.items():
            if len(mids) > 1:
                issues.append(
                    {
                        "severity": "critical",
                        "type": "duplicate_business_key",
                        "channel_id": False,
                        "ref": biz,
                        "message": f"business_key {biz} on messages {mids}",
                        "action": "Investigate identity collision",
                    }
                )

        # 9) Current legacy leakage after the *current* Hub streak floor.
        # Floor = start of the trailing contiguous hub_unified streak (not the
        # first-ever Hub send). This ignores intentional migration patterns such
        # as temporary shadow regression between pilot and soak.
        if Log is not None:
            for ch in hub_channels:
                floor_dt, floor_id = self._current_hub_activation_floor(Log, ch.id)
                if not floor_dt or not floor_id:
                    continue
                lookback = now - timedelta(days=LEAKAGE_LOOKBACK_DAYS)
                if floor_dt < lookback:
                    floor_dt = lookback
                    # When lookback replaces streak start, ignore id tie-break
                    floor_id = 0
                leak = Log.search(
                    [
                        ("channel_id", "=", ch.id),
                        ("send_origin", "=", "legacy"),
                        "|",
                        ("create_date", ">", floor_dt),
                        "&",
                        ("create_date", "=", floor_dt),
                        ("id", ">=", floor_id),
                    ],
                    limit=5,
                )
                for log in leak:
                    issues.append(
                        {
                            "severity": "critical",
                            "type": "legacy_leakage",
                            "channel_id": ch.id,
                            "ref": log.id,
                            "message": (
                                f"Hub channel {ch.id} has legacy send_origin log "
                                f"{log.id} after current Hub streak floor "
                                f"{floor_dt}/id={floor_id}"
                            ),
                            "action": "Rollback channel or investigate dual-path send",
                        }
                    )

        # 10) Optional compat convergence for recent hub_unified logs
        if Log is not None:
            since_compat = now - timedelta(days=DUP_LOOKBACK_DAYS)
            hub_logs = Log.search(
                [
                    ("send_origin", "=", "hub_unified"),
                    ("create_date", ">=", since_compat),
                ],
                limit=200,
            )
            for log in hub_logs:
                if not log.hub_message_id:
                    issues.append(
                        {
                            "severity": "warning",
                            "type": "compat_missing_hub_link",
                            "channel_id": log.channel_id,
                            "ref": log.id,
                            "message": f"hub_unified log {log.id} missing hub_message_id",
                            "action": "Inspect mirror/compat linkage",
                        }
                    )
                    continue
                hub = log.hub_message_id
                if hub.wa_message_log_id and hub.wa_message_log_id != log.id:
                    issues.append(
                        {
                            "severity": "warning",
                            "type": "compat_divergence",
                            "channel_id": log.channel_id,
                            "ref": log.id,
                            "message": (
                                f"log {log.id} hub_message={hub.id} but "
                                f"hub.wa_message_log_id={hub.wa_message_log_id}"
                            ),
                            "action": "Inspect convergence",
                        }
                    )
                twin = Message.search_count(
                    [("business_key", "=", f"walog:{log.id}")]
                )
                if twin:
                    issues.append(
                        {
                            "severity": "warning",
                            "type": "walog_twin",
                            "channel_id": log.channel_id,
                            "ref": log.id,
                            "message": f"walog:{log.id} twin Hub message exists",
                            "action": "Inspect duplicate canonical identity",
                        }
                    )

        critical = [i for i in issues if i["severity"] == "critical"]
        warnings = [i for i in issues if i["severity"] == "warning"]
        if critical:
            status = "critical"
        elif warnings:
            status = "warning"
        else:
            status = "healthy"

        result = {
            "ok": True,
            "status": status,
            "run_at": fields.Datetime.to_string(now),
            "channels_checked": wa_channels.ids,
            "hub_channels": hub_channels.ids,
            "allowlist": allow_ids,
            "allowlist_raw": allow_raw,
            "issue_count": len(issues),
            "critical_count": len(critical),
            "warning_count": len(warnings),
            "issues": issues,
        }

        # Fingerprint critical issues for activity dedupe
        crit_keys = sorted(
            f"{i['type']}:{i.get('channel_id')}:{i.get('ref')}" for i in critical
        )
        fingerprint = hashlib.sha256(
            json.dumps(crit_keys).encode("utf-8")
        ).hexdigest()[:32]

        singleton = self._get_singleton()
        prev_fp = singleton.last_issue_fingerprint or ""
        singleton.write(
            {
                "last_run_at": now,
                "last_status": status,
                "last_issue_count": len(issues),
                "last_critical_count": len(critical),
                "last_warning_count": len(warnings),
                "last_result_json": json.dumps(result, default=str)[:50000],
                "last_issue_fingerprint": fingerprint if critical else "",
            }
        )

        _logger.info(
            "whatsapp discuss hub health status=%s issues=%s critical=%s warning=%s "
            "hub=%s allowlist=%s",
            status,
            len(issues),
            len(critical),
            len(warnings),
            hub_channels.ids,
            allow_ids,
        )

        if notify and create_activities and critical and fingerprint != prev_fp:
            self._notify_critical(singleton, critical, fingerprint)
        elif notify and create_activities and critical and fingerprint == prev_fp:
            _logger.info(
                "whatsapp discuss hub health: suppressing duplicate activities "
                "fingerprint=%s",
                fingerprint,
            )

        return result

    @api.model
    def _notify_critical(self, singleton, critical, fingerprint):
        user = self._responsible_user()
        if not user:
            _logger.warning(
                "whatsapp discuss hub health: critical issues but no responsible user; "
                "fingerprint=%s count=%s",
                fingerprint,
                len(critical),
            )
            return
        # Deduplicate: open activities on this record with same fingerprint note
        Activity = self.env["mail.activity"].sudo()
        existing = Activity.search(
            [
                ("res_model", "=", self._name),
                ("res_id", "=", singleton.id),
                ("summary", "ilike", "Discuss Hub Health CRITICAL"),
                ("note", "ilike", fingerprint),
            ],
            limit=1,
        )
        if existing:
            return
        items = "".join(
            f"<li>[{i['type']}] ch={i.get('channel_id')} ref={i.get('ref')}: "
            f"{i['message']}</li>"
            for i in critical[:15]
        )
        note = (
            f"<p>Discuss Hub Health CRITICAL (fingerprint {fingerprint})</p>"
            f"<ul>{items}</ul>"
            f"<p>Do not auto-rollback. See E3 operator runbook.</p>"
        )
        try:
            singleton.activity_schedule(
                "mail.mail_activity_data_todo",
                user_id=user.id,
                summary="Discuss Hub Health CRITICAL",
                note=note,
            )
        except Exception as exc:
            _logger.warning(
                "whatsapp discuss hub health: failed to create activity: %s", exc
            )

    @api.model
    def cron_run_health_check(self):
        return self.service_run_health_check(notify=True, create_activities=True)

    def action_run_health_check(self):
        self.ensure_one()
        result = self.service_run_health_check(notify=True, create_activities=True)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Discuss Hub Health",
                "message": (
                    f"status={result.get('status')} "
                    f"critical={result.get('critical_count')} "
                    f"warning={result.get('warning_count')}"
                ),
                "type": "success" if result.get("status") == "healthy" else "warning",
                "sticky": False,
            },
        }
