# -*- coding: utf-8 -*-
"""Guarded service APIs for n8n outbox and Dify draft generation."""

from datetime import timedelta
import json
import uuid

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import html2plaintext

from .dev_work import (
    _bounded,
    _canonical_hash,
    _clean_text,
    _validated_json,
)


def _uuid(*_args):
    return str(uuid.uuid4())


def _require_outbox_service(env):
    if not env.is_superuser() and not env.user.has_group(
        "dev_session_hub.group_dev_hub_integration"
    ):
        raise AccessError("This operation requires the scoped Dev Hub outbox role.")


def _require_generation_service(env):
    if not env.is_superuser() and not env.user.has_group(
        "dev_session_hub.group_dev_hub_generation"
    ):
        raise AccessError("This operation requires the scoped Dev Hub generation role.")


def _lease_expiry(seconds):
    seconds = max(30, min(int(seconds or 300), 1800))
    return fields.Datetime.now() + timedelta(seconds=seconds)


class DevProject(models.Model):
    _inherit = "dev.project"

    generation_policy = fields.Selection(
        [
            ("manual", "Manual Drafts"),
            ("automatic", "Automatic Analysis and Plan Drafts"),
        ],
        default="manual",
        required=True,
        help="Automatic mode only creates drafts through the guarded integration queue.",
    )
    generation_provider = fields.Selection(
        [("dify_n8n", "Dify through n8n")],
        default="dify_n8n",
        required=True,
    )


class DevWorkItem(models.Model):
    _inherit = "dev.work.item"

    generation_request_ids = fields.One2many(
        "dev.work.generation", "work_item_id", string="Generation Requests"
    )
    current_generation_id = fields.Many2one(
        "dev.work.generation", compute="_compute_current_generation"
    )

    def _compute_current_generation(self):
        Generation = self.env["dev.work.generation"]
        for record in self:
            record.current_generation_id = (
                record.generation_request_ids.sorted(
                    lambda item: (item.requested_at, item.id), reverse=True
                )[:1]
                or Generation
            )

    def _generation_prerequisites(self):
        self.ensure_one()
        missing = []
        if not self.odoo_task_id or not self.op_backend_id or not self.op_work_package_id:
            missing.append("verified OpenProject-backed Odoo task")
        if not self.preferred_repository_id:
            missing.append("preferred repository")
        if not self.preferred_environment_id:
            missing.append("preferred environment")
        else:
            self.preferred_environment_id._assert_dev_hub_safe(self.dev_project_id)
        if self.preferred_repository_id and not (
            self.preferred_repository_id.head_cache
            or self.current_checkpoint_id.git_head
        ):
            missing.append("repository HEAD snapshot")
        return missing

    def _build_generation_context(self, kind):
        self.ensure_one()
        missing = self._generation_prerequisites()
        if missing:
            raise UserError("Generation context needs: %s." % ", ".join(missing))
        source_messages = self.source_message_ids.sorted(
            lambda item: (item.message_timestamp, item.id)
        )[:3]
        task_description = html2plaintext(
            getattr(self.odoo_task_id, "description", False) or ""
        )
        repository = self.preferred_repository_id
        environment = self.preferred_environment_id
        checkpoint = self.current_checkpoint_id
        payload = {
            "schema": "dev-hub-generation-context.v1",
            "generation_kind": kind,
            "work_item_uuid": self.uuid,
            "context_revision": self.context_revision,
            "source_summaries": [
                _bounded(item.text_snapshot, 1200) for item in source_messages
            ],
            "openproject": {
                "backend_id": self.op_backend_id.id,
                "work_package_id": self.op_work_package_id,
                "url": self.op_url or "",
            },
            "odoo_task": {
                "id": self.odoo_task_id.id,
                "title": _bounded(self.odoo_task_id.name, 500),
                "description": _bounded(task_description, 3000),
                "priority": self.priority_cache or "",
                "deadline": str(self.deadline_cache or ""),
            },
            "project": {
                "name": self.dev_project_id.name,
                "code": self.dev_project_id.code,
                "policy": _bounded(self.dev_project_id.production_policy, 1800),
                "agent_guardrails": _bounded(
                    self.dev_project_id.agent_instruction_summary, 1800
                ),
            },
            "repository": {
                "id": repository.id,
                "name": repository.name,
                "role": repository.repository_role,
                "remote": repository.git_remote,
                "default_branch": repository.default_branch,
                "head": checkpoint.git_head
                or repository.head_cache
                or "",
            },
            "environment": {
                "id": environment.id,
                "name": environment.name,
                "type": environment.environment_type,
                "odoo_version": environment.odoo_version or "",
                "data_sensitivity": environment.data_sensitivity,
            },
        }
        if kind == "plan":
            analysis = self.current_accepted_analysis_id
            if not analysis:
                raise UserError("Plan generation requires an accepted analysis.")
            payload["accepted_analysis"] = {
                "revision": analysis.revision,
                "hash": analysis.content_hash,
                "problem_summary": _bounded(analysis.problem_summary, 1800),
                "technical_findings": _bounded(analysis.technical_findings, 3000),
                "affected_components": _bounded(analysis.affected_components, 1800),
                "risks": _bounded(analysis.risks, 1800),
                "dependencies": _bounded(analysis.dependencies, 1800),
                "open_questions": _bounded(analysis.open_questions, 1800),
            }
        return json.loads(_validated_json(payload))

    def _request_generation(self, kind):
        self.ensure_one()
        if kind == "analysis" and self.current_phase != "registered":
            raise UserError("Analysis generation requires a Registered Work Item.")
        if kind == "plan" and self.current_phase != "analyzing":
            raise UserError("Plan generation requires an accepted analysis in Analyzing.")
        context = self._build_generation_context(kind)
        context_json = _validated_json(context)
        context_hash = _canonical_hash(context)
        key = "generation:%s:%s:%s" % (self.uuid, kind, context_hash[:24])
        existing = self.env["dev.work.generation"].sudo().search(
            [("idempotency_key", "=", key)], limit=1
        )
        if existing:
            return existing
        return self.env["dev.work.generation"].with_context(
            dev_internal_generation=True
        ).sudo().create(
            {
                "work_item_id": self.id,
                "kind": kind,
                "context_json": context_json,
                "context_hash": context_hash,
                "idempotency_key": key,
                "requested_by_id": self.env.user.id,
            }
        )

    def action_request_analysis_generation(self):
        self.ensure_one()
        return self._request_generation("analysis")

    def action_request_plan_generation(self):
        self.ensure_one()
        return self._request_generation("plan")

    def action_register(self):
        result = super().action_register()
        for record in self:
            if record.dev_project_id.generation_policy != "automatic":
                continue
            try:
                record.action_request_analysis_generation()
            except (UserError, ValidationError) as exc:
                record.action_block(
                    "Automatic analysis generation needs input: %s"
                    % _bounded(str(exc), 700)
                )
        return result


class DevWorkAnalysis(models.Model):
    _inherit = "dev.work.analysis"

    def action_accept(self):
        result = super().action_accept()
        for record in self:
            if record.work_item_id.dev_project_id.generation_policy == "automatic":
                record.work_item_id.action_request_plan_generation()
        return result


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
    def service_lease(self, limit=10, lease_seconds=300, consumer_ref=None):
        _require_outbox_service(self.env)
        self._recover_expired_leases()
        consumer_ref = _clean_text(consumer_ref, "Consumer reference", 120)
        limit = max(1, min(int(limit or 10), 50))
        now = fields.Datetime.now()
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


class DevWorkGeneration(models.Model):
    _name = "dev.work.generation"
    _description = "Guarded Development Draft Generation"
    _order = "requested_at desc, id desc"

    work_item_id = fields.Many2one(
        "dev.work.item", required=True, ondelete="restrict", readonly=True, index=True
    )
    kind = fields.Selection(
        [("analysis", "Analysis"), ("plan", "Plan")],
        required=True,
        readonly=True,
        index=True,
    )
    state = fields.Selection(
        [
            ("pending", "Pending"),
            ("leased", "Leased"),
            ("processing", "Processing"),
            ("succeeded", "Succeeded"),
            ("retry", "Retrying"),
            ("dead_letter", "Dead Letter"),
        ],
        default="pending",
        required=True,
        readonly=True,
        index=True,
    )
    correlation_id = fields.Char(
        required=True, default=_uuid, readonly=True, copy=False, index=True
    )
    idempotency_key = fields.Char(required=True, readonly=True, copy=False, index=True)
    context_json = fields.Text(required=True, readonly=True)
    context_hash = fields.Char(required=True, readonly=True, index=True)
    requested_at = fields.Datetime(
        required=True, default=fields.Datetime.now, readonly=True, index=True
    )
    requested_by_id = fields.Many2one(
        "res.users", required=True, ondelete="restrict", readonly=True
    )
    lease_owner_id = fields.Many2one("res.users", readonly=True)
    lease_consumer_ref = fields.Char(readonly=True)
    lease_token = fields.Char(readonly=True, copy=False, index=True)
    lease_version = fields.Integer(default=0, required=True, readonly=True)
    leased_at = fields.Datetime(readonly=True)
    lease_expires_at = fields.Datetime(readonly=True, index=True)
    processing_at = fields.Datetime(readonly=True)
    completed_at = fields.Datetime(readonly=True)
    attempt_count = fields.Integer(default=0, readonly=True)
    max_attempts = fields.Integer(default=3, required=True, readonly=True)
    next_attempt_at = fields.Datetime(
        default=fields.Datetime.now, required=True, readonly=True, index=True
    )
    provider_reference = fields.Char(readonly=True)
    run_reference = fields.Char(readonly=True)
    artifact_model = fields.Char(readonly=True)
    artifact_record_id = fields.Integer(readonly=True)
    last_error_code = fields.Char(readonly=True)
    last_error_summary = fields.Char(readonly=True)

    _idempotency_unique = models.Constraint(
        "unique(idempotency_key)", "Generation idempotency key must be unique."
    )
    _provider_run_unique = models.UniqueIndex(
        "(provider_reference, run_reference) "
        "WHERE provider_reference IS NOT NULL AND run_reference IS NOT NULL",
        "A provider run may import at most one generation request.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("dev_internal_generation"):
            raise AccessError("Generation requests may be created only by guarded actions.")
        for values in vals_list:
            values["context_json"] = _validated_json(values.get("context_json"))
            if values.get("state", "pending") != "pending":
                raise ValidationError("Generation requests must start Pending.")
        return super().create(vals_list)

    def write(self, values):
        if not self.env.context.get("dev_generation_action"):
            raise AccessError("Generation records change only through guarded callbacks.")
        protected = {
            "work_item_id",
            "kind",
            "correlation_id",
            "idempotency_key",
            "context_json",
            "context_hash",
            "requested_at",
            "requested_by_id",
        }
        if protected & set(values):
            raise AccessError("Generation identity and context are immutable.")
        return super().write(values)

    def unlink(self):
        raise AccessError("Generation audit records cannot be deleted.")

    @api.model
    def service_lease(self, limit=5, lease_seconds=600, consumer_ref=None):
        _require_generation_service(self.env)
        now = fields.Datetime.now()
        expired = self.sudo().search(
            [
                ("state", "=", "leased"),
                ("lease_expires_at", "<=", now),
            ]
        )
        for record in expired:
            exhausted = record.attempt_count >= record.max_attempts
            record.with_context(dev_generation_action=True).write(
                {
                    "state": "dead_letter" if exhausted else "retry",
                    "next_attempt_at": now,
                    "lease_owner_id": False,
                    "lease_consumer_ref": False,
                    "lease_token": False,
                    "lease_expires_at": False,
                    "completed_at": now if exhausted else False,
                    "last_error_code": "lease_expired",
                    "last_error_summary": (
                        "Generation lease expired on the final attempt."
                        if exhausted
                        else "Generation lease expired before execution."
                    ),
                }
            )
        stalled = self.sudo().search(
            [
                ("state", "=", "processing"),
                ("lease_expires_at", "<=", now),
            ]
        )
        if stalled:
            stalled.with_context(dev_generation_action=True).write(
                {
                    "state": "dead_letter",
                    "lease_owner_id": False,
                    "lease_consumer_ref": False,
                    "lease_token": False,
                    "lease_expires_at": False,
                    "last_error_code": "generation_outcome_unknown",
                    "last_error_summary": (
                        "Generation processing expired; review before retrying."
                    ),
                }
            )
        limit = max(1, min(int(limit or 5), 20))
        consumer_ref = _clean_text(consumer_ref, "Consumer reference", 120)
        self.env.cr.execute(
            """
                SELECT id
                  FROM dev_work_generation
                 WHERE state IN ('pending', 'retry')
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
            record.with_context(dev_generation_action=True).write(
                {
                    "state": "leased",
                    "attempt_count": record.attempt_count + 1,
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
                    "kind": record.kind,
                    "correlation_id": record.correlation_id,
                    "lease_token": lease_token,
                    "lease_version": record.lease_version,
                    "idempotency_key": record.idempotency_key,
                    "context": json.loads(record.context_json),
                    "attempt": record.attempt_count,
                }
            )
        return result

    def _service_record(self, record_id, correlation_id, lease_token):
        _require_generation_service(self.env)
        record = self.sudo().browse(int(record_id)).exists()
        if not record or record.correlation_id != correlation_id:
            raise AccessError("Unknown generation correlation.")
        if record.lease_owner_id.id != self.env.user.id:
            raise AccessError("The generation lease belongs to another identity.")
        if not lease_token or record.lease_token != lease_token:
            raise AccessError("The generation lease token is stale or invalid.")
        if not record.lease_expires_at or record.lease_expires_at <= fields.Datetime.now():
            raise AccessError("The generation lease has expired.")
        return record

    @api.model
    def service_mark_processing(
        self,
        record_id,
        correlation_id,
        lease_token,
        provider_reference=None,
        run_reference=None,
    ):
        record = self._service_record(record_id, correlation_id, lease_token)
        if record.state == "processing":
            raise AccessError("Generation execution permission was already consumed.")
        if record.state != "leased":
            raise UserError("Only a leased generation can start processing.")
        provider_reference = _clean_text(
            provider_reference, "Provider reference", 200
        )
        run_reference = _clean_text(run_reference, "Run reference", 300)
        if not provider_reference or not run_reference:
            raise ValidationError(
                "Provider and run references are required before generation starts."
            )
        record.with_context(dev_generation_action=True).write(
            {
                "state": "processing",
                "processing_at": fields.Datetime.now(),
                "provider_reference": provider_reference,
                "run_reference": run_reference,
            }
        )
        return True

    @api.model
    def service_complete(self, record_id, correlation_id, lease_token, result):
        record = self._service_record(record_id, correlation_id, lease_token)
        if record.state == "succeeded":
            return {
                "state": "succeeded",
                "artifact_model": record.artifact_model,
                "artifact_record_id": record.artifact_record_id,
            }
        if record.state != "processing":
            raise UserError("Generation completion requires Processing state.")
        context = json.loads(record.context_json)
        work = record.work_item_id
        stale_reason = False
        if context.get("context_revision") != work.context_revision:
            stale_reason = "Work Item context changed after generation was requested."
        elif record.kind == "plan":
            accepted = work.current_accepted_analysis_id
            expected = context.get("accepted_analysis") or {}
            if (
                not accepted
                or expected.get("revision") != accepted.revision
                or expected.get("hash") != accepted.content_hash
            ):
                stale_reason = "Accepted analysis changed after planning was requested."
        if stale_reason:
            record.with_context(dev_generation_action=True).write(
                {
                    "state": "dead_letter",
                    "completed_at": fields.Datetime.now(),
                    "lease_owner_id": False,
                    "lease_consumer_ref": False,
                    "lease_token": False,
                    "lease_expires_at": False,
                    "last_error_code": "stale_generation_context",
                    "last_error_summary": stale_reason,
                }
            )
            return {"state": "dead_letter", "error_code": "stale_generation_context"}
        if not isinstance(result, dict):
            raise ValidationError("Generation result must be a bounded object.")
        supplied_uuid = result.get("work_item_uuid")
        if supplied_uuid and supplied_uuid != work.uuid:
            raise ValidationError("Generation result targets a different Work Item.")
        result = dict(result, work_item_uuid=work.uuid)
        if record.kind == "analysis":
            result.update(
                {
                    "provider_reference": record.provider_reference,
                    "run_reference": record.run_reference,
                    "model_reference": "managed-dify-workflow",
                    "observed_head": (context.get("repository") or {}).get("head", ""),
                }
            )
        if record.kind == "plan":
            result["analysis_revision"] = work.current_accepted_analysis_id.revision
            result["run_reference"] = record.run_reference
        try:
            with self.env.cr.savepoint():
                if record.kind == "analysis":
                    artifact_id = (
                        self.env["dev.work.item"]
                        .with_context(dev_generation_import=True)
                        .import_analysis_draft(result)
                    )
                    artifact_model = "dev.work.analysis"
                else:
                    artifact_id = (
                        self.env["dev.work.item"]
                        .with_context(dev_generation_import=True)
                        .import_plan_draft(result)
                    )
                    artifact_model = "dev.work.plan"
                    self.env[artifact_model].sudo().browse(
                        artifact_id
                    ).action_submit_for_approval()
        except (AccessError, UserError, ValidationError) as exc:
            summary = _bounded(str(exc), 900)
            record.with_context(dev_generation_action=True).write(
                {
                    "state": "dead_letter",
                    "completed_at": fields.Datetime.now(),
                    "lease_owner_id": False,
                    "lease_consumer_ref": False,
                    "lease_token": False,
                    "lease_expires_at": False,
                    "last_error_code": "invalid_generation_output",
                    "last_error_summary": summary,
                }
            )
            return {"state": "dead_letter", "error_code": "invalid_generation_output"}
        record.with_context(dev_generation_action=True).write(
            {
                "state": "succeeded",
                "completed_at": fields.Datetime.now(),
                "artifact_model": artifact_model,
                "artifact_record_id": artifact_id,
                "lease_owner_id": False,
                "lease_consumer_ref": False,
                "lease_token": False,
                "lease_expires_at": False,
                "last_error_code": False,
                "last_error_summary": False,
            }
        )
        return {
            "state": "succeeded",
            "artifact_model": artifact_model,
            "artifact_record_id": artifact_id,
        }

    @api.model
    def service_fail(
        self,
        record_id,
        correlation_id,
        error_code,
        error_summary,
        lease_token=None,
        transient=True,
        retry_after_seconds=120,
    ):
        record = self._service_record(record_id, correlation_id, lease_token)
        if record.state not in ("leased", "processing"):
            raise UserError("Only an active generation lease can fail.")
        retry = bool(transient) and record.attempt_count < record.max_attempts
        record.with_context(dev_generation_action=True).write(
            {
                "state": "retry" if retry else "dead_letter",
                "next_attempt_at": fields.Datetime.now()
                + timedelta(
                    seconds=max(30, min(int(retry_after_seconds or 120), 86400))
                ),
                "lease_owner_id": False,
                "lease_consumer_ref": False,
                "lease_token": False,
                "lease_expires_at": False,
                "last_error_code": _clean_text(error_code, "Error code", 100),
                "last_error_summary": _clean_text(
                    error_summary, "Error summary", 1000
                ),
            }
        )
        if not retry and record.work_item_id.current_phase in (
            "registered",
            "analyzing",
            "planning",
        ):
            record.work_item_id.sudo().with_context(
                dev_integration_actor_id=self.env.user.id
            ).action_block("Draft generation requires review after repeated failure.")
        return {"state": record.state, "attempt_count": record.attempt_count}
