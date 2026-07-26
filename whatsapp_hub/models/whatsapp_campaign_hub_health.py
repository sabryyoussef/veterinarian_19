# -*- coding: utf-8 -*-
"""P5E: read-only Campaign Hub health checks (no routing mutations)."""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


def _icp_int(env, key, default):
    raw = (env["ir.config_parameter"].sudo().get_param(key) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _icp_bool(env, key, default=False):
    raw = (env["ir.config_parameter"].sudo().get_param(key) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def _parse_campaign_allowlist(env):
    raw = (
        env["ir.config_parameter"]
        .sudo()
        .get_param("whatsapp_hub.campaign_hub_allowed_campaign_ids")
        or ""
    ).strip()
    if not raw:
        return None
    ids = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if not part.isdigit():
            return False
        ids.append(int(part))
    return ids


def _body_hash(text):
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


class WhatsappCampaignHubHealth(models.Model):
    _name = "whatsapp.campaign.hub.health"
    _description = "Campaign Hub Health Status"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _rec_name = "display_name"

    display_name = fields.Char(default="Campaign Hub Health", readonly=True)
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
    last_issue_fingerprint = fields.Char(readonly=True)
    active = fields.Boolean(default=True)

    # Fairness metrics (last run)
    pending_campaign_jobs = fields.Integer(readonly=True)
    pending_discuss_jobs = fields.Integer(readonly=True)
    oldest_campaign_pending_minutes = fields.Integer(readonly=True)
    oldest_discuss_pending_minutes = fields.Integer(readonly=True)

    @api.model
    def _get_singleton(self):
        rec = self.sudo().search([], limit=1)
        if not rec:
            rec = self.sudo().create({"display_name": "Campaign Hub Health"})
        return rec

    @api.model
    def _responsible_user(self):
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
    def service_run_health_check(self, notify=True, create_activities=True):
        """
        Read-only Campaign Hub health scan.

        Never sends, retries, quarantines, or mutates Campaign/Discuss flags.
        """
        Out = self.env["whatsapp.outbound.message"].sudo()
        Message = self.env["whatsapp.message"].sudo()
        # NOTE: empty Odoo recordsets are falsy — never use `if Model:` to gate presence.
        has_log = "wa.message.log" in self.env
        has_campaign = "wa.campaign" in self.env
        has_line = "wa.campaign.line" in self.env
        Log = self.env["wa.message.log"].sudo() if has_log else None
        Campaign = self.env["wa.campaign"].sudo() if has_campaign else None
        Line = self.env["wa.campaign.line"].sudo() if has_line else None
        now = fields.Datetime.now()
        issues = []

        stale_m = _icp_int(self.env, "whatsapp_hub.campaign_health_stale_minutes", 30)
        stuck_m = _icp_int(
            self.env, "whatsapp_hub.campaign_health_stuck_processing_minutes", 15
        )
        pending_warn = _icp_int(self.env, "whatsapp_hub.campaign_health_pending_warn", 15)
        starve_m = _icp_int(self.env, "whatsapp_hub.discuss_starvation_minutes", 10)
        max_pending = _icp_int(self.env, "whatsapp_hub.max_pending_campaign_jobs", 100)
        cutover_on = _icp_bool(self.env, "whatsapp_hub.campaign_cutover_enabled", False)

        allow_raw = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("whatsapp_hub.campaign_hub_allowed_campaign_ids")
            or ""
        )
        allow = _parse_campaign_allowlist(self.env)
        if allow is False:
            issues.append(
                {
                    "severity": "critical",
                    "type": "allowlist_malformed",
                    "campaign_id": False,
                    "ref": allow_raw,
                    "message": "campaign_hub_allowed_campaign_ids is malformed",
                    "action": "Fix ICP to comma-separated integers",
                }
            )
            allow_ids = []
        elif allow is None:
            allow_ids = []
        else:
            allow_ids = list(allow)
        allow_set = set(allow_ids)

        hub_campaigns = (
            Campaign.search([("wa_outbound_mode", "=", "hub")]) if has_campaign else []
        )
        Routing = (
            self.env["whatsapp.campaign.hub.routing"]
            if "whatsapp.campaign.hub.routing" in self.env
            else None
        )

        # 1) Active Hub Campaign must be allowlisted (admission-capable only)
        #    Allowlist = currently authorized to admit NEW Hub jobs (P5F-A).
        #    Completed/cancelled historical Hub Campaigns may leave allowlist safely.
        for camp in hub_campaigns:
            admission_capable = False
            if Routing:
                admission_capable = Routing.campaign_is_admission_capable(camp)
            else:
                admission_capable = camp.state not in ("completed", "cancelled")
            if admission_capable and camp.id not in allow_set:
                issues.append(
                    {
                        "severity": "critical",
                        "type": "hub_not_allowlisted",
                        "campaign_id": camp.id,
                        "ref": camp.id,
                        "message": (
                            f"Active Hub Campaign {camp.id} is not in allowlist "
                            f"(state={camp.state})"
                        ),
                        "action": "Add to allowlist or set mode to shadow/legacy",
                    }
                )

        # 1b) Completed/cancelled still allowlisted → cleanup warning
        for cid in allow_ids:
            if not has_campaign:
                break
            camp = Campaign.browse(cid)
            if camp.exists() and camp.state in ("completed", "cancelled"):
                issues.append(
                    {
                        "severity": "warning",
                        "type": "completed_campaign_still_allowlisted",
                        "campaign_id": cid,
                        "ref": cid,
                        "message": (
                            f"Campaign {cid} is {camp.state} but still on Hub allowlist"
                        ),
                        "action": "Remove from active allowlist (preserve Hub history)",
                    }
                )

        # 2) Allowlisted IDs exist
        for cid in allow_ids:
            if not has_campaign:
                break
            camp = Campaign.browse(cid)
            if not camp.exists():
                issues.append(
                    {
                        "severity": "critical",
                        "type": "allowlist_missing_campaign",
                        "campaign_id": cid,
                        "ref": cid,
                        "message": f"Allowlisted campaign {cid} does not exist",
                        "action": "Remove from allowlist",
                    }
                )

        # Active Hub jobs (pending/processing) — always check; historical sent ignored for allowlist
        active_jobs = Out.search(
            [
                ("purpose", "=", "campaign"),
                ("transport_mode", "=", "unified_bridge"),
                ("state", "in", ("pending", "processing")),
            ]
        )
        # 3) Outside allowlist — only while Campaign Hub control plane is active
        #    OR whenever active incomplete jobs exist for non-allowlisted campaigns
        if cutover_on or allow_ids:
            for job in active_jobs:
                cid = job.campaign_id if isinstance(job.campaign_id, int) else (
                    job.campaign_id.id if job.campaign_id else False
                )
                if cid and cid not in allow_set:
                    issues.append(
                        {
                            "severity": "critical",
                            "type": "job_outside_allowlist",
                            "campaign_id": cid,
                            "ref": job.id,
                            "message": f"Campaign Hub job {job.id} campaign={cid} outside allowlist",
                            "action": "Quarantine job or fix allowlist",
                        }
                    )
        elif active_jobs and not allow_ids and not cutover_on:
            # Control plane OFF with leftover incomplete jobs
            issues.append(
                {
                    "severity": "warning",
                    "type": "orphan_active_campaign_jobs",
                    "campaign_id": False,
                    "ref": active_jobs.ids[:10],
                    "message": f"{len(active_jobs)} pending/processing Campaign Hub jobs while cutover OFF",
                    "action": "Quarantine incomplete Campaign jobs",
                }
            )

        # Fairness metrics
        discuss_pending = Out.search(
            [
                ("purpose", "=", "discuss"),
                ("transport_mode", "=", "unified_bridge"),
                ("state", "in", ("pending", "processing")),
            ],
            order="create_date asc, id asc",
        )
        camp_pending = active_jobs
        oldest_camp_mins = 0
        oldest_disc_mins = 0
        if camp_pending:
            oldest = min(camp_pending.mapped("create_date"))
            oldest_camp_mins = int((now - oldest).total_seconds() // 60) if oldest else 0
        if discuss_pending:
            oldest = min(discuss_pending.mapped("create_date"))
            oldest_disc_mins = int((now - oldest).total_seconds() // 60) if oldest else 0

        # 4–5) Stale / stuck
        stale_cut = now - timedelta(minutes=stale_m)
        stuck_cut = now - timedelta(minutes=stuck_m)
        for job in active_jobs:
            age_base = job.write_date or job.create_date
            if job.state == "processing" and not (job.evolution_message_id or "").strip():
                if age_base and age_base < stuck_cut:
                    issues.append(
                        {
                            "severity": "critical",
                            "type": "stuck_processing_no_provider",
                            "campaign_id": job.campaign_id,
                            "ref": job.id,
                            "message": f"Job {job.id} processing without provider ID >{stuck_m}m",
                            "action": "Reconcile uncertain job; do not auto-resend",
                        }
                    )
            elif age_base and age_base < stale_cut:
                issues.append(
                    {
                        "severity": "warning",
                        "type": "stale_pending",
                        "campaign_id": job.campaign_id,
                        "ref": job.id,
                        "message": f"Job {job.id} pending/processing older than {stale_m}m",
                        "action": "Inspect outbound worker / provider",
                    }
                )

        # 6–7) Duplicate business keys / provider IDs among Campaign Hub jobs (recent window)
        lookback = now - timedelta(days=7)
        recent_jobs = Out.search(
            [
                ("purpose", "=", "campaign"),
                ("transport_mode", "=", "unified_bridge"),
                ("create_date", ">=", lookback),
            ]
        )
        by_biz = {}
        by_prov = {}
        for job in recent_jobs:
            biz = (job.business_key or "").strip()
            if biz:
                by_biz.setdefault(biz, []).append(job.id)
            prov = (job.evolution_message_id or "").strip()
            if prov:
                by_prov.setdefault(prov, []).append(job.id)
        for biz, ids in by_biz.items():
            if len(ids) > 1:
                issues.append(
                    {
                        "severity": "critical",
                        "type": "duplicate_business_key",
                        "campaign_id": False,
                        "ref": biz,
                        "message": f"Duplicate Campaign business_key {biz} jobs={ids}",
                        "action": "Investigate identity collision",
                    }
                )
        for prov, ids in by_prov.items():
            if len(ids) > 1:
                issues.append(
                    {
                        "severity": "critical",
                        "type": "duplicate_provider_id",
                        "campaign_id": False,
                        "ref": prov,
                        "message": f"Duplicate provider ID {prov} jobs={ids}",
                        "action": "Investigate duplicate send",
                    }
                )

        # 8) Legacy leakage on CURRENT Hub-mode Campaigns only
        for camp in hub_campaigns:
            if has_log:
                legacy_logs = Log.search(
                    [
                        ("campaign_id", "=", camp.id),
                        ("send_origin", "=", "legacy"),
                        ("create_date", ">=", lookback),
                    ],
                    limit=5,
                )
                # Only flag if campaign also has hub_unified activity (Hub-active boundary)
                hub_logs = Log.search(
                    [
                        ("campaign_id", "=", camp.id),
                        ("send_origin", "=", "hub_unified"),
                    ],
                    limit=1,
                )
                if legacy_logs and hub_logs:
                    issues.append(
                        {
                            "severity": "critical",
                            "type": "legacy_leakage",
                            "campaign_id": camp.id,
                            "ref": legacy_logs.ids,
                            "message": f"Hub-mode Campaign {camp.id} has recent legacy send_origin logs",
                            "action": "Stop Hub Campaign; investigate dual path",
                        }
                    )
            if "integration.outbound.queue" in self.env and has_line:
                q_lines = Line.search(
                    [
                        ("campaign_id", "=", camp.id),
                        ("queue_id", "!=", False),
                        ("hub_outbound_id", "!=", False),
                    ],
                    limit=5,
                )
                if q_lines:
                    issues.append(
                        {
                            "severity": "critical",
                            "type": "legacy_bridge_leakage",
                            "campaign_id": camp.id,
                            "ref": q_lines.ids,
                            "message": f"Hub-linked lines also have bridge queue_id on Campaign {camp.id}",
                            "action": "Investigate dual queue",
                        }
                    )

        # 9–12) Lifecycle / Hub refs for Hub-linked lines (active Hub campaigns + recent hub jobs)
        hub_linked_lines = (
            Line.search(
                [
                    "|",
                    ("hub_message_id", "!=", False),
                    ("hub_outbound_id", "!=", False),
                ]
            )
            if has_line
            else []
        )
        # Limit to lines whose campaign is hub OR has recent hub_unified (avoid pure historical noise)
        for line in hub_linked_lines:
            camp = line.campaign_id
            is_active_hub = camp and camp.wa_outbound_mode == "hub"
            job = Out.browse(line.hub_outbound_id) if line.hub_outbound_id else Out.browse()
            msg = Message.browse(line.hub_message_id) if line.hub_message_id else Message.browse()

            if line.hub_outbound_id and (not job or not job.exists()):
                if is_active_hub:
                    issues.append(
                        {
                            "severity": "critical",
                            "type": "missing_hub_outbound",
                            "campaign_id": camp.id,
                            "ref": line.id,
                            "message": f"Line {line.id} hub_outbound_id={line.hub_outbound_id} missing",
                            "action": "Reconcile line Hub refs",
                        }
                    )
                continue
            if line.hub_message_id and (not msg or not msg.exists()):
                if is_active_hub:
                    issues.append(
                        {
                            "severity": "critical",
                            "type": "missing_hub_message",
                            "campaign_id": camp.id,
                            "ref": line.id,
                            "message": f"Line {line.id} hub_message_id={line.hub_message_id} missing",
                            "action": "Reconcile line Hub refs",
                        }
                    )
                continue

            if not job or not job.exists():
                continue

            # Lifecycle divergence — active Hub campaigns only (avoid historical P5D noise)
            if is_active_hub:
                if line.status == "sent" and job.state != "sent":
                    issues.append(
                        {
                            "severity": "critical",
                            "type": "line_sent_job_not_sent",
                            "campaign_id": camp.id if camp else False,
                            "ref": line.id,
                            "message": f"Line {line.id} sent but Hub job {job.id} state={job.state}",
                            "action": "Reconcile projection",
                        }
                    )
                if job.state == "sent" and line.status not in (
                    "sent",
                    "delivered",
                    "read",
                ):
                    issues.append(
                        {
                            "severity": "critical",
                            "type": "job_sent_line_not_sent",
                            "campaign_id": camp.id if camp else False,
                            "ref": line.id,
                            "message": f"Hub job {job.id} sent but line {line.id} status={line.status}",
                            "action": "Re-project line from outbound",
                        }
                    )

            # Compat gap for Hub-first (hub_unified expected when job sent)
            if has_log and job.state == "sent" and is_active_hub:
                clog = Log.search(
                    [
                        ("campaign_line_id", "=", line.id),
                        ("send_origin", "=", "hub_unified"),
                    ],
                    limit=1,
                )
                if not clog:
                    issues.append(
                        {
                            "severity": "warning",
                            "type": "compat_log_missing",
                            "campaign_id": camp.id,
                            "ref": line.id,
                            "message": f"No hub_unified wa.message.log for Hub-sent line {line.id}",
                            "action": "Inspect Hub compatibility logging",
                        }
                    )
                elif clog.hub_message_id and line.hub_message_id and clog.hub_message_id.id != line.hub_message_id:
                    issues.append(
                        {
                            "severity": "critical",
                            "type": "compat_hub_message_mismatch",
                            "campaign_id": camp.id,
                            "ref": line.id,
                            "message": f"Compat log hub_message_id mismatch for line {line.id}",
                            "action": "Investigate convergence",
                        }
                    )

            # walog twin for Hub-first campaign business key
            if msg and msg.exists() and (msg.business_key or "").startswith("campaign:"):
                # Any walog twin pointing at same campaign line is unexpected for Hub-first
                pass
            if has_log and job.state == "sent" and msg and msg.exists():
                # Search walog keys that mirror same provider
                if job.evolution_message_id:
                    twins = Message.search(
                        [
                            ("business_key", "=like", "walog:%"),
                            ("campaign_line_id", "=", line.id),
                        ],
                        limit=3,
                    )
                    # campaign_line_id may be Integer on message
                    if not twins and hasattr(Message, "campaign_line_id"):
                        twins = Message.search(
                            [
                                ("business_key", "=like", "walog:%"),
                                ("related_model", "=", "wa.campaign.line"),
                                ("related_res_id", "=", line.id),
                            ],
                            limit=3,
                        )
                    if twins and is_active_hub:
                        issues.append(
                            {
                                "severity": "critical",
                                "type": "walog_twin",
                                "campaign_id": camp.id,
                                "ref": twins.ids,
                                "message": f"walog:* twin(s) for Hub Campaign line {line.id}",
                                "action": "Investigate mirror twin creation",
                            }
                        )

            # 16) Render hash mismatch — only when freeze lock is present on active Hub
            if (
                is_active_hub
                and getattr(line, "rendered_locked", False)
                and line.rendered_body_hash
                and msg
                and msg.exists()
            ):
                msg_hash = _body_hash(msg.body or "")
                if msg_hash != line.rendered_body_hash:
                    issues.append(
                        {
                            "severity": "critical",
                            "type": "render_hash_mismatch",
                            "campaign_id": camp.id if camp else False,
                            "ref": line.id,
                            "message": f"Line {line.id} frozen hash != Hub message body hash",
                            "action": "Do not re-send; investigate payload mutation",
                        }
                    )
                if job.body is not None and _body_hash(job.body or "") != line.rendered_body_hash:
                    issues.append(
                        {
                            "severity": "critical",
                            "type": "render_hash_mismatch_outbound",
                            "campaign_id": camp.id if camp else False,
                            "ref": line.id,
                            "message": f"Line {line.id} frozen hash != Hub outbound body hash",
                            "action": "Investigate outbound payload",
                        }
                    )

        # 13–14) Pending volume / backpressure
        pend_count = len(camp_pending)
        if pend_count >= pending_warn:
            issues.append(
                {
                    "severity": "warning",
                    "type": "pending_volume",
                    "campaign_id": False,
                    "ref": pend_count,
                    "message": f"Campaign Hub pending/processing={pend_count} >= warn {pending_warn}",
                    "action": "Pause new Campaign admits; drain queue",
                }
            )
        if pend_count >= max_pending:
            issues.append(
                {
                    "severity": "warning",
                    "type": "backpressure",
                    "campaign_id": False,
                    "ref": pend_count,
                    "message": f"Campaign pending {pend_count} >= max_pending {max_pending}",
                    "action": "Backpressure active; stop admits until drain",
                }
            )

        # 15) Discuss starvation warning
        if oldest_disc_mins >= starve_m and pend_count > 0:
            issues.append(
                {
                    "severity": "warning",
                    "type": "discuss_starvation",
                    "campaign_id": False,
                    "ref": oldest_disc_mins,
                    "message": (
                        f"Discuss pending age {oldest_disc_mins}m while Campaign pending={pend_count}"
                    ),
                    "action": "Pause Campaign admits; verify Discuss drain",
                }
            )

        # 17) Failure rate (recent sent+failed)
        recent_done = Out.search(
            [
                ("purpose", "=", "campaign"),
                ("transport_mode", "=", "unified_bridge"),
                ("state", "in", ("sent", "failed")),
                ("write_date", ">=", now - timedelta(hours=24)),
            ]
        )
        if len(recent_done) >= 5:
            failed_n = len(recent_done.filtered(lambda j: j.state == "failed"))
            rate = failed_n / float(len(recent_done))
            if rate >= 0.20:
                issues.append(
                    {
                        "severity": "warning",
                        "type": "elevated_failure_rate",
                        "campaign_id": False,
                        "ref": round(rate, 2),
                        "message": f"Campaign Hub 24h failure rate {rate:.0%} ({failed_n}/{len(recent_done)})",
                        "action": "Inspect provider errors; pause Hub Campaigns",
                    }
                )

        critical = [i for i in issues if i["severity"] == "critical"]
        warning = [i for i in issues if i["severity"] == "warning"]
        if critical:
            status = "critical"
        elif warning:
            status = "warning"
        else:
            status = "healthy"

        crit_keys = sorted(
            f"{i['type']}:{i.get('campaign_id')}:{i.get('ref')}" for i in critical
        )
        fingerprint = (
            hashlib.sha256("|".join(crit_keys).encode("utf-8")).hexdigest()[:16]
            if crit_keys
            else ""
        )

        result = {
            "ok": status == "healthy",
            "status": status,
            "run_at": fields.Datetime.to_string(now),
            "issue_count": len(issues),
            "critical_count": len(critical),
            "warning_count": len(warning),
            "issues": issues,
            "fingerprint": fingerprint,
            "campaign_cutover_enabled": cutover_on,
            "allowlist": allow_ids,
            "allowlisted_campaign_count": len(allow_ids),
            "active_hub_campaign_count": len(
                [
                    c
                    for c in (hub_campaigns or [])
                    if Routing and Routing.campaign_is_admission_capable(c)
                ]
            )
            if Routing
            else len(
                [
                    c
                    for c in (hub_campaigns or [])
                    if c.state not in ("completed", "cancelled")
                ]
            ),
            "pending_campaign_jobs": pend_count,
            "pending_discuss_jobs": len(discuss_pending),
            "oldest_campaign_pending_minutes": oldest_camp_mins,
            "oldest_discuss_pending_minutes": oldest_disc_mins,
        }

        singleton = self._get_singleton()
        singleton.write(
            {
                "last_run_at": now,
                "last_status": status,
                "last_issue_count": len(issues),
                "last_critical_count": len(critical),
                "last_warning_count": len(warning),
                "last_result_json": json.dumps(result, default=str)[:50000],
                "last_issue_fingerprint": fingerprint or False,
                "pending_campaign_jobs": pend_count,
                "pending_discuss_jobs": len(discuss_pending),
                "oldest_campaign_pending_minutes": oldest_camp_mins,
                "oldest_discuss_pending_minutes": oldest_disc_mins,
            }
        )

        _logger.info(
            "whatsapp campaign hub health: status=%s critical=%s warning=%s fingerprint=%s",
            status,
            len(critical),
            len(warning),
            fingerprint or "-",
        )

        if notify and create_activities and critical:
            self._notify_critical(singleton, critical, fingerprint)

        return result

    @api.model
    def _notify_critical(self, singleton, critical, fingerprint):
        user = self._responsible_user()
        if not user:
            # Fall back to superuser / admin so Test/Prod always get an activity
            user = self.env.ref("base.user_admin", raise_if_not_found=False)
        if not user or not user.active:
            _logger.warning(
                "campaign hub health: critical but no responsible user fingerprint=%s",
                fingerprint,
            )
            return
        Activity = self.env["mail.activity"].sudo()
        existing = Activity.search(
            [
                ("res_model", "=", self._name),
                ("res_id", "=", singleton.id),
                ("summary", "ilike", "Campaign Hub Health CRITICAL"),
                ("note", "ilike", fingerprint),
            ],
            limit=1,
        )
        if existing:
            return
        items = "".join(
            f"<li>[{i['type']}] camp={i.get('campaign_id')} ref={i.get('ref')}: "
            f"{i['message']}</li>"
            for i in critical[:15]
        )
        note = (
            f"<p>Campaign Hub Health CRITICAL (fingerprint {fingerprint})</p>"
            f"<ul>{items}</ul>"
            f"<p>Do not auto-rollback. See P5E operator design.</p>"
        )
        try:
            singleton.activity_schedule(
                "mail.mail_activity_data_todo",
                user_id=user.id,
                summary="Campaign Hub Health CRITICAL",
                note=note,
            )
        except Exception as exc:
            _logger.warning("campaign hub health: activity failed: %s", exc)
            # Fallback create without schedule helper
            try:
                act_type = self.env.ref("mail.mail_activity_data_todo")
                Activity.create(
                    {
                        "activity_type_id": act_type.id,
                        "res_model_id": self.env["ir.model"]
                        ._get(self._name)
                        .id,
                        "res_id": singleton.id,
                        "user_id": user.id,
                        "summary": "Campaign Hub Health CRITICAL",
                        "note": note,
                    }
                )
            except Exception as exc2:
                _logger.warning(
                    "campaign hub health: activity create failed: %s", exc2
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
                "title": "Campaign Hub Health",
                "message": (
                    f"status={result.get('status')} "
                    f"critical={result.get('critical_count')} "
                    f"warning={result.get('warning_count')}"
                ),
                "type": "success" if result.get("status") == "healthy" else "warning",
                "sticky": False,
            },
        }
