# -*- coding: utf-8 -*-
"""Guarded service APIs for n8n outbox and Dify draft generation."""

from datetime import timedelta
import json
import uuid

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

# Kind registry: capability modules may extend via _register_hook / monkeypatch.
# Default handlers call work-item import RPCs provided by Analysis/Plan modules.
GENERATION_KIND_REGISTRY = {
    "analysis": "import_analysis_draft",
    "merge_analysis": "import_merged_analysis_draft",
    "plan": "import_plan_draft",
}

from odoo.tools import html2plaintext

from odoo.addons.devhub_work.models.dev_work_utils import (
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
    analysis_source_mode = fields.Selection(
        [
            ("odoo_task", "Odoo task / OpenProject-backed only"),
            ("work_item", "Standalone Work Item (no Odoo task required)"),
            ("either", "Odoo task or standalone Work Item"),
        ],
        default="odoo_task",
        required=True,
        help="Controls deep-analysis prerequisites. OpenProject is never required for "
        "work_item / either modes.",
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
        mode = self.dev_project_id.analysis_source_mode or "odoo_task"
        if mode == "odoo_task":
            has_legacy = bool(
                self.odoo_task_id
                and getattr(self, "op_backend_id", False)
                and self.op_backend_id
                and getattr(self, "op_work_package_id", False)
                and self.op_work_package_id
            )
            if not has_legacy:
                missing.append("verified OpenProject-backed Odoo task")
        # mode work_item / either: OpenProject not required
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

    def _build_generation_context(self, kind, base_analysis=None):
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
                _context_text(item.text_snapshot, 1200) for item in source_messages
            ],
            "openproject": {
                "backend_id": self.op_backend_id.id,
                "work_package_id": self.op_work_package_id,
                "url": self.op_url or "",
            },
            "odoo_task": {
                "id": self.odoo_task_id.id,
                "title": _context_text(self.odoo_task_id.name, 500),
                "description": _context_text(task_description, 3000),
                "priority": self.priority_cache or "",
                "deadline": str(self.deadline_cache or ""),
            },
            "project": {
                "name": self.dev_project_id.name,
                "code": self.dev_project_id.code,
                "policy": _context_text(self.dev_project_id.production_policy, 1800),
                "agent_guardrails": _context_text(
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
                "problem_summary": _context_text(analysis.problem_summary, 1800),
                "technical_findings": _context_text(analysis.technical_findings, 3000),
                "affected_components": _context_text(analysis.affected_components, 1800),
                "risks": _context_text(analysis.risks, 1800),
                "dependencies": _context_text(analysis.dependencies, 1800),
                "open_questions": _context_text(analysis.open_questions, 1800),
            }
        if kind == "merge_analysis":
            base = base_analysis or self.current_analysis_id
            if not base:
                raise UserError("Merge & Improve requires an existing analysis revision.")
            human = (base.user_analysis_notes or "").strip()
            if not human:
                raise UserError(
                    "Write your notes in the 'My Analysis' tab before merging."
                )
            payload["base_analysis"] = {
                "id": base.id,
                "revision": base.revision,
                "hash": base.content_hash,
                "origin": base.origin,
                "problem_summary": _context_text(base.problem_summary, 2000),
                "original_request_summary": _context_text(
                    base.original_request_summary, 3000
                ),
                "reproduction_context": _context_text(base.reproduction_context, 2000),
                "current_behavior": _context_text(base.current_behavior, 2000),
                "expected_behavior": _context_text(base.expected_behavior, 2000),
                "technical_findings": _context_text(base.technical_findings, 6000),
                "affected_components": _context_text(base.affected_components, 2000),
                "risks": _context_text(base.risks, 2000),
                "dependencies": _context_text(base.dependencies, 2000),
                "open_questions": _context_text(base.open_questions, 2000),
                "evidence_references": _context_text(base.evidence_references, 2000),
            }
            payload["human_analysis"] = _context_text(human, 6000)
        return json.loads(_validated_json(payload))

    def _request_generation(self, kind, base_analysis=None):
        self.ensure_one()
        if kind == "analysis" and self.current_phase != "registered":
            raise UserError("Analysis generation requires a Registered Work Item.")
        if kind == "plan" and self.current_phase != "analyzing":
            raise UserError("Plan generation requires an accepted analysis in Analyzing.")
        if kind == "merge_analysis" and self.current_phase != "analyzing":
            raise UserError(
                "Merge & Improve Analysis requires the Analyzing phase."
            )
        context = self._build_generation_context(kind, base_analysis=base_analysis)
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

    def request_analysis_merge(self, base_analysis):
        """Queue a semantic merge of a specific analysis revision + its My Analysis notes."""
        self.ensure_one()
        base_analysis.ensure_one()
        if base_analysis.work_item_id != self:
            raise UserError("The analysis revision does not belong to this work item.")
        if base_analysis.status in ("superseded", "rejected"):
            raise UserError(
                "Merge a working analysis revision (draft, generated, reviewed, "
                "or accepted), not a superseded or rejected one."
            )
        if self.current_phase == "registered":
            # A base analysis already exists (e.g. code/database run); ease into Analyzing.
            self.transition_lifecycle(
                "analyzing", "Merge & Improve Analysis", actor_type="automation"
            )
        return self._request_generation("merge_analysis", base_analysis=base_analysis)

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

    def action_merge_and_improve_analysis(self):
        """Human-triggered: queue a guarded semantic merge using this revision as base."""
        self.ensure_one()
        generation = self.work_item_id.request_analysis_merge(self)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Merge & Improve Analysis queued",
                "message": (
                    "A semantic merge request was queued (id %s). The external "
                    "generation worker will produce a consolidated analysis "
                    "revision shortly." % generation.id
                ),
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.act_window_close"},
            },
        }


class DevWorkGeneration(models.Model):
    _name = "dev.work.generation"
    _description = "Guarded Development Draft Generation"
    _order = "requested_at desc, id desc"

    work_item_id = fields.Many2one(
        "dev.work.item", required=True, ondelete="restrict", readonly=True, index=True
    )
    kind = fields.Selection(
        [
            ("analysis", "Analysis"),
            ("plan", "Plan"),
            ("merge_analysis", "Merge Analysis"),
        ],
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
            # Staleness reads run under the scoped generation-service user, which
            # has no direct access to dev.work.analysis; sudo the read-only check.
            accepted = work.sudo().current_accepted_analysis_id
            expected = context.get("accepted_analysis") or {}
            if (
                not accepted
                or expected.get("revision") != accepted.revision
                or expected.get("hash") != accepted.content_hash
            ):
                stale_reason = "Accepted analysis changed after planning was requested."
        elif record.kind == "merge_analysis":
            # Staleness reads run under the scoped generation-service user, which
            # has no direct access to dev.work.analysis; sudo the read-only check.
            expected = context.get("base_analysis") or {}
            base = self.env["dev.work.analysis"].sudo().browse(
                expected.get("id") or 0
            ).exists()
            if (
                not base
                or base.work_item_id.id != work.id
                or expected.get("hash") != base.content_hash
            ):
                stale_reason = "Base analysis changed after the merge was requested."
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
        # Registry-driven dispatch (kinds registered by Analysis/Plan).
        import_method = GENERATION_KIND_REGISTRY.get(record.kind)
        if not import_method:
            raise UserError("Unsupported generation kind: %s" % record.kind)
        if not hasattr(work, import_method):
            raise UserError(
                "Generation kind %s requires a capability module providing %s."
                % (record.kind, import_method)
            )
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
            analysis = getattr(work, "current_accepted_analysis_id", False)
            if analysis:
                result["analysis_revision"] = analysis.revision
            result["run_reference"] = record.run_reference
        if record.kind == "merge_analysis":
            base_ctx = context.get("base_analysis") or {}
            result.update(
                {
                    "provider_reference": record.provider_reference,
                    "run_reference": record.run_reference,
                    "model_reference": "managed-dify-workflow",
                    "observed_head": (context.get("repository") or {}).get("head", ""),
                    "base_analysis_id": base_ctx.get("id"),
                    "human_input_snapshot": context.get("human_analysis"),
                    "merged_by_id": record.requested_by_id.id,
                }
            )
        artifact_model = {
            "analysis": "dev.work.analysis",
            "merge_analysis": "dev.work.analysis",
            "plan": "dev.work.plan",
        }.get(record.kind)
        if not artifact_model:
            raise UserError("Unsupported generation kind: %s" % record.kind)
        try:
            with self.env.cr.savepoint():
                importer = getattr(
                    self.env["dev.work.item"].with_context(dev_generation_import=True),
                    import_method,
                )
                artifact_id = importer(result)
                if record.kind == "plan":
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
