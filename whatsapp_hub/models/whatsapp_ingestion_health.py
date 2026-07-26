# -*- coding: utf-8 -*-
"""Inbound WhatsApp Hub ingestion health + gap recovery watchdog."""
from __future__ import annotations

import logging
from datetime import timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

FAILURE_THRESHOLD = 3
LOOKBACK_DAYS = 14


class WhatsappIngestionHealth(models.Model):
    _name = "whatsapp.ingestion.health"
    _description = "WhatsApp Ingestion Health"
    _order = "health_status, last_successful_ingestion_at desc, id desc"
    _rec_name = "display_name"

    display_name = fields.Char(compute="_compute_display_name", store=False)
    conversation_id = fields.Many2one(
        "whatsapp.conversation",
        required=True,
        ondelete="cascade",
        index=True,
    )
    group_jid = fields.Char(
        related="conversation_id.group_id.jid",
        store=True,
        index=True,
        readonly=True,
    )
    remote_jid = fields.Char(
        related="conversation_id.remote_jid",
        store=True,
        index=True,
        readonly=True,
    )
    instance_id = fields.Many2one(
        related="conversation_id.instance_id",
        store=True,
        index=True,
        readonly=True,
    )
    last_provider_event_at = fields.Datetime(index=True)
    last_successful_ingestion_at = fields.Datetime(index=True)
    last_external_message_id = fields.Char()
    last_ingestion_error = fields.Text()
    consecutive_failure_count = fields.Integer(default=0)
    gap_detected = fields.Boolean(default=False, index=True)
    recovery_state = fields.Selection(
        [
            ("idle", "Idle"),
            ("queued", "Queued"),
            ("running", "Running"),
            ("completed", "Completed"),
            ("failed", "Failed"),
        ],
        default="idle",
        required=True,
        index=True,
    )
    health_status = fields.Selection(
        [
            ("healthy", "Healthy"),
            ("idle", "Idle"),
            ("delayed", "Delayed"),
            ("gap_detected", "Gap Detected"),
            ("recovering", "Recovering"),
            ("failed", "Failed"),
            ("unknown", "Unknown"),
        ],
        default="healthy",
        required=True,
        index=True,
    )
    stall_threshold_minutes = fields.Integer(default=30)
    notes = fields.Text()

    _conversation_unique = models.Constraint(
        "unique(conversation_id)",
        "Only one ingestion health row per conversation.",
    )

    @api.depends("conversation_id", "conversation_id.name", "health_status")
    def _compute_display_name(self):
        for rec in self:
            name = rec.conversation_id.name or "Conversation"
            rec.display_name = f"{name} [{rec.health_status or 'healthy'}]"

    @api.model
    def _get_or_create_for_conversation(self, conversation):
        conversation.ensure_one()
        Health = self.sudo()
        existing = Health.search(
            [("conversation_id", "=", conversation.id)], limit=1
        )
        if existing:
            return existing
        return Health.create({"conversation_id": conversation.id})

    def recompute_health_status(self):
        now = fields.Datetime.now()
        for rec in self:
            threshold = int(rec.stall_threshold_minutes or 30)
            last_ok = rec.last_successful_ingestion_at
            last_evt = rec.last_provider_event_at

            # A conversation is only "delayed" when there is positive evidence of
            # newer provider activity we have not yet ingested. Pure age without a
            # fresher provider event just means the chat is inactive -> "idle",
            # not a genuine ingestion problem. Missing all freshness data -> unknown.
            provider_ahead = bool(last_evt and (not last_ok or last_evt > last_ok))
            stale = bool(last_ok and (now - last_ok) > timedelta(minutes=threshold))

            if rec.consecutive_failure_count >= FAILURE_THRESHOLD:
                status = "failed"
            elif rec.recovery_state == "running":
                status = "recovering"
            elif rec.gap_detected:
                status = "gap_detected"
            elif provider_ahead:
                # Provider saw a newer event than our last successful ingest.
                status = "delayed"
            elif not last_ok and not last_evt:
                # No freshness data at all (legacy/stale row, never observed).
                status = "unknown"
            elif stale:
                # Old but no pending provider signal -> inactive conversation.
                status = "idle"
            else:
                status = "healthy"
            if rec.health_status != status:
                rec.health_status = status

    def record_successful_ingest(self, message):
        self.ensure_one()
        message.ensure_one()
        now = fields.Datetime.now()
        external_id = (
            message.evolution_message_id
            or message.provider_message_id
            or (
                str(message.chatwoot_message_id)
                if message.chatwoot_message_id
                else False
            )
        )
        # Watchdog freshness uses ingest wall-clock time (not WA message ts),
        # so delayed webhooks / backfills do not look like immediate gaps.
        vals = {
            "last_successful_ingestion_at": now,
            "last_provider_event_at": now,
            "last_external_message_id": external_id or False,
            "last_ingestion_error": False,
            "consecutive_failure_count": 0,
            "gap_detected": False,
        }
        if self.recovery_state in ("queued", "running"):
            # Keep recovery_state until action_recover finishes; just clear gap.
            pass
        elif self.recovery_state == "failed":
            vals["recovery_state"] = "idle"
        self.write(vals)
        self.recompute_health_status()
        return True

    def record_provider_event(self, external_id=None, event_at=None):
        self.ensure_one()
        event_at = event_at or fields.Datetime.now()
        vals = {
            "last_provider_event_at": event_at,
        }
        if external_id:
            vals["last_external_message_id"] = str(external_id)[:300]
        self.write(vals)
        # Provider substantially ahead of last successful ingest → gap signal
        threshold = int(self.stall_threshold_minutes or 30)
        if (
            self.last_successful_ingestion_at
            and self.last_provider_event_at
            and self.last_provider_event_at
            > self.last_successful_ingestion_at + timedelta(minutes=threshold)
        ):
            self.gap_detected = True
        elif not self.last_successful_ingestion_at and self.last_provider_event_at:
            self.gap_detected = True
        self.recompute_health_status()
        return True

    def record_failure(self, error):
        self.ensure_one()
        err = (error or "").strip()
        if len(err) > 4000:
            err = err[:3980] + "\n...[truncated]..."
        count = int(self.consecutive_failure_count or 0) + 1
        vals = {
            "consecutive_failure_count": count,
            "last_ingestion_error": err or False,
        }
        if count >= FAILURE_THRESHOLD:
            vals["health_status"] = "failed"
        self.write(vals)
        self.recompute_health_status()
        return True

    def _should_flag_gap_or_delay(self):
        self.ensure_one()
        threshold = int(self.stall_threshold_minutes or 30)
        last_ok = self.last_successful_ingestion_at
        last_evt = self.last_provider_event_at
        # "delayed" requires positive evidence of newer, un-ingested provider
        # activity. Age alone (inactive chat) is NOT actionable and must not
        # trigger recovery — that path only reacts to real provider-ahead signals.
        delayed = bool(last_evt and (not last_ok or last_evt > last_ok))
        gap = False
        if last_evt and last_ok and last_evt > last_ok + timedelta(minutes=threshold):
            gap = True
        elif last_evt and not last_ok:
            gap = True
        return delayed, gap

    @api.model
    def cron_watchdog(self):
        """Scan active conversations for stalled/gap ingestion and optionally recover."""
        Health = self.sudo()
        Conversation = self.env["whatsapp.conversation"].sudo()
        Message = self.env["whatsapp.message"].sudo()
        ICP = self.env["ir.config_parameter"].sudo()
        auto_recover = (
            ICP.get_param("whatsapp_hub.auto_recover_gaps", "False") or ""
        ).strip().lower() in ("1", "true", "yes", "on")

        since = fields.Datetime.now() - timedelta(days=LOOKBACK_DAYS)
        recent_msgs = Message.read_group(
            [("message_timestamp", ">=", since), ("conversation_id", "!=", False)],
            ["conversation_id"],
            ["conversation_id"],
        )
        conv_ids = {
            row["conversation_id"][0]
            for row in recent_msgs
            if row.get("conversation_id")
        }
        existing_health = Health.search([])
        conv_ids.update(existing_health.mapped("conversation_id").ids)

        conversations = Conversation.search(
            [("id", "in", list(conv_ids)), ("active", "=", True)]
        )
        checked = 0
        flagged = 0
        queued = 0
        for conv in conversations:
            health = Health._get_or_create_for_conversation(conv)
            # Seed last_successful from latest message if empty
            if not health.last_successful_ingestion_at:
                latest = Message.search(
                    [("conversation_id", "=", conv.id)],
                    order="message_timestamp desc, id desc",
                    limit=1,
                )
                if latest:
                    health.last_successful_ingestion_at = latest.message_timestamp
                    health.last_external_message_id = (
                        latest.evolution_message_id
                        or latest.provider_message_id
                        or False
                    )
            delayed, gap = health._should_flag_gap_or_delay()
            vals = {}
            if gap and not health.gap_detected:
                vals["gap_detected"] = True
            if vals:
                health.write(vals)
            health.recompute_health_status()
            checked += 1
            if gap or delayed or health.health_status in (
                "gap_detected",
                "delayed",
                "failed",
            ):
                flagged += 1
                if (
                    auto_recover
                    and health.recovery_state in ("idle", "completed", "failed")
                    and health.health_status in ("gap_detected", "delayed", "failed")
                ):
                    health.recovery_state = "queued"
                    try:
                        health.action_recover_missing_messages()
                        queued += 1
                    except Exception:
                        _logger.exception(
                            "whatsapp_hub ingestion health auto-recover failed "
                            "conversation=%s",
                            conv.id,
                        )
        _logger.info(
            "whatsapp_hub ingestion health cron checked=%s flagged=%s queued=%s",
            checked,
            flagged,
            queued,
        )
        return {"checked": checked, "flagged": flagged, "queued": queued}

    def action_recover_missing_messages(self):
        """Pull missing messages from Evolution for this conversation."""
        self.ensure_one()
        Recovery = self.env["whatsapp.evolution.recovery"].sudo()
        self.write({"recovery_state": "running", "gap_detected": True})
        self.recompute_health_status()
        try:
            result = Recovery.recover_conversation(self.conversation_id)
            errors = result.get("errors") or []
            if errors and not (result.get("created") or result.get("existing")):
                self.write(
                    {
                        "recovery_state": "failed",
                        "last_ingestion_error": "; ".join(str(e) for e in errors[:5]),
                        "consecutive_failure_count": max(
                            int(self.consecutive_failure_count or 0), FAILURE_THRESHOLD
                        ),
                    }
                )
            else:
                notes = (
                    f"Recovery: created={result.get('created', 0)} "
                    f"existing={result.get('existing', 0)} "
                    f"errors={len(errors)}"
                )
                self.write(
                    {
                        "recovery_state": "completed",
                        "gap_detected": False,
                        "consecutive_failure_count": 0,
                        "last_ingestion_error": (
                            "; ".join(str(e) for e in errors[:5]) if errors else False
                        ),
                        "notes": notes,
                        "last_successful_ingestion_at": fields.Datetime.now(),
                    }
                )
            self.recompute_health_status()
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": "Recovery finished",
                    "message": (
                        f"created={result.get('created', 0)} "
                        f"existing={result.get('existing', 0)} "
                        f"errors={len(errors)}"
                    ),
                    "type": "success" if not errors else "warning",
                    "sticky": False,
                },
            }
        except Exception as exc:
            _logger.exception(
                "whatsapp_hub recovery failed conversation=%s", self.conversation_id.id
            )
            self.write(
                {
                    "recovery_state": "failed",
                    "last_ingestion_error": str(exc)[:4000],
                    "consecutive_failure_count": max(
                        int(self.consecutive_failure_count or 0) + 1, FAILURE_THRESHOLD
                    ),
                }
            )
            self.recompute_health_status()
            raise
