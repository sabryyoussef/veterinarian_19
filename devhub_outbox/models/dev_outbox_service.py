# -*- coding: utf-8 -*-
"""Guarded service APIs for n8n outbox and Dify draft generation."""

from datetime import timedelta
import json
import uuid

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import html2plaintext

from odoo.addons.devhub_work.models.dev_work import (
    _bounded,
    _canonical_hash,
    _clean_text,
    _context_text,
    _validated_json,
)


def _uuid(*_args):
    return str(uuid.uuid4())


def _require_outbox_service(env):
    if not env.is_superuser() and not env.user.has_group(
        "devhub_core.group_dev_hub_integration"
    ):
        raise AccessError("This operation requires the scoped Dev Hub outbox role.")


def _require_generation_service(env):
    if not env.is_superuser() and not env.user.has_group(
        "devhub_core.group_dev_hub_generation"
    ):
        raise AccessError("This operation requires the scoped Dev Hub generation role.")


def _lease_expiry(seconds):
    seconds = max(30, min(int(seconds or 300), 1800))
    return fields.Datetime.now() + timedelta(seconds=seconds)


class DevExternalOutbox(models.Model):
    _inherit = "dev.external.outbox"

    state = fields.Selection(
        selection_add=[
            ("leased", "Leased"),
            ("processing", "Processing"),
            ("uncertain_delivery", "Delivery Pending Confirmation"),
        ],
        ondelete={
            "leased": "set default",
            "processing": "set default",
            "uncertain_delivery": "set default",
        },
    )
    correlation_id = fields.Char(
        required=True, default=_uuid, readonly=True, copy=False, index=True
    )
    communication_id = fields.Many2one(
        "dev.work.communication", ondelete="restrict", readonly=True, index=True
    )
    lease_owner_id = fields.Many2one("res.users", readonly=True, index=True)
    lease_consumer_ref = fields.Char(readonly=True)
    lease_token = fields.Char(readonly=True, copy=False, index=True)
    lease_version = fields.Integer(default=0, required=True, readonly=True)
    leased_at = fields.Datetime(readonly=True)
    lease_expires_at = fields.Datetime(readonly=True, index=True)
    processing_at = fields.Datetime(readonly=True)
    reconciliation_required = fields.Boolean(default=False, readonly=True, index=True)
    max_attempts = fields.Integer(default=5, required=True, readonly=True)

    def _recover_expired_leases(self):
        now = fields.Datetime.now()
        leased = self.sudo().search(
            [("state", "=", "leased"), ("lease_expires_at", "<=", now)]
        )
        for record in leased:
            exhausted = record.attempt_count >= record.max_attempts
            record.with_context(dev_outbox_action=True).write(
                {
                    "state": (
                        "dead_letter"
                        if exhausted
                        else (
                            "uncertain_delivery"
                            if record.reconciliation_required
                            else "retry"
                        )
                    ),
                    "next_attempt_at": now,
                    "lease_owner_id": False,
                    "lease_consumer_ref": False,
                    "lease_token": False,
                    "lease_expires_at": False,
                    "completed_at": now if exhausted else False,
                    "last_error_code": "lease_expired",
                    "last_error_summary": (
                        "Reconciliation lease expired; manual review is required."
                        if exhausted
                        else "Lease expired before dispatch started."
                    ),
                }
            )
        processing = self.sudo().search(
            [("state", "=", "processing"), ("lease_expires_at", "<=", now)]
        )
        if processing:
            processing.with_context(dev_outbox_action=True).write(
                {
                    "state": "uncertain_delivery",
                    "next_attempt_at": now + timedelta(seconds=60),
                    "lease_owner_id": False,
                    "lease_consumer_ref": False,
                    "lease_token": False,
                    "lease_expires_at": False,
                    "reconciliation_required": True,
                    "last_error_code": "dispatch_outcome_unknown",
                    "last_error_summary": (
                        "Processing lease expired after dispatch began; provider "
                        "reconciliation is required and resend is prohibited."
                    ),
                }
            )

    @api.model
    def service_lease(
        self, limit=10, lease_seconds=300, consumer_ref=None, correlation_id=None
    ):
        _require_outbox_service(self.env)
        self._recover_expired_leases()
        consumer_ref = _clean_text(consumer_ref, "Consumer reference", 120)
        limit = max(1, min(int(limit or 10), 50))
        now = fields.Datetime.now()
        if correlation_id:
            correlation_id = _clean_text(correlation_id, "Correlation ID", 120)
            self.env.cr.execute(
                """
                    SELECT id
                      FROM dev_external_outbox
                     WHERE correlation_id = %s
                       AND state IN ('pending', 'retry', 'uncertain_delivery')
                       AND (
                            (channel = 'chatwoot' AND operation = 'public_message')
                            OR (channel = 'openproject' AND operation = 'milestone')
                       )
                       AND next_attempt_at <= %s
                       AND attempt_count < max_attempts
                     ORDER BY next_attempt_at, id
                     FOR UPDATE SKIP LOCKED
                     LIMIT 1
                """,
                [correlation_id, now],
            )
        else:
            self.env.cr.execute(
                """
                    SELECT id
                      FROM dev_external_outbox
                     WHERE state IN ('pending', 'retry', 'uncertain_delivery')
                       AND (
                            (channel = 'chatwoot' AND operation = 'public_message')
                            OR (channel = 'openproject' AND operation = 'milestone')
                       )
                       AND next_attempt_at <= %s
                       AND attempt_count < max_attempts
                     ORDER BY next_attempt_at, id
                     FOR UPDATE SKIP LOCKED
                     LIMIT %s
                """,
                [now, limit],
            )
        records = self.sudo().browse([row[0] for row in self.env.cr.fetchall()])
        result = []
        for record in records:
            lease_token = _uuid()
            reconcile_only = (
                record.state == "uncertain_delivery"
                or record.reconciliation_required
            )
            record.with_context(dev_outbox_action=True).write(
                {
                    "state": "leased",
                    "attempt_count": record.attempt_count + 1,
                    "last_attempt_at": now,
                    "lease_owner_id": self.env.user.id,
                    "lease_consumer_ref": consumer_ref,
                    "lease_token": lease_token,
                    "lease_version": record.lease_version + 1,
                    "leased_at": now,
                    "lease_expires_at": _lease_expiry(lease_seconds),
                    "last_error_code": False,
                    "last_error_summary": False,
                }
            )
            result.append(
                {
                    "id": record.id,
                    "correlation_id": record.correlation_id,
                    "lease_token": lease_token,
                    "lease_version": record.lease_version,
                    "idempotency_key": record.idempotency_key,
                    "channel": record.channel,
                    "operation": record.operation,
                    "payload": json.loads(record.payload_json),
                    "attempt": record.attempt_count,
                    "reconcile_only": reconcile_only,
                    "lease_expires_at": fields.Datetime.to_string(
                        record.lease_expires_at
                    ),
                }
            )
        return result

    def _service_record(self, record_id, correlation_id, lease_token):
        _require_outbox_service(self.env)
        record = self.sudo().browse(int(record_id)).exists()
        if not record or record.correlation_id != correlation_id:
            raise AccessError("Unknown outbox correlation.")
        if record.lease_owner_id.id != self.env.user.id:
            raise AccessError("The outbox lease belongs to another service identity.")
        if not lease_token or record.lease_token != lease_token:
            raise AccessError("The outbox lease token is stale or invalid.")
        if not record.lease_expires_at or record.lease_expires_at <= fields.Datetime.now():
            raise AccessError("The outbox lease has expired.")
        return record

    @api.model
    def service_mark_processing(self, record_id, correlation_id, lease_token):
        record = self._service_record(record_id, correlation_id, lease_token)
        if record.state == "processing":
            raise AccessError("Dispatch permission was already consumed for this lease.")
        if record.state != "leased":
            raise UserError("Only a leased outbox intent can start processing.")
        record.with_context(dev_outbox_action=True).write(
            {"state": "processing", "processing_at": fields.Datetime.now()}
        )
        return True

    @api.model
    def service_ack_success(
        self, record_id, correlation_id, lease_token=None, result=None
    ):
        _require_outbox_service(self.env)
        record = self.sudo().browse(int(record_id)).exists()
        if not record or record.correlation_id != correlation_id:
            raise AccessError("Unknown outbox correlation.")
        if record.state == "done":
            return {"state": "done", "external_reference": record.external_reference}
        record = self._service_record(record_id, correlation_id, lease_token)
        if record.state != "processing":
            raise UserError("Success requires the explicit Processing state.")
        result = result or {}
        if not isinstance(result, dict):
            raise ValidationError("Callback result must be a bounded object.")
        allowed = {
            "external_reference",
            "chatwoot_message_id",
        }
        if set(result) - allowed:
            raise ValidationError("Callback result contains unsupported fields.")
        external_reference = _clean_text(
            result.get("external_reference"), "External reference", 500
        )
        chatwoot_message_id = result.get("chatwoot_message_id")
        if record.channel == "chatwoot":
            if (
                isinstance(chatwoot_message_id, bool)
                or not isinstance(chatwoot_message_id, int)
                or chatwoot_message_id <= 0
            ):
                raise ValidationError(
                    "A positive Chatwoot message ID is required for delivery success."
                )
            if external_reference != str(chatwoot_message_id):
                raise ValidationError(
                    "Chatwoot external reference must match the provider message ID."
                )
        elif not external_reference:
            raise ValidationError(
                "An external reference is required for OpenProject success."
            )
        record.with_context(dev_outbox_action=True).write(
            {
                "state": "done",
                "completed_at": fields.Datetime.now(),
                "external_reference": external_reference,
                "lease_owner_id": False,
                "lease_consumer_ref": False,
                "lease_token": False,
                "lease_expires_at": False,
                "reconciliation_required": False,
                "last_error_code": False,
                "last_error_summary": False,
            }
        )
        if record.communication_id:
            record.communication_id.sudo()._integration_update(
                {
                    "chatwoot_message_id": chatwoot_message_id or False,
                    "delivery_summary": "Chatwoot accepted the explicit queued message.",
                    "delivery_status": "handed_off",
                    "error_state": False,
                }
            )
        return {"state": "done", "external_reference": external_reference}

    @api.model
    def service_ack_failure(
        self,
        record_id,
        correlation_id,
        error_code,
        error_summary,
        lease_token=None,
        transient=True,
        retry_after_seconds=60,
        delivery_uncertain=False,
    ):
        record = self._service_record(record_id, correlation_id, lease_token)
        if record.state not in ("leased", "processing"):
            raise UserError("Only an active lease can record failure.")
        code = _clean_text(error_code, "Error code", 100)
        summary = _clean_text(error_summary, "Error summary", 1000)
        retry_allowed = (
            bool(transient)
            and not bool(delivery_uncertain)
            and record.attempt_count < record.max_attempts
        )
        reconciliation_allowed = (
            bool(delivery_uncertain) and record.attempt_count < record.max_attempts
        )
        values = {
            "state": (
                "retry"
                if retry_allowed
                else (
                    "uncertain_delivery"
                    if reconciliation_allowed
                    else "dead_letter"
                )
            ),
            "next_attempt_at": fields.Datetime.now()
            + timedelta(seconds=max(30, min(int(retry_after_seconds or 60), 86400))),
            "lease_owner_id": False,
            "lease_consumer_ref": False,
            "lease_token": False,
            "lease_expires_at": False,
            "reconciliation_required": reconciliation_allowed,
            "completed_at": (
                fields.Datetime.now()
                if not retry_allowed and not reconciliation_allowed
                else False
            ),
            "last_error_code": code,
            "last_error_summary": summary,
        }
        record.with_context(dev_outbox_action=True).write(values)
        if record.communication_id:
            record.communication_id.sudo()._integration_update(
                {
                    "delivery_status": "failed"
                    if retry_allowed
                    else (
                        "delivery_pending_confirmation"
                        if reconciliation_allowed
                        else "dead_letter"
                    ),
                    "error_state": summary,
                }
            )
        return {"state": record.state, "attempt_count": record.attempt_count}


