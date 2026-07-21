# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import json
import re
import uuid

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


MAX_TEXT = 12000
MAX_JSON = 16000
MAX_BRIEF = 16000
MAX_JSON_DEPTH = 6
MAX_JSON_ITEMS = 200

# A "secret-like value" is what distinguishes an actual credential from ordinary
# technical prose. We require some length AND at least one digit or base64 marker
# (+/=). This keeps detection fail-closed for real secrets while allowing phrases
# like "password policy", "api_key: rotated_now", or "password: required" through.
_SECRET_VALUE = r"(?=[^\s,;]{8,})(?=[^\s,;]*[0-9+/=])[^\s,;]+"
# A bearer/basic credential value: token-charset, >=16 chars, with a digit or +/=,
# so prose like "basic authentication" / "bearer token authorization" is allowed.
_BEARER_VALUE = r"(?=[a-z0-9._~+/=-]{16,})(?=[a-z0-9._~+/=-]*[0-9+/=])[a-z0-9._~+/=-]+"

SECRET_PATTERN = re.compile(
    # NB: case-insensitive only (no VERBOSE): the literal spaces in the PEM branch
    # below are significant, otherwise "-----BEGIN OPENSSH PRIVATE KEY-----" (with
    # spaces) would never match.
    r"(?i)"
    r"(?:authorization|proxy-authorization)\s*[\"']?\s*[:=]\s*[^\s,;]+|"
    r"\b(?:bearer|basic)\s+" + _BEARER_VALUE + r"|"
    r"\b(?:password|passwd|pwd|secret|client_secret|access_token|refresh_token|"
    r"api[_-]?key|private[_-]?key)\b\s*[\"']?\s*[:=]\s*" + _SECRET_VALUE + r"|"
    r"\bAKIA[0-9A-Z]{16}\b|"
    r"\bgh[opusr]_[A-Za-z0-9_]{20,}\b|"
    r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b|"
    r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b|"
    r"[a-z][a-z0-9+.-]{0,40}://[^/\s:@]+:[^/\s@]+@|"
    r"-----BEGIN [A-Z0-9 ]*(?:PRIVATE KEY|OPENSSH KEY)-----"
)
FORBIDDEN_CONTENT = re.compile(
    r"(?im)"
    r"^(?:diff --git|index [0-9a-f]+\.\.[0-9a-f]+|@@ .+ @@|\+\+\+ b/|--- a/)|"
    r"^\s*(?:export\s+)?(?:PATH|HOME|AWS_[A-Z0-9_]+|DATABASE_URL|"
    r"OPENAI_API_KEY|ODOO_RC)\s*=|"
    r"[\"']?(?:raw_payload|environment_dump|full_diff|transcript|messages)"
    r"[\"']?\s*:"
)
FORBIDDEN_JSON_KEYS = {
    "authorization",
    "cookie",
    "cookies",
    "credential",
    "credentials",
    "diff",
    "env",
    "environment_variables",
    "headers",
    "password",
    "private_key",
    "raw",
    "raw_payload",
    "request",
    "response",
    "secret",
    "token",
    "transcript",
}

LIFECYCLE_SELECTION = [
    ("received", "Received"),
    ("triage", "Triage"),
    ("registered", "Registered"),
    ("analyzing", "Analyzing"),
    ("planning", "Planning"),
    ("awaiting_plan_approval", "Awaiting Plan Approval"),
    ("approved", "Approved"),
    ("implementing", "Implementing"),
    ("paused", "Paused"),
    ("blocked", "Blocked"),
    ("testing", "Testing"),
    ("ready_for_review", "Ready for Review"),
    ("completed", "Completed"),
    ("reported", "Reported"),
    ("cancelled", "Cancelled"),
]
LIFECYCLE_TRANSITIONS = {
    "received": {"triage", "cancelled"},
    "triage": {"registered", "cancelled"},
    "registered": {"analyzing", "blocked", "cancelled"},
    "analyzing": {"planning", "triage", "blocked", "cancelled"},
    "planning": {"awaiting_plan_approval", "blocked", "cancelled"},
    "awaiting_plan_approval": {"approved", "planning", "blocked", "cancelled"},
    "approved": {"implementing", "awaiting_plan_approval", "cancelled"},
    "implementing": {"paused", "blocked", "testing", "cancelled"},
    "paused": {"implementing", "blocked", "cancelled"},
    "blocked": {
        "triage",
        "analyzing",
        "planning",
        "awaiting_plan_approval",
        "approved",
        "implementing",
        "testing",
        "ready_for_review",
        "cancelled",
    },
    "testing": {"implementing", "ready_for_review", "blocked", "cancelled"},
    "ready_for_review": {"implementing", "testing", "completed", "blocked", "cancelled"},
    "completed": {"reported"},
    "reported": set(),
    "cancelled": set(),
}


def _uuid(*_args):
    return str(uuid.uuid4())


def _canonical_hash(payload):
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _clean_text(value, label, limit=MAX_TEXT):
    if value is None or value is False:
        value = ""
    if not isinstance(value, str):
        raise ValidationError("%s must be text." % label)
    value = value.strip()
    if len(value) > limit:
        raise ValidationError("%s exceeds the %s-character storage limit." % (label, limit))
    if SECRET_PATTERN.search(value):
        raise ValidationError("%s appears to contain credential material." % label)
    if FORBIDDEN_CONTENT.search(value):
        raise ValidationError(
            "%s contains a raw payload, environment dump, diff, or transcript." % label
        )
    return value


def _clean_note_text(value, label, limit=MAX_TEXT):
    """Softer guard for human-authored notes (e.g. My Analysis).

    Humans legitimately quote diff hunks, env lines, or use words like
    "messages:"/"transcript:" that trip FORBIDDEN_CONTENT. Those are neutralized
    later via ``_neutralize_forbidden``/``_context_text`` when the merge context is
    built, so we only enforce type, length, and SECRET_PATTERN here — real
    credentials are still never allowed through.
    """
    if value is None or value is False:
        value = ""
    if not isinstance(value, str):
        raise ValidationError("%s must be text." % label)
    value = value.strip()
    if len(value) > limit:
        raise ValidationError("%s exceeds the %s-character storage limit." % (label, limit))
    if SECRET_PATTERN.search(value):
        raise ValidationError("%s appears to contain credential material." % label)
    return value


def _bounded(value, limit):
    value = (value or "").strip()
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def _neutralize_forbidden(value):
    """Rewrite human-authored evidence so the outbox guard patterns do not reject it.

    Analysis notes legitimately quote diff hunks, env lines, or use plain words like
    "messages:"/"transcript:" that collide with FORBIDDEN_CONTENT. We keep the meaning
    (bracketing/relabelling) instead of blocking the whole merge. SECRET_PATTERN still
    applies afterwards, so real credentials are never let through.
    """
    if not value or not isinstance(value, str):
        return value
    text = value
    text = re.sub(r"(?i)\braw_payload\s*:", "payload-ref:", text)
    text = re.sub(r"(?i)\benvironment_dump\s*:", "env-ref:", text)
    text = re.sub(r"(?i)\bfull_diff\s*:", "diff-ref:", text)
    text = re.sub(r"(?i)\btranscript\s*:", "discussion:", text)
    text = re.sub(r"(?i)\bmessages\s*:", "source notes:", text)
    text = re.sub(
        r"(?m)^(diff --git|index [0-9a-f]+\.\.[0-9a-f]+|@@ .+ @@|\+\+\+ b/|--- a/)",
        r"[\1]",
        text,
    )
    text = re.sub(
        r"(?im)^(\s*)((?:export\s+)?"
        r"(?:PATH|HOME|AWS_[A-Z0-9_]+|DATABASE_URL|OPENAI_API_KEY|ODOO_RC)\s*=)",
        r"\1[env] \2",
        text,
    )
    return text


def _context_text(value, limit):
    """Bounded, guard-safe rendering of human/analysis free text for generation context."""
    return _bounded(_neutralize_forbidden(value), limit)


def _validate_text_values(model, values, limit=MAX_TEXT):
    for name, value in values.items():
        field = model._fields.get(name)
        if field and field.type in ("char", "text") and value:
            _clean_text(value, field.string or name, limit)


def _normalize_aliases(values, aliases):
    for alias, canonical in aliases.items():
        if alias not in values:
            continue
        if canonical in values and values[canonical] != values[alias]:
            raise ValidationError(
                "Conflicting values were supplied for %s and %s." % (alias, canonical)
            )
        values[canonical] = values.pop(alias)


def _validate_json_value(value, depth=0, counter=None):
    if counter is None:
        counter = [0]
    if depth > MAX_JSON_DEPTH:
        raise ValidationError("Outbox JSON exceeds the maximum nesting depth.")
    counter[0] += 1
    if counter[0] > MAX_JSON_ITEMS:
        raise ValidationError("Outbox JSON contains too many values.")
    if value is None or isinstance(value, (bool, int, float)):
        return
    if isinstance(value, str):
        _clean_text(value, "Outbox JSON value", 2000)
        return
    if isinstance(value, list):
        for item in value:
            _validate_json_value(item, depth + 1, counter)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).strip().lower().replace("-", "_")
            if normalized in FORBIDDEN_JSON_KEYS:
                raise ValidationError("Outbox JSON contains a forbidden key: %s." % key)
            if len(str(key)) > 80:
                raise ValidationError("Outbox JSON key is too long.")
            _validate_json_value(item, depth + 1, counter)
        return
    raise ValidationError("Outbox JSON contains an unsupported value type.")


def _validated_json(payload):
    if isinstance(payload, str):
        if len(payload.encode("utf-8")) > MAX_JSON:
            raise ValidationError("Outbox JSON exceeds the byte limit.")
        try:
            payload = json.loads(payload)
        except (TypeError, ValueError) as exc:
            raise ValidationError("Outbox payload must be valid JSON.") from exc
    if not isinstance(payload, dict):
        raise ValidationError("Outbox payload must be a JSON object.")
    _validate_json_value(payload)
    result = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(result.encode("utf-8")) > MAX_JSON:
        raise ValidationError("Outbox JSON exceeds the byte limit.")
    return result


def _require_approver(env):
    if not env.is_superuser() and not env.user.has_group(
        "dev_session_hub.group_dev_hub_approver"
    ):
        raise AccessError("A Dev Hub approver must authorize this action.")


def _require_importer(env):
    if env.is_superuser():
        return
    is_manager = env.user.has_group("dev_session_hub.group_dev_hub_manager")
    is_guarded_generation = env.user.has_group(
        "dev_session_hub.group_dev_hub_generation"
    ) and env.context.get("dev_generation_import")
    allowed = is_manager or is_guarded_generation
    if not allowed:
        raise AccessError(
            "Draft import requires the guarded generation callback or a manager."
        )


class DevWorkItem(models.Model):
    _name = "dev.work.item"
    _description = "Development Work Item"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "write_date desc, id desc"

    uuid = fields.Char(required=True, default=_uuid, readonly=True, copy=False, index=True)
    name = fields.Char(required=True, tracking=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, index=True
    )
    dev_project_id = fields.Many2one(
        "dev.project", required=True, ondelete="restrict", index=True, tracking=True
    )
    odoo_project_id = fields.Many2one(
        "project.project", required=True, ondelete="restrict", index=True, tracking=True
    )
    odoo_task_id = fields.Many2one(
        "project.task", ondelete="restrict", index=True, copy=False, tracking=True
    )
    op_backend_id = fields.Many2one(
        "openproject.backend", ondelete="restrict", index=True, copy=False, tracking=True
    )
    op_work_package_id = fields.Integer(index=True, copy=False, tracking=True)
    op_url = fields.Char(copy=False)
    responsible_user_id = fields.Many2one(
        "res.users", required=True, default=lambda self: self.env.user, index=True
    )
    priority_cache = fields.Selection(
        [("0", "Normal"), ("1", "Low"), ("2", "High"), ("3", "Very High")],
        default="0",
    )
    deadline_cache = fields.Date()
    preferred_repository_id = fields.Many2one(
        "dev.repository", ondelete="restrict", index=True
    )
    preferred_environment_id = fields.Many2one(
        "dev.environment", ondelete="restrict", index=True
    )
    current_phase = fields.Selection(
        LIFECYCLE_SELECTION,
        required=True,
        default="received",
        readonly=True,
        index=True,
        tracking=True,
    )
    lifecycle_phase = fields.Selection(
        related="current_phase", store=True, readonly=True, index=True
    )
    blocked_from_phase = fields.Selection(LIFECYCLE_SELECTION, readonly=True, copy=False)
    blocker = fields.Text()
    cancellation_reason = fields.Text(readonly=True, copy=False)
    progress_percent = fields.Float(compute="_compute_progress", store=True)
    plan_progress = fields.Float(related="progress_percent", store=True, readonly=True)
    completed_step_count = fields.Integer(compute="_compute_progress", store=True)
    actionable_step_count = fields.Integer(compute="_compute_progress", store=True)
    context_revision = fields.Char(readonly=True, copy=False, index=True)

    source_message_ids = fields.Many2many(
        "dev.work.source.message",
        "dev_work_item_source_message_rel",
        "work_item_id",
        "source_message_id",
        string="Source Messages",
    )
    external_link_ids = fields.One2many(
        "dev.work.external.link", "work_item_id", string="External Links"
    )
    analysis_ids = fields.One2many("dev.work.analysis", "work_item_id")
    plan_ids = fields.One2many("dev.work.plan", "work_item_id")
    checkpoint_ids = fields.One2many("dev.work.checkpoint", "work_item_id")
    completion_report_ids = fields.One2many("dev.completion.report", "work_item_id")
    communication_ids = fields.One2many("dev.work.communication", "work_item_id")
    lifecycle_event_ids = fields.One2many(
        "dev.work.lifecycle.event", "work_item_id", string="Lifecycle Events"
    )
    outbox_ids = fields.One2many("dev.external.outbox", "work_item_id")
    session_ids = fields.One2many("dev.session", "work_item_id")
    current_analysis_id = fields.Many2one(
        "dev.work.analysis", compute="_compute_current_artifacts", store=False
    )
    current_accepted_analysis_id = fields.Many2one(
        "dev.work.analysis", compute="_compute_current_artifacts", store=False
    )
    approved_plan_id = fields.Many2one(
        "dev.work.plan", compute="_compute_current_artifacts", store=False
    )
    current_approved_plan_id = fields.Many2one(
        "dev.work.plan", related="approved_plan_id", readonly=True
    )
    current_checkpoint_id = fields.Many2one(
        "dev.work.checkpoint", compute="_compute_current_artifacts", store=False
    )
    completion_report_id = fields.Many2one(
        "dev.completion.report", compute="_compute_current_artifacts", store=False
    )
    op_reference = fields.Char(compute="_compute_op_reference")

    _uuid_unique = models.Constraint("unique(uuid)", "Work item UUID must be unique.")
    _op_identity_unique = models.UniqueIndex(
        "(op_backend_id, op_work_package_id) "
        "WHERE op_backend_id IS NOT NULL AND op_work_package_id IS NOT NULL",
        "An OpenProject work package can belong to only one work item.",
    )
    _odoo_task_unique = models.UniqueIndex(
        "(odoo_task_id) WHERE odoo_task_id IS NOT NULL",
        "An Odoo task can be primary for only one work item.",
    )

    @api.depends("op_work_package_id")
    def _compute_op_reference(self):
        for record in self:
            record.op_reference = (
                "#%s" % record.op_work_package_id
                if record.op_work_package_id
                else False
            )

    @api.depends("plan_ids.status", "plan_ids.step_ids.status")
    def _compute_progress(self):
        for record in self:
            plan = record.plan_ids.filtered(lambda p: p.status == "approved")[:1]
            if not plan:
                plan = record.plan_ids.sorted(lambda p: (p.revision, p.id), reverse=True)[:1]
            steps = plan.step_ids if plan else self.env["dev.work.plan.step"]
            actionable = steps.filtered(lambda s: s.status != "skipped")
            done = actionable.filtered(lambda s: s.status == "done")
            record.actionable_step_count = len(actionable)
            record.completed_step_count = len(done)
            record.progress_percent = (
                100.0 * len(done) / len(actionable) if actionable else 0.0
            )

    @api.depends(
        "analysis_ids.status",
        "analysis_ids.revision",
        "plan_ids.status",
        "plan_ids.revision",
        "checkpoint_ids.captured_at",
        "completion_report_ids.status",
        "completion_report_ids.revision",
    )
    def _compute_current_artifacts(self):
        Analysis = self.env["dev.work.analysis"]
        Plan = self.env["dev.work.plan"]
        Checkpoint = self.env["dev.work.checkpoint"]
        Report = self.env["dev.completion.report"]
        for record in self:
            accepted_analysis = record.analysis_ids.filtered(
                lambda r: r.status == "accepted"
            ).sorted(
                lambda r: (r.revision, r.id), reverse=True
            )[:1]
            record.current_accepted_analysis_id = accepted_analysis or Analysis
            record.current_analysis_id = (
                accepted_analysis
                or record.analysis_ids.sorted(
                    lambda r: (r.revision, r.id), reverse=True
                )[:1]
                or Analysis
            )
            record.approved_plan_id = (
                record.plan_ids.filtered(lambda r: r.status == "approved").sorted(
                    lambda r: (r.revision, r.id), reverse=True
                )[:1]
                or Plan
            )
            record.current_checkpoint_id = (
                record.checkpoint_ids.sorted(
                    lambda r: (r.captured_at, r.id), reverse=True
                )[:1]
                or Checkpoint
            )
            record.completion_report_id = (
                record.completion_report_ids.filtered(
                    lambda r: r.status == "approved"
                ).sorted(lambda r: (r.revision, r.id), reverse=True)[:1]
                or record.completion_report_ids.sorted(
                    lambda r: (r.revision, r.id), reverse=True
                )[:1]
                or Report
            )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("current_phase", "received") != "received":
                raise ValidationError("Work items must be created in Received state.")
            task = self.env["project.task"].browse(vals.get("odoo_task_id")).exists()
            if task:
                vals.setdefault("odoo_project_id", task.project_id.id)
                vals.setdefault("op_backend_id", task.op_backend_id.id)
                vals.setdefault("op_work_package_id", task.op_work_package_id)
                vals.setdefault("op_url", task.op_url)
                vals.setdefault("priority_cache", task.priority or "0")
                vals.setdefault("deadline_cache", task.date_deadline)
            _validate_text_values(self, vals)
            _clean_text(vals.get("name"), "Work item title", 300)
        records = super().create(vals_list)
        for record in records:
            if not record.source_message_ids:
                raise ValidationError(
                    "A Received work item requires at least one source message."
                )
            record._refresh_context_revision()
            record._append_lifecycle_event(False, "received", "Work item created")
        return records

    def write(self, vals):
        if {"uuid", "current_phase", "context_revision", "cancellation_reason"} & set(vals):
            raise AccessError("Protected work-item fields can change only through actions.")
        _validate_text_values(self, vals)
        _clean_text(vals.get("name"), "Work item title", 300)
        result = super().write(vals)
        if {
            "dev_project_id",
            "odoo_project_id",
            "odoo_task_id",
            "op_backend_id",
            "op_work_package_id",
            "preferred_repository_id",
            "preferred_environment_id",
        } & set(vals):
            self._refresh_context_revision()
        return result

    @api.constrains(
        "dev_project_id",
        "odoo_project_id",
        "odoo_task_id",
        "op_backend_id",
        "op_work_package_id",
        "preferred_repository_id",
        "preferred_environment_id",
    )
    def _check_identity_consistency(self):
        for record in self:
            task = record.odoo_task_id
            if task:
                if task.project_id != record.odoo_project_id:
                    raise ValidationError("The Odoo task must belong to the selected project.")
                if task.op_backend_id and record.op_backend_id != task.op_backend_id:
                    raise ValidationError("Work item and Odoo task OP backends must match.")
                if (
                    task.op_work_package_id
                    and record.op_work_package_id != task.op_work_package_id
                ):
                    raise ValidationError("Work item and Odoo task OP package IDs must match.")
                if record.op_backend_id and not task.op_backend_id:
                    raise ValidationError("The linked Odoo task has no matching OP backend.")
                if record.op_work_package_id and not task.op_work_package_id:
                    raise ValidationError("The linked Odoo task has no matching OP package ID.")
            if bool(record.op_backend_id) != bool(record.op_work_package_id):
                raise ValidationError("OP backend and work-package ID must be set together.")
            if (
                record.preferred_repository_id
                and record.preferred_repository_id.project_id != record.dev_project_id
            ):
                raise ValidationError("Preferred repository must belong to the Dev project.")
            if (
                record.preferred_environment_id
                and record.preferred_environment_id.project_id != record.dev_project_id
            ):
                raise ValidationError("Preferred environment must belong to the Dev project.")

    def _refresh_context_revision(self):
        for record in self:
            payload = {
                "uuid": record.uuid,
                "phase": record.current_phase,
                "task": record.odoo_task_id.id or None,
                "backend": record.op_backend_id.id or None,
                "wp": record.op_work_package_id or None,
                "analysis": record.current_analysis_id.content_hash or None,
                "plan": record.approved_plan_id.content_hash or None,
                "checkpoint": record.current_checkpoint_id.snapshot_hash or None,
            }
            super(DevWorkItem, record).write({"context_revision": _canonical_hash(payload)})

    def _append_lifecycle_event(
        self, old_phase, new_phase, reason, actor_type="human", artifact=None, policy=None
    ):
        self.ensure_one()
        reason = _clean_text(reason, "Lifecycle reason", 1000)
        self.env["dev.work.lifecycle.event"].with_context(
            dev_internal_event=True
        ).sudo().create(
            {
                "work_item_id": self.id,
                "old_phase": old_phase or False,
                "new_phase": new_phase,
                "actor_type": actor_type,
                "actor_id": self.env.context.get("dev_integration_actor_id")
                or self.env.user.id,
                "occurred_at": fields.Datetime.now(),
                "reason": reason,
                "artifact_model": artifact._name if artifact else False,
                "artifact_record_id": artifact.id if artifact else False,
                "artifact_revision": getattr(artifact, "revision", 0) if artifact else 0,
                "artifact_hash": (
                    getattr(artifact, "content_hash", False)
                    or getattr(artifact, "snapshot_hash", False)
                    if artifact
                    else False
                ),
                "policy_decision": _clean_text(policy, "Policy decision", 1000),
                "correlation_id": _uuid(),
            }
        )

    def _validate_transition_requirements(self, new_phase):
        self.ensure_one()
        if new_phase == "received" and not self.source_message_ids:
            raise UserError("Received work requires at least one source message.")
        if new_phase == "registered":
            if not (
                self.odoo_task_id
                and self.op_backend_id
                and self.op_work_package_id
                and self.odoo_task_id.op_backend_id == self.op_backend_id
                and self.odoo_task_id.op_work_package_id == self.op_work_package_id
            ):
                raise UserError("Registration requires a verified OP-backed Odoo task.")
        elif new_phase == "planning":
            if not self.analysis_ids:
                raise UserError("Planning requires an analysis revision.")
        elif new_phase == "awaiting_plan_approval":
            plan = self.plan_ids.filtered(lambda p: p.status == "awaiting_approval")[:1]
            if not plan or not plan._is_complete():
                raise UserError("Approval requires a complete plan revision.")
        elif new_phase == "approved":
            if not self.approved_plan_id:
                raise UserError("The exact plan revision must be approved first.")
        elif new_phase == "implementing":
            if not self.approved_plan_id:
                raise UserError("Implementation requires an approved exact plan hash.")
            if not self.preferred_repository_id or not self.preferred_environment_id:
                raise UserError("Implementation requires registered repository and environment.")
            self.preferred_environment_id._assert_dev_hub_safe(self.dev_project_id)
        elif new_phase == "paused":
            if (
                not self.current_checkpoint_id
                or self.current_checkpoint_id.lifecycle_phase != self.current_phase
            ):
                raise UserError("Pausing requires an immutable checkpoint.")
        elif new_phase == "testing":
            if not self.plan_ids.mapped("step_ids").filtered(
                lambda s: s.status in ("in_progress", "done")
            ):
                raise UserError("Testing requires recorded implementation progress.")
        elif new_phase == "ready_for_review":
            if not self.current_checkpoint_id:
                raise UserError("Review requires a current checkpoint.")
            report = self.completion_report_ids.filtered(
                lambda r: r.status in ("ready_review", "approved")
            )
            if not report:
                raise UserError("Review requires a completion report ready for review.")
        elif new_phase == "completed":
            if not self.completion_report_ids.filtered(lambda r: r.status == "approved"):
                raise UserError("Completion requires an approved completion report.")
        elif new_phase == "reported":
            if not self.communication_ids.filtered(lambda c: c.state == "queued"):
                raise UserError("Reported requires a reviewed message handed to the outbox.")

    def transition_lifecycle(
        self, new_phase, reason, actor_type="human", artifact=None, policy=None
    ):
        self.ensure_one()
        self.env.cr.execute("SELECT id FROM dev_work_item WHERE id = %s FOR UPDATE", [self.id])
        self.invalidate_recordset()
        if new_phase not in LIFECYCLE_TRANSITIONS.get(self.current_phase, set()):
            raise UserError(
                "Invalid work lifecycle transition: %s → %s"
                % (self.current_phase, new_phase)
            )
        reason = _clean_text(reason, "Lifecycle reason", 1000)
        if new_phase in ("blocked", "cancelled") and not reason:
            raise UserError("Blocked and cancelled transitions require a reason.")
        self._validate_transition_requirements(new_phase)
        old_phase = self.current_phase
        vals = {"current_phase": new_phase}
        if new_phase == "blocked":
            vals.update(blocked_from_phase=old_phase, blocker=reason)
        elif old_phase == "blocked":
            vals.update(blocked_from_phase=False, blocker=False)
        if new_phase == "cancelled":
            vals["cancellation_reason"] = reason
        super(DevWorkItem, self).write(vals)
        self._append_lifecycle_event(
            old_phase, new_phase, reason, actor_type, artifact, policy
        )
        self._refresh_context_revision()
        return True

    def action_triage(self):
        return self.transition_lifecycle("triage", "Intake moved to triage")

    def action_start_triage(self):
        return self.action_triage()

    def action_register(self):
        return self.transition_lifecycle("registered", "External identity verified")

    def action_analyze(self):
        return self.transition_lifecycle("analyzing", "Analysis started")

    def action_start_analysis(self):
        return self.action_analyze()

    def action_plan(self):
        return self.transition_lifecycle("planning", "Planning started")

    def action_start_planning(self):
        return self.action_plan()

    def action_request_plan_approval(self):
        return self.transition_lifecycle(
            "awaiting_plan_approval", "Plan submitted for exact-hash approval"
        )

    def action_start_implementation(self):
        return self.transition_lifecycle(
            "implementing", "Implementation explicitly started"
        )

    def action_start_testing(self):
        return self.transition_lifecycle("testing", "Testing started")

    def action_ready_for_review(self):
        self.ensure_one()
        if (
            not self.current_checkpoint_id
            or self.current_checkpoint_id.lifecycle_phase != self.current_phase
        ):
            session = self.session_ids.sorted(
                lambda item: (item.write_date, item.id), reverse=True
            )[:1]
            if not session:
                raise UserError("Ready for review requires a session checkpoint.")
            session._create_work_checkpoint("client_review")
        return self.transition_lifecycle("ready_for_review", "Ready for human review")

    def action_complete(self):
        return self.transition_lifecycle("completed", "Completion report approved")

    def action_reported(self):
        return self.transition_lifecycle("reported", "Outbound handoff recorded")

    def action_resume(self):
        self.ensure_one()
        target = (
            self.blocked_from_phase
            if self.current_phase == "blocked" and self.blocked_from_phase
            else "implementing"
        )
        return self.transition_lifecycle(target, "Work resumed from checkpoint")

    def action_pause(self):
        self.ensure_one()
        if (
            not self.current_checkpoint_id
            or self.current_checkpoint_id.lifecycle_phase != self.current_phase
        ):
            session = self.session_ids.filtered(
                lambda item: item.state in ("started", "in_progress", "resumed", "paused")
            ).sorted(lambda item: (item.write_date, item.id), reverse=True)[:1]
            if not session:
                raise UserError("Pausing requires a linked session checkpoint.")
            session._create_work_checkpoint("pause")
        return self.transition_lifecycle("paused", "Work paused at latest checkpoint")

    def action_block(self, reason=None):
        reason = reason or self.blocker or self.env.context.get("dev_transition_reason")
        if not reason:
            raise UserError("Record a blocker reason before blocking work.")
        return self.transition_lifecycle("blocked", reason)

    def action_cancel(self, reason=None):
        reason = reason or self.env.context.get("dev_transition_reason")
        if not reason:
            raise UserError("Cancellation requires an explicit reason.")
        return self.transition_lifecycle("cancelled", reason)

    def action_report(self):
        return self.action_reported()

    def action_open_openproject(self):
        self.ensure_one()
        url = self.op_url or self.odoo_task_id.op_url
        if not url:
            raise UserError("No OpenProject URL is available.")
        return {"type": "ir.actions.act_url", "url": url, "target": "new"}

    def action_open_odoo_task(self):
        self.ensure_one()
        if not self.odoo_task_id:
            raise UserError("No Odoo task is linked.")
        return {
            "type": "ir.actions.act_window",
            "res_model": "project.task",
            "res_id": self.odoo_task_id.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_open_source_conversation(self):
        self.ensure_one()
        message = self.source_message_ids.filtered(lambda m: m.source_url)[:1]
        if not message:
            raise UserError("No source conversation URL is available.")
        return {"type": "ir.actions.act_url", "url": message.source_url, "target": "new"}

    def build_resume_brief(self, session=None):
        self.ensure_one()
        if session:
            session.ensure_one()
            if session.work_item_id != self:
                raise ValidationError("The session does not belong to this work item.")
        analysis = self.current_accepted_analysis_id
        plan = self.approved_plan_id
        checkpoint = self.current_checkpoint_id
        workspace = session.execution_workspace_id if session else self.execution_workspace_id
        source = self.source_message_ids.sorted(
            lambda r: (r.message_timestamp or fields.Datetime.now(), r.id)
        )[:3]
        steps = plan.step_ids.sorted(lambda r: (r.sequence, r.id)) if plan else []
        source_text = "\n".join(
            "- %s" % _bounded(message.text_snapshot, 900) for message in source
        ) or "- No sanitized source snapshot."
        step_text = "\n".join(
            "- [%s] %s: %s"
            % ("x" if step.status == "done" else " ", step.step_key, step.title)
            for step in steps[:40]
        ) or "- No approved plan steps."
        lines = [
            "# Development Resume Brief",
            "",
            "Context revision: `%s`" % (self.context_revision or "unavailable"),
            "Work item: %s (`%s`)" % (self.name, self.uuid),
            "Lifecycle: %s" % self.current_phase,
            "OpenProject: %s" % (self.op_url or self.op_work_package_id or "unlinked"),
            "Odoo task: %s" % (self.odoo_task_id.display_name or "unlinked"),
            "",
            "## Source request",
            source_text,
            "",
            "## Accepted analysis",
            _bounded(analysis.problem_summary, 1800) if analysis else "No analysis.",
            "",
            "## Approved plan",
            (
                "Revision %s, hash `%s`, progress %s / %s\n\n%s"
                % (
                    plan.revision,
                    plan.content_hash,
                    self.completed_step_count,
                    self.actionable_step_count,
                    _bounded(plan.goal, 1200),
                )
                if plan
                else "No approved plan."
            ),
            step_text,
            "",
            "## Execution workspace",
            (
                "Workspace: %s\nBranch: %s\nWorktree: %s\nBase HEAD: %s\n"
                "Current HEAD: %s\nPlan: Revision %s\nProgress: %s/%s"
                % (
                    workspace.name,
                    workspace.execution_branch,
                    workspace.worktree_path,
                    workspace.base_head,
                    workspace.current_head or "unavailable",
                    workspace.plan_revision,
                    self.completed_step_count,
                    self.actionable_step_count,
                )
                if workspace
                else "No isolated execution workspace."
            ),
            "",
            "## Latest checkpoint",
            (
                "Next: %s\nBlockers: %s\nDecisions: %s\nPending decisions: %s\n"
                "Remaining: %s\nGit baseline: %s @ %s (%s)"
                % (
                    _bounded(checkpoint.next_recommended_step, 700),
                    _bounded(checkpoint.blockers, 700) or "none",
                    _bounded(checkpoint.decisions_made, 700) or "none",
                    _bounded(checkpoint.pending_decisions, 700) or "none",
                    checkpoint.remaining_step_keys or "none",
                    checkpoint.branch or "unavailable",
                    checkpoint.git_head or "unavailable",
                    checkpoint.dirty_summary or "unavailable",
                )
                if checkpoint
                else "No checkpoint."
            ),
            "",
            "## Current session",
            (
                "Environment: %s\nMachine: %s\nClient: %s\nWorking directory: %s\n"
                "Current Git: %s @ %s\nDrift: %s"
                % (
                    session.environment_id.name,
                    session.machine_id.name,
                    session.client_id.name,
                    session.working_directory,
                    session.git_branch_snapshot or "unavailable",
                    session.git_head_snapshot or "unavailable",
                    session.drift_warning or "none",
                )
                if session
                else "No session selected."
            ),
            "",
            "## Guardrails",
            "- No production access or deployment.",
            "- No automatic branch switch, commit, push, service restart, or Docker action.",
            "- Follow only the approved plan hash and create a checkpoint before handoff.",
            "",
            "## Exact recommended next action",
            (
                _bounded(checkpoint.next_recommended_step, 1000)
                if checkpoint
                else "Create a checkpoint before continuing implementation."
            ),
        ]
        brief = _clean_text("\n".join(lines), "Resume brief", MAX_BRIEF)
        return brief, self.context_revision

    @api.model
    def import_analysis_draft(self, payload):
        """Strict authenticated RPC callback; it never executes code or starts work."""
        _require_importer(self.env)
        actor_id = self.env.user.id
        if not isinstance(payload, dict):
            raise ValidationError("Analysis import must be a JSON object.")
        allowed = {
            "work_item_uuid",
            "problem_summary",
            "original_request_summary",
            "reproduction_context",
            "current_behavior",
            "expected_behavior",
            "technical_findings",
            "affected_components",
            "risks",
            "dependencies",
            "open_questions",
            "evidence_references",
            "model_reference",
            "provider_reference",
            "run_reference",
            "observed_head",
        }
        unknown = set(payload) - allowed
        if unknown:
            raise ValidationError(
                "Unsupported analysis import fields: %s" % ", ".join(sorted(unknown))
            )
        required = ("problem_summary", "original_request_summary")
        missing = [name for name in required if not payload.get(name)]
        if missing:
            raise ValidationError(
                "Analysis import requires: %s." % ", ".join(missing)
            )
        work = self.sudo().with_context(
            dev_integration_actor_id=actor_id
        ).search([("uuid", "=", payload.get("work_item_uuid"))], limit=1)
        if not work:
            raise ValidationError("Unknown Work Item UUID.")
        if work.current_phase == "registered":
            work.transition_lifecycle(
                "analyzing", "Bounded analysis draft imported", actor_type="automation"
            )
        if work.current_phase != "analyzing":
            raise UserError("Analysis drafts may be imported only while Analyzing.")
        values = {key: value for key, value in payload.items() if key != "work_item_uuid"}
        values.update(
            work_item_id=work.id,
            status="generated",
            origin="generated",
            repository_id=work.preferred_repository_id.id,
            generated_at=fields.Datetime.now(),
            author_id=actor_id,
        )
        return self.env["dev.work.analysis"].sudo().create(values).id

    @api.model
    def import_merged_analysis_draft(self, payload):
        """Strict callback for the guarded 'merge_analysis' generation kind.

        Creates a new mixed-origin analysis revision that consolidates a base
        analysis with the human 'My Analysis' notes. It never overwrites the
        base revision; traceability links the new revision back to its base.
        """
        _require_importer(self.env)
        actor_id = self.env.user.id
        if not isinstance(payload, dict):
            raise ValidationError("Merged analysis import must be a JSON object.")
        allowed = {
            "work_item_uuid",
            "problem_summary",
            "original_request_summary",
            "reproduction_context",
            "current_behavior",
            "expected_behavior",
            "technical_findings",
            "affected_components",
            "risks",
            "dependencies",
            "open_questions",
            "evidence_references",
            "model_reference",
            "provider_reference",
            "run_reference",
            "observed_head",
            "base_analysis_id",
            "human_input_snapshot",
            "merged_by_id",
        }
        unknown = set(payload) - allowed
        if unknown:
            raise ValidationError(
                "Unsupported merged analysis fields: %s" % ", ".join(sorted(unknown))
            )
        required = ("problem_summary", "original_request_summary")
        missing = [name for name in required if not payload.get(name)]
        if missing:
            raise ValidationError(
                "Merged analysis import requires: %s." % ", ".join(missing)
            )
        work = self.sudo().with_context(
            dev_integration_actor_id=actor_id
        ).search([("uuid", "=", payload.get("work_item_uuid"))], limit=1)
        if not work:
            raise ValidationError("Unknown Work Item UUID.")
        if work.current_phase != "analyzing":
            raise UserError(
                "Merged analysis may be imported only while Analyzing."
            )
        base = self.env["dev.work.analysis"].sudo().browse(
            payload.get("base_analysis_id") or 0
        ).exists()
        if not base or base.work_item_id != work:
            raise ValidationError("The base analysis is unknown for this work item.")
        values = {
            key: value
            for key, value in payload.items()
            if key not in ("work_item_uuid", "base_analysis_id", "merged_by_id")
        }
        merged_by = self.env["res.users"].sudo().browse(
            payload.get("merged_by_id") or actor_id
        ).exists()
        values.update(
            work_item_id=work.id,
            status="generated",
            origin="mixed",
            parent_revision_id=base.id,
            base_analysis_id=base.id,
            merged_by_id=(merged_by.id if merged_by else actor_id),
            merged_at=fields.Datetime.now(),
            repository_id=(base.repository_id.id or work.preferred_repository_id.id),
            generated_at=fields.Datetime.now(),
            author_id=actor_id,
        )
        return self.env["dev.work.analysis"].sudo().create(values).id

    @api.model
    def import_plan_draft(self, payload):
        """Strict authenticated RPC callback; exact human approval remains mandatory."""
        _require_importer(self.env)
        actor_id = self.env.user.id
        if not isinstance(payload, dict):
            raise ValidationError("Plan import must be a JSON object.")
        allowed = {
            "work_item_uuid",
            "analysis_revision",
            "goal",
            "scope",
            "out_of_scope",
            "proposed_changes",
            "affected_components",
            "migration_impact",
            "security_impact",
            "test_plan",
            "rollback_plan",
            "dependencies",
            "risks",
            "acceptance_criteria",
            "run_reference",
            "steps",
        }
        unknown = set(payload) - allowed
        if unknown:
            raise ValidationError(
                "Unsupported plan import fields: %s" % ", ".join(sorted(unknown))
            )
        required = (
            "goal",
            "scope",
            "out_of_scope",
            "proposed_changes",
            "affected_components",
            "migration_impact",
            "security_impact",
            "test_plan",
            "rollback_plan",
            "dependencies",
            "risks",
            "acceptance_criteria",
        )
        missing = [name for name in required if not payload.get(name)]
        if missing:
            raise ValidationError("Plan import requires: %s." % ", ".join(missing))
        work = self.sudo().with_context(
            dev_integration_actor_id=actor_id
        ).search([("uuid", "=", payload.get("work_item_uuid"))], limit=1)
        if not work:
            raise ValidationError("Unknown Work Item UUID.")
        analysis = work.analysis_ids.filtered(lambda item: item.status == "accepted")
        if payload.get("analysis_revision"):
            analysis = analysis.filtered(
                lambda item: item.revision == payload["analysis_revision"]
            )
        analysis = analysis.sorted(lambda item: (item.revision, item.id), reverse=True)[:1]
        if not analysis:
            raise UserError("Plan import requires an accepted analysis revision.")
        if work.current_phase == "analyzing":
            work.transition_lifecycle(
                "planning", "Bounded plan draft imported", actor_type="automation"
            )
        if work.current_phase != "planning":
            raise UserError("Plan drafts may be imported only while Planning.")
        steps = payload.get("steps") or []
        if not isinstance(steps, list) or not 1 <= len(steps) <= 30:
            raise ValidationError("Plan steps must contain between 1 and 30 items.")
        values = {
            key: value
            for key, value in payload.items()
            if key not in ("work_item_uuid", "analysis_revision", "steps")
        }
        values.update(
            work_item_id=work.id,
            analysis_id=analysis.id,
            status="draft",
            origin="generated",
            generated_at=fields.Datetime.now(),
            author_id=actor_id,
        )
        plan = self.env["dev.work.plan"].sudo().with_context(
            dev_integration_actor_id=actor_id
        ).create(values)
        step_allowed = {
            "step_key",
            "sequence",
            "title",
            "description",
            "dependency_keys",
            "acceptance_evidence",
        }
        for item in steps:
            if not isinstance(item, dict) or set(item) - step_allowed:
                raise ValidationError("Plan step import contains unsupported fields.")
            self.env["dev.work.plan.step"].sudo().create({"plan_id": plan.id, **item})
        return plan.id

    def _queue_outbox(
        self, channel, operation, payload, idempotency_key, communication=None
    ):
        self.ensure_one()
        lock_key = int(
            hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()[:16], 16
        ) & 0x7FFFFFFFFFFFFFFF
        self.env.cr.execute("SELECT pg_advisory_xact_lock(%s)", [lock_key])
        existing = self.env["dev.external.outbox"].sudo().search(
            [("idempotency_key", "=", idempotency_key)], limit=1
        )
        if existing:
            return existing
        return self.env["dev.external.outbox"].with_context(
            dev_internal_outbox=True
        ).sudo().create(
            {
                "work_item_id": self.id,
                "channel": channel,
                "operation": operation,
                "payload_json": payload,
                "idempotency_key": idempotency_key,
                "communication_id": communication.id if communication else False,
            }
        )

    def _prepare_op_milestone(self, milestone, summary, status_hint=None, link=None):
        self.ensure_one()
        if not self.op_backend_id or not self.op_work_package_id:
            raise UserError("An OP identity is required to prepare a milestone.")
        if milestone not in ("analysis_plan_ready", "material_blocker", "completion"):
            raise ValidationError("Only sparse approved OpenProject milestones are allowed.")
        summary = _clean_text(summary, "OpenProject milestone summary", 2000)
        payload = {
            "schema": "dev-hub.op-milestone.v1",
            "backend_id": self.op_backend_id.id,
            "work_package_id": self.op_work_package_id,
            "milestone": milestone,
            "summary": summary,
        }
        if status_hint:
            if status_hint not in ("new", "in_progress", "on_hold", "in_review", "closed"):
                raise ValidationError("Unsupported broad OpenProject status hint.")
            payload["status_hint"] = status_hint
        if link:
            payload["dev_hub_link"] = _clean_text(link, "Dev Hub link", 500)
        key = "op:%s:%s:%s:%s" % (
            self.op_backend_id.id,
            self.op_work_package_id,
            milestone,
            _canonical_hash(payload)[:16],
        )
        return self._queue_outbox("openproject", "milestone", payload, key)

    def action_prepare_analysis_plan_milestone(self):
        self.ensure_one()
        analysis = self.current_accepted_analysis_id
        plan = self.plan_ids.filtered(
            lambda p: p.status in ("awaiting_approval", "approved")
        ).sorted(lambda p: (p.revision, p.id), reverse=True)[:1]
        if not analysis or not plan:
            raise UserError(
                "This milestone requires accepted analysis and a submitted plan."
            )
        return self._prepare_op_milestone(
            "analysis_plan_ready",
            "Development analysis and plan revision %s are ready." % plan.revision,
            "in_progress",
        )

    def action_prepare_blocker_milestone(self):
        self.ensure_one()
        if self.current_phase != "blocked" or not self.blocker:
            raise UserError("A material blocker must be recorded first.")
        return self._prepare_op_milestone(
            "material_blocker", _bounded(self.blocker, 1800), "on_hold"
        )

    def action_prepare_completion_milestone(self):
        self.ensure_one()
        report = self.completion_report_ids.filtered(lambda r: r.status == "approved")[:1]
        if self.current_phase != "completed" or not report:
            raise UserError(
                "Completed lifecycle work and an approved report are required."
            )
        return self._prepare_op_milestone(
            "completion", _bounded(report.implemented_summary, 1800), "closed"
        )

    def _invalidate_effective_plan(self, reason):
        for record in self:
            if record.current_phase in ("approved", "implementing", "paused", "testing"):
                raise UserError(
                    "An approved plan cannot be changed during execution; create and "
                    "approve a new revision before starting implementation."
                )
            if record.current_phase == "awaiting_plan_approval":
                super(DevWorkItem, record).write({"current_phase": "planning"})
                record._append_lifecycle_event(
                    "awaiting_plan_approval", "planning", reason, "automation"
                )
            record._refresh_context_revision()


class DevWorkLifecycleEvent(models.Model):
    _name = "dev.work.lifecycle.event"
    _description = "Immutable Development Work Lifecycle Event"
    _order = "occurred_at desc, id desc"

    work_item_id = fields.Many2one(
        "dev.work.item", required=True, ondelete="restrict", index=True, readonly=True
    )
    old_phase = fields.Selection(LIFECYCLE_SELECTION, readonly=True)
    new_phase = fields.Selection(LIFECYCLE_SELECTION, required=True, readonly=True)
    actor_type = fields.Selection(
        [("human", "Human"), ("automation", "Automation"), ("agent", "Agent")],
        required=True,
        readonly=True,
    )
    actor_id = fields.Many2one(
        "res.users", required=True, ondelete="restrict", readonly=True
    )
    occurred_at = fields.Datetime(required=True, readonly=True, index=True)
    timestamp = fields.Datetime(related="occurred_at", readonly=True)
    from_phase = fields.Selection(related="old_phase", readonly=True)
    to_phase = fields.Selection(related="new_phase", readonly=True)
    reason = fields.Text(required=True, readonly=True)
    correlation_id = fields.Char(required=True, readonly=True, index=True)
    artifact_model = fields.Char(readonly=True)
    artifact_record_id = fields.Integer(readonly=True)
    artifact_revision = fields.Integer(readonly=True)
    artifact_hash = fields.Char(readonly=True)
    policy_decision = fields.Text(readonly=True)

    _correlation_unique = models.Constraint(
        "unique(correlation_id)", "Lifecycle correlation ID must be unique."
    )

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("dev_internal_event"):
            raise AccessError("Lifecycle events may be created only by lifecycle actions.")
        return super().create(vals_list)

    def write(self, vals):
        raise AccessError("Lifecycle events are immutable.")

    def unlink(self):
        raise AccessError("Lifecycle events are immutable.")


class DevWorkSourceMessage(models.Model):
    _name = "dev.work.source.message"
    _description = "Development Work Source Message"
    _order = "message_timestamp desc, id desc"

    provider = fields.Selection(
        [("evolution", "Evolution"), ("chatwoot", "Chatwoot"), ("manual", "Manual")],
        required=True,
        index=True,
    )
    instance_reference = fields.Char(index=True)
    evolution_instance_ref = fields.Char(related="instance_reference", readonly=False)
    provider_message_id = fields.Char(index=True)
    extracted_item_index = fields.Integer(default=0, required=True)
    dedupe_key = fields.Char(required=True, readonly=True, copy=False, index=True)
    evolution_message_id = fields.Char(index=True)
    group_jid = fields.Char()
    sender_jid = fields.Char()
    chatwoot_account_id = fields.Integer(index=True)
    chatwoot_inbox_id = fields.Integer(index=True)
    chatwoot_conversation_id = fields.Integer(index=True)
    chatwoot_message_id = fields.Integer(index=True)
    message_timestamp = fields.Datetime(
        required=True, default=fields.Datetime.now, index=True
    )
    text_snapshot = fields.Text(required=True)
    sanitized_text = fields.Text(related="text_snapshot", readonly=False)
    text_hash = fields.Char(required=True, readonly=True)
    content_hash = fields.Char(related="text_hash", readonly=True)
    attachment_references = fields.Text(
        help="Sanitized URLs or opaque attachment references only; no attachment payload."
    )
    source_url = fields.Char()
    work_item_ids = fields.Many2many(
        "dev.work.item",
        "dev_work_item_source_message_rel",
        "source_message_id",
        "work_item_id",
    )

    _dedupe_unique = models.Constraint(
        "unique(dedupe_key)", "Source message extraction must be unique."
    )
    _provider_message_unique = models.UniqueIndex(
        "(provider, instance_reference, provider_message_id, extracted_item_index) "
        "WHERE provider_message_id IS NOT NULL",
        "This provider message extraction already exists.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            _normalize_aliases(
                vals,
                {
                    "evolution_instance_ref": "instance_reference",
                    "sanitized_text": "text_snapshot",
                },
            )
            _validate_text_values(self, vals, 6000)
            snapshot = _clean_text(vals.get("text_snapshot"), "Source text", 6000)
            if not snapshot:
                raise ValidationError("A sanitized source text snapshot is required.")
            identity = {
                "provider": vals.get("provider"),
                "instance": vals.get("instance_reference") or "",
                "message": vals.get("provider_message_id")
                or vals.get("chatwoot_message_id")
                or "",
                "index": vals.get("extracted_item_index", 0),
            }
            if not identity["message"]:
                raise ValidationError("A provider or Chatwoot message identity is required.")
            vals["dedupe_key"] = _canonical_hash(identity)
            vals["text_snapshot"] = snapshot
            vals["text_hash"] = _canonical_hash({"text": snapshot})
            _clean_text(vals.get("attachment_references"), "Attachment references", 4000)
        return super().create(vals_list)

    def write(self, vals):
        vals = dict(vals)
        _normalize_aliases(
            vals,
            {
                "evolution_instance_ref": "instance_reference",
                "sanitized_text": "text_snapshot",
            },
        )
        if {
            "provider",
            "instance_reference",
            "provider_message_id",
            "extracted_item_index",
            "dedupe_key",
            "text_snapshot",
            "text_hash",
        } & set(vals):
            raise AccessError("Source identity and sanitized snapshot are immutable.")
        _validate_text_values(self, vals, 6000)
        _clean_text(vals.get("attachment_references"), "Attachment references", 4000)
        return super().write(vals)


class DevWorkExternalLink(models.Model):
    _name = "dev.work.external.link"
    _description = "Development Work External Link"
    _order = "link_type, id"

    work_item_id = fields.Many2one(
        "dev.work.item", required=True, ondelete="cascade", index=True
    )
    link_type = fields.Selection(
        [
            ("github_issue", "GitHub Issue"),
            ("github_pr", "GitHub Pull Request"),
            ("commit", "Git Commit"),
            ("chatwoot", "Chatwoot"),
            ("attachment", "Attachment"),
            ("evidence", "Evidence"),
            ("other", "Other"),
        ],
        required=True,
        index=True,
    )
    name = fields.Char(required=True)
    external_id = fields.Char(index=True)
    external_reference = fields.Char(related="external_id", readonly=False)
    url = fields.Char(required=True)
    sync_state = fields.Selection(
        [("reference", "Reference"), ("synced", "Synced"), ("stale", "Stale")],
        default="reference",
        required=True,
    )
    last_sync_at = fields.Datetime()
    metadata_summary = fields.Text()

    _typed_external_unique = models.UniqueIndex(
        "(work_item_id, link_type, external_id) WHERE external_id IS NOT NULL",
        "This external identity is already linked to the work item.",
    )

    @api.constrains("name", "url", "metadata_summary")
    def _check_safe_fields(self):
        for record in self:
            _clean_text(record.name, "External link name", 300)
            _clean_text(record.url, "External link URL", 1000)
            _clean_text(record.metadata_summary, "External link metadata", 2000)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            _normalize_aliases(vals, {"external_reference": "external_id"})
            _validate_text_values(self, vals, 2000)
        return super().create(vals_list)

    def write(self, vals):
        vals = dict(vals)
        _normalize_aliases(vals, {"external_reference": "external_id"})
        _validate_text_values(self, vals, 2000)
        return super().write(vals)


class DevWorkAnalysis(models.Model):
    _name = "dev.work.analysis"
    _description = "Versioned Development Work Analysis"
    _order = "work_item_id, revision desc"

    work_item_id = fields.Many2one(
        "dev.work.item", required=True, ondelete="cascade", index=True
    )
    revision = fields.Integer(required=True, readonly=True, copy=False)
    parent_revision_id = fields.Many2one(
        "dev.work.analysis", ondelete="restrict", readonly=True, copy=False
    )
    content_hash = fields.Char(required=True, readonly=True, copy=False, index=True)
    status = fields.Selection(
        [
            ("draft", "Draft"),
            ("generated", "Generated"),
            ("reviewed", "Reviewed"),
            ("accepted", "Accepted"),
            ("rejected", "Rejected"),
            ("superseded", "Superseded"),
        ],
        default="draft",
        required=True,
        index=True,
    )
    origin = fields.Selection(
        [("manual", "Manual"), ("generated", "Generated"), ("mixed", "Mixed")],
        required=True,
        default="manual",
    )
    problem_summary = fields.Text(required=True)
    original_request_summary = fields.Text()
    original_request_snapshot = fields.Text(
        related="original_request_summary", readonly=False
    )
    reproduction_context = fields.Text()
    current_behavior = fields.Text()
    expected_behavior = fields.Text()
    technical_findings = fields.Text()
    affected_components = fields.Text()
    affected_modules_files = fields.Text(
        related="affected_components", readonly=False
    )
    risks = fields.Text()
    dependencies = fields.Text()
    open_questions = fields.Text()
    evidence_references = fields.Text()
    user_analysis_notes = fields.Text(
        string="My Analysis",
        help="Your own analysis notes. Editable separately from generated findings "
        "and excluded from the accepted content hash.",
    )
    agent_reference = fields.Char()
    agent_name = fields.Char(related="agent_reference", readonly=False)
    model_reference = fields.Char()
    model_name = fields.Char(related="model_reference", readonly=False)
    provider_reference = fields.Char()
    provider_name = fields.Char(related="provider_reference", readonly=False)
    run_reference = fields.Char()
    prompt_version = fields.Char()
    template_version = fields.Char()
    schema_version = fields.Char(default="dev-work-analysis.v1", required=True)
    repository_id = fields.Many2one("dev.repository", ondelete="restrict")
    observed_head = fields.Char()
    generated_at = fields.Datetime()
    created_date = fields.Datetime(related="create_date", readonly=True)
    author_id = fields.Many2one(
        "res.users", required=True, default=lambda self: self.env.user, ondelete="restrict"
    )
    # Traceability for human-driven "Merge & Improve Analysis" revisions.
    base_analysis_id = fields.Many2one(
        "dev.work.analysis", ondelete="restrict", readonly=True, copy=False,
        help="The pre-merge analysis this revision consolidated with human input.",
    )
    human_input_snapshot = fields.Text(
        readonly=True, copy=False,
        help="Frozen copy of the My Analysis notes that fed the merge.",
    )
    merged_by_id = fields.Many2one(
        "res.users", ondelete="restrict", readonly=True, copy=False,
        help="User who triggered the semantic merge.",
    )
    merged_at = fields.Datetime(readonly=True, copy=False)

    _revision_unique = models.Constraint(
        "unique(work_item_id, revision)", "Analysis revision must be unique per work item."
    )

    def _hash_values(self, values=None):
        self.ensure_one()
        values = values or {}
        names = (
            "problem_summary",
            "original_request_summary",
            "reproduction_context",
            "current_behavior",
            "expected_behavior",
            "technical_findings",
            "affected_components",
            "risks",
            "dependencies",
            "open_questions",
            "evidence_references",
            "schema_version",
            "observed_head",
        )
        return _canonical_hash(
            {name: values.get(name, self[name]) or "" for name in names}
        )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            _normalize_aliases(
                vals,
                {
                    "original_request_snapshot": "original_request_summary",
                    "affected_modules_files": "affected_components",
                    "agent_name": "agent_reference",
                    "model_name": "model_reference",
                    "provider_name": "provider_reference",
                },
            )
            work_item = self.env["dev.work.item"].browse(vals.get("work_item_id")).exists()
            if not work_item:
                raise ValidationError("Analysis requires a work item.")
            latest = self.search(
                [("work_item_id", "=", work_item.id)], order="revision desc", limit=1
            )
            vals["revision"] = latest.revision + 1 if latest else 1
            vals["content_hash"] = "pending"
            if vals.get("status") == "accepted":
                raise ValidationError("Use the explicit Accept action.")
            for name, value in vals.items():
                if name in self._fields and self._fields[name].type in ("char", "text"):
                    label = self._fields[name].string or name
                    if name == "user_analysis_notes":
                        _clean_note_text(value, label)
                    else:
                        _clean_text(value, label)
        records = super().create(vals_list)
        for record in records:
            super(DevWorkAnalysis, record).write(
                {"content_hash": record._hash_values()}
            )
        return records

    def write(self, vals):
        vals = dict(vals)
        _normalize_aliases(
            vals,
            {
                "original_request_snapshot": "original_request_summary",
                "affected_modules_files": "affected_components",
                "agent_name": "agent_reference",
                "model_name": "model_reference",
                "provider_name": "provider_reference",
            },
        )
        user_note_keys = {"user_analysis_notes"}
        only_user_notes = bool(vals) and set(vals.keys()) <= user_note_keys
        if any(record.status == "superseded" for record in self) and not only_user_notes:
            raise AccessError("Accepted and superseded analyses are immutable.")
        if any(record.status == "superseded" for record in self) and only_user_notes:
            raise AccessError("Superseded analyses cannot receive new notes.")
        if any(record.status == "accepted" for record in self) and not only_user_notes:
            raise AccessError("Accepted and superseded analyses are immutable.")
        if {"revision", "parent_revision_id", "content_hash", "work_item_id"} & set(vals):
            raise AccessError("Analysis revision identity is immutable.")
        if vals.get("status") == "accepted":
            raise AccessError("Use the explicit Accept action.")
        for name, value in vals.items():
            field = self._fields.get(name)
            if field and field.type in ("char", "text"):
                label = field.string or name
                if name == "user_analysis_notes":
                    _clean_note_text(value, label)
                else:
                    _clean_text(value, label)
        result = super().write(vals)
        if only_user_notes:
            return result
        for record in self:
            super(DevWorkAnalysis, record).write(
                {"content_hash": record._hash_values()}
            )
        return result

    def action_accept(self):
        self.ensure_one()
        if self.work_item_id.current_phase != "analyzing":
            raise UserError("Analysis acceptance requires the Analyzing phase.")
        if self.status not in ("draft", "generated", "reviewed"):
            raise UserError("Only a working analysis revision can be accepted.")
        old = self.work_item_id.analysis_ids.filtered(
            lambda r: r.status == "accepted" and r != self
        )
        if old:
            super(DevWorkAnalysis, old).write({"status": "superseded"})
        super(DevWorkAnalysis, self).write({"status": "accepted"})
        self.work_item_id._refresh_context_revision()
        return True

    def action_new_revision(self):
        self.ensure_one()
        values = self.copy_data()[0]
        values.update(
            parent_revision_id=self.id,
            status="draft",
            content_hash=False,
            revision=0,
        )
        return self.create(values)


class DevWorkPlan(models.Model):
    _name = "dev.work.plan"
    _description = "Versioned Development Work Plan"
    _order = "work_item_id, revision desc"

    work_item_id = fields.Many2one(
        "dev.work.item", required=True, ondelete="cascade", index=True
    )
    revision = fields.Integer(required=True, readonly=True, copy=False)
    parent_revision_id = fields.Many2one(
        "dev.work.plan", ondelete="restrict", readonly=True, copy=False
    )
    analysis_id = fields.Many2one("dev.work.analysis", ondelete="restrict")
    content_hash = fields.Char(required=True, readonly=True, copy=False, index=True)
    status = fields.Selection(
        [
            ("draft", "Draft"),
            ("awaiting_approval", "Awaiting Approval"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
            ("superseded", "Superseded"),
        ],
        default="draft",
        required=True,
        index=True,
    )
    origin = fields.Selection(
        [("manual", "Manual"), ("generated", "Generated"), ("mixed", "Mixed")],
        required=True,
        default="manual",
    )
    generated_by = fields.Selection(
        related="origin", readonly=False
    )
    goal = fields.Text(required=True)
    scope = fields.Text(required=True)
    out_of_scope = fields.Text(required=True)
    proposed_changes = fields.Text(required=True)
    affected_components = fields.Text(required=True)
    affected_modules_files = fields.Text(
        related="affected_components", readonly=False
    )
    migration_impact = fields.Text(required=True)
    security_impact = fields.Text(required=True)
    test_plan = fields.Text(required=True)
    rollback_plan = fields.Text(required=True)
    dependencies = fields.Text(required=True)
    risks = fields.Text(required=True)
    acceptance_criteria = fields.Text(required=True)
    schema_version = fields.Char(default="dev-work-plan.v1", required=True)
    author_id = fields.Many2one(
        "res.users", required=True, default=lambda self: self.env.user, ondelete="restrict"
    )
    generated_at = fields.Datetime()
    agent_reference = fields.Char()
    run_reference = fields.Char(related="agent_reference", readonly=False)
    step_ids = fields.One2many("dev.work.plan.step", "plan_id")
    approval_ids = fields.One2many("dev.work.approval", "plan_id", readonly=True)
    progress = fields.Float(compute="_compute_progress")

    _revision_unique = models.Constraint(
        "unique(work_item_id, revision)", "Plan revision must be unique per work item."
    )

    @api.depends("step_ids.status")
    def _compute_progress(self):
        for record in self:
            actionable = record.step_ids.filtered(lambda step: step.status != "skipped")
            done = actionable.filtered(lambda step: step.status == "done")
            record.progress = 100.0 * len(done) / len(actionable) if actionable else 0.0

    def _hash_values(self, values=None):
        self.ensure_one()
        values = values or {}
        names = (
            "goal",
            "scope",
            "out_of_scope",
            "proposed_changes",
            "affected_components",
            "migration_impact",
            "security_impact",
            "test_plan",
            "rollback_plan",
            "dependencies",
            "risks",
            "acceptance_criteria",
            "schema_version",
        )
        steps = [
            {
                "key": step.step_key,
                "sequence": step.sequence,
                "title": step.title,
                "description": step.description or "",
                "acceptance": step.acceptance_evidence or "",
                "dependencies": step.dependency_keys or "",
                "parallel_group": step.parallel_group or "",
            }
            for step in self.step_ids.sorted(lambda r: (r.sequence, r.id))
        ]
        return _canonical_hash(
            {
                "fields": {name: values.get(name, self[name]) or "" for name in names},
                "steps": steps,
            }
        )

    def _is_complete(self):
        self.ensure_one()
        required = (
            self.goal,
            self.scope,
            self.out_of_scope,
            self.proposed_changes,
            self.affected_components,
            self.migration_impact,
            self.security_impact,
            self.test_plan,
            self.rollback_plan,
            self.dependencies,
            self.risks,
            self.acceptance_criteria,
        )
        return all((value or "").strip() for value in required) and bool(self.step_ids)

    def _refresh_hash(self):
        for record in self:
            super(DevWorkPlan, record).write({"content_hash": record._hash_values()})
            record.work_item_id._refresh_context_revision()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            _normalize_aliases(
                vals,
                {
                    "generated_by": "origin",
                    "affected_modules_files": "affected_components",
                    "run_reference": "agent_reference",
                },
            )
            work_item = self.env["dev.work.item"].browse(vals.get("work_item_id")).exists()
            if not work_item:
                raise ValidationError("Plan requires a work item.")
            latest = self.search(
                [("work_item_id", "=", work_item.id)], order="revision desc", limit=1
            )
            vals["revision"] = latest.revision + 1 if latest else 1
            vals["content_hash"] = "pending"
            if vals.get("status") == "approved":
                raise ValidationError("Use exact-hash plan approval.")
            for name, value in vals.items():
                field = self._fields.get(name)
                if field and field.type in ("char", "text"):
                    _clean_text(value, field.string or name)
        records = super().create(vals_list)
        records._refresh_hash()
        return records

    def write(self, vals):
        vals = dict(vals)
        _normalize_aliases(
            vals,
            {
                "generated_by": "origin",
                "affected_modules_files": "affected_components",
                "run_reference": "agent_reference",
            },
        )
        content_names = {
            "goal",
            "scope",
            "out_of_scope",
            "proposed_changes",
            "affected_components",
            "migration_impact",
            "security_impact",
            "test_plan",
            "rollback_plan",
            "dependencies",
            "risks",
            "acceptance_criteria",
            "schema_version",
        }
        if content_names & set(vals) and any(record.status != "draft" for record in self):
            raise AccessError(
                "Submitted plans are immutable; use the explicit New Revision action."
            )
        if any(record.status in ("approved", "superseded") for record in self):
            raise AccessError("Approved and superseded plans are immutable.")
        if {"revision", "parent_revision_id", "content_hash", "work_item_id"} & set(vals):
            raise AccessError("Plan revision identity is immutable.")
        if vals.get("status") == "approved":
            raise AccessError("Use exact-hash plan approval.")
        for name, value in vals.items():
            field = self._fields.get(name)
            if field and field.type in ("char", "text"):
                _clean_text(value, field.string or name)
        material_change = bool(content_names & set(vals))
        result = super().write(vals)
        if material_change:
            self._refresh_hash()
            self.mapped("work_item_id")._invalidate_effective_plan(
                "Material plan content changed"
            )
        return result

    def unlink(self):
        if any(record.status in ("approved", "superseded") for record in self):
            raise AccessError("Approved and superseded plans cannot be deleted.")
        return super().unlink()

    def action_submit_for_approval(self):
        self.ensure_one()
        if self.work_item_id.current_phase != "planning":
            raise UserError("Plan submission requires the Work Item Planning phase.")
        if self.status != "draft" or not self._is_complete():
            raise UserError("Only a complete Draft plan can be submitted.")
        self._refresh_hash()
        super(DevWorkPlan, self).write({"status": "awaiting_approval"})
        if self.work_item_id.current_phase == "planning":
            self.work_item_id.transition_lifecycle(
                "awaiting_plan_approval", "Plan revision submitted", artifact=self
            )
        return True

    def action_approve_exact(self, expected_hash=None, comment=None, policy_version="manual"):
        self.ensure_one()
        _require_approver(self.env)
        if self.work_item_id.current_phase != "awaiting_plan_approval":
            raise UserError("Plan approval requires the Work Item approval gate.")
        expected_hash = expected_hash or self.content_hash
        self._refresh_hash()
        if self.status != "awaiting_approval" or expected_hash != self.content_hash:
            raise UserError("Plan approval hash is stale or does not match exactly.")
        approval = self.env["dev.work.approval"].with_context(
            dev_internal_approval=True
        ).sudo().create(
            {
                "work_item_id": self.work_item_id.id,
                "plan_id": self.id,
                "plan_revision": self.revision,
                "plan_hash": expected_hash,
                "decision": "approved",
                "approver_id": self.env.user.id,
                "decided_at": fields.Datetime.now(),
                "comment": _clean_text(comment, "Approval comment", 2000),
                "policy_version": _clean_text(policy_version, "Policy version", 200),
            }
        )
        old = self.work_item_id.plan_ids.filtered(
            lambda p: p.status == "approved" and p != self
        )
        if old:
            super(DevWorkPlan, old).write({"status": "superseded"})
        super(DevWorkPlan, self).write({"status": "approved"})
        if self.work_item_id.current_phase == "awaiting_plan_approval":
            self.work_item_id.transition_lifecycle(
                "approved", "Exact plan hash approved", artifact=self
            )
        self.work_item_id._refresh_context_revision()
        return approval

    def action_reject(self, comment=None, policy_version="manual"):
        self.ensure_one()
        _require_approver(self.env)
        if self.status != "awaiting_approval":
            raise UserError("Only a submitted plan can be rejected.")
        approval = self.env["dev.work.approval"].with_context(
            dev_internal_approval=True
        ).sudo().create(
            {
                "work_item_id": self.work_item_id.id,
                "plan_id": self.id,
                "plan_revision": self.revision,
                "plan_hash": self.content_hash,
                "decision": "rejected",
                "approver_id": self.env.user.id,
                "decided_at": fields.Datetime.now(),
                "comment": _clean_text(comment, "Approval comment", 2000),
                "policy_version": _clean_text(policy_version, "Policy version", 200),
            }
        )
        super(DevWorkPlan, self).write({"status": "rejected"})
        if self.work_item_id.current_phase == "awaiting_plan_approval":
            self.work_item_id.transition_lifecycle(
                "planning", "Plan rejected; revision required", artifact=self
            )
        return approval

    def action_new_revision(self):
        self.ensure_one()
        work = self.work_item_id
        if work.current_phase in (
            "implementing",
            "paused",
            "blocked",
            "testing",
            "ready_for_review",
            "completed",
            "reported",
            "cancelled",
        ):
            raise UserError(
                "An active or closed execution cannot silently replace its approved plan."
            )
        if self.status == "approved":
            super(DevWorkPlan, self).write({"status": "superseded"})
            if work.current_phase == "approved":
                super(DevWorkItem, work).write({"current_phase": "planning"})
                work._append_lifecycle_event(
                    "approved",
                    "planning",
                    "Approved plan superseded by a new revision",
                    artifact=self,
                )
        elif self.status in ("draft", "rejected"):
            super(DevWorkPlan, self).write({"status": "superseded"})
        elif self.status == "awaiting_approval":
            raise UserError("Reject the submitted plan before creating a new revision.")
        values = self.copy_data()[0]
        values.update(
            parent_revision_id=self.id,
            status="draft",
            content_hash=False,
            revision=0,
            step_ids=[],
            approval_ids=[],
        )
        new_plan = self.create(values)
        for step in self.step_ids.sorted(lambda r: (r.sequence, r.id)):
            step_values = step.copy_data()[0]
            step_values.update(
                plan_id=new_plan.id,
                status="pending",
                started_at=False,
                completed_at=False,
                blocker=False,
                result_summary=False,
            )
            self.env["dev.work.plan.step"].create(step_values)
        new_plan._refresh_hash()
        work._refresh_context_revision()
        return new_plan


class DevWorkPlanStep(models.Model):
    _name = "dev.work.plan.step"
    _description = "Development Work Plan Step"
    _order = "plan_id, sequence, id"

    plan_id = fields.Many2one(
        "dev.work.plan", required=True, ondelete="cascade", index=True
    )
    work_item_id = fields.Many2one(
        "dev.work.item", related="plan_id.work_item_id", store=True, index=True
    )
    step_key = fields.Char(required=True)
    sequence = fields.Integer(default=10, required=True)
    title = fields.Char(required=True)
    description = fields.Text()
    acceptance_evidence = fields.Text()
    dependency_keys = fields.Char()
    dependencies = fields.Char(related="dependency_keys", readonly=False)
    parallel_group = fields.Char()
    status = fields.Selection(
        [
            ("pending", "Pending"),
            ("in_progress", "In Progress"),
            ("done", "Done"),
            ("blocked", "Blocked"),
            ("skipped", "Skipped"),
        ],
        default="pending",
        required=True,
        index=True,
    )
    assignee_type = fields.Selection(
        [("human", "Human"), ("agent", "Agent")], default="human", required=True
    )
    assignee_id = fields.Many2one("res.users", ondelete="restrict")
    run_reference = fields.Char()
    started_at = fields.Datetime(readonly=True)
    completed_at = fields.Datetime(readonly=True)
    blocker = fields.Text()
    result_summary = fields.Text()
    evidence_references = fields.Text()
    # View-support only: lets the standalone step form make the immutable plan
    # structure (title/description/acceptance_evidence/...) read-only once the plan
    # leaves 'draft', mirroring the write() guard so users never hit a surprise
    # AccessError while recording execution evidence on an approved plan.
    plan_status = fields.Selection(
        related="plan_id.status", string="Plan Status", readonly=True
    )

    _step_key_unique = models.Constraint(
        "unique(plan_id, step_key)", "Step key must be unique within a plan revision."
    )

    def action_open_detail(self):
        """Open this step in its full detail form (modal).

        Odoo's ``editable`` one2many list edits rows inline and never opens the
        record's own form on row click, so an explicit action is the cleanest
        Odoo-native way to expose the step's larger description/evidence fields
        without disabling inline quick-edit. View-support only -- no business
        logic runs here.
        """
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.title or "Plan Step",
            "res_model": "dev.work.plan.step",
            "res_id": self.id,
            "view_mode": "form",
            "views": [
                (
                    self.env.ref(
                        "dev_session_hub.dev_work_plan_step_view_form"
                    ).id,
                    "form",
                )
            ],
            "target": "new",
        }

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            _normalize_aliases(vals, {"dependencies": "dependency_keys"})
            plan = self.env["dev.work.plan"].browse(vals.get("plan_id")).exists()
            if plan and plan.status in ("approved", "superseded"):
                raise AccessError("Steps cannot be added to an immutable plan.")
            for name, value in vals.items():
                field = self._fields.get(name)
                if field and field.type in ("char", "text"):
                    _clean_text(value, field.string or name)
        records = super().create(vals_list)
        records.mapped("plan_id")._refresh_hash()
        return records

    def write(self, vals):
        vals = dict(vals)
        _normalize_aliases(vals, {"dependencies": "dependency_keys"})
        structural = {
            "step_key",
            "sequence",
            "title",
            "description",
            "acceptance_evidence",
            "dependency_keys",
            "parallel_group",
        }
        if structural & set(vals) and any(
            record.plan_id.status != "draft" for record in self
        ):
            raise AccessError(
                "Submitted plan structure is immutable; create a new revision."
            )
        if "status" in vals:
            allowed = {
                "pending": {"in_progress", "skipped"},
                "in_progress": {"done", "blocked", "pending"},
                "blocked": {"in_progress", "pending", "skipped"},
                "done": set(),
                "skipped": set(),
            }
            for record in self:
                if vals["status"] not in allowed.get(record.status, set()):
                    raise UserError(
                        "Invalid plan-step transition: %s → %s"
                        % (record.status, vals["status"])
                    )
                if vals["status"] in ("blocked", "skipped") and not (
                    vals.get("blocker") or record.blocker
                ):
                    raise UserError("Blocked or skipped steps require a reason.")
                if vals["status"] == "in_progress" and not record.parallel_group:
                    other = record.plan_id.step_ids.filtered(
                        lambda s: s != record and s.status == "in_progress"
                    )
                    if other:
                        raise UserError("Only one non-parallel plan step may be current.")
            if vals["status"] == "in_progress":
                vals.setdefault("started_at", fields.Datetime.now())
            elif vals["status"] in ("done", "skipped"):
                vals.setdefault("completed_at", fields.Datetime.now())
        for name, value in vals.items():
            field = self._fields.get(name)
            if field and field.type in ("char", "text"):
                _clean_text(value, field.string or name)
        result = super().write(vals)
        if structural & set(vals):
            self.mapped("plan_id")._refresh_hash()
            self.mapped("work_item_id")._invalidate_effective_plan(
                "Material plan step changed"
            )
        return result

    def unlink(self):
        if any(record.plan_id.status in ("approved", "superseded") for record in self):
            raise AccessError("Steps cannot be deleted from an immutable plan.")
        plans = self.mapped("plan_id")
        result = super().unlink()
        plans._refresh_hash()
        return result


class DevWorkApproval(models.Model):
    _name = "dev.work.approval"
    _description = "Immutable Development Work Approval"
    _order = "decided_at desc, id desc"

    work_item_id = fields.Many2one(
        "dev.work.item", required=True, ondelete="restrict", readonly=True, index=True
    )
    plan_id = fields.Many2one(
        "dev.work.plan", required=True, ondelete="restrict", readonly=True, index=True
    )
    plan_revision = fields.Integer(required=True, readonly=True)
    plan_hash = fields.Char(required=True, readonly=True, index=True)
    exact_plan_hash = fields.Char(related="plan_hash", readonly=True)
    decision = fields.Selection(
        [("approved", "Approved"), ("rejected", "Rejected")],
        required=True,
        readonly=True,
    )
    approver_id = fields.Many2one(
        "res.users", required=True, ondelete="restrict", readonly=True
    )
    decided_at = fields.Datetime(required=True, readonly=True, index=True)
    decision_date = fields.Datetime(related="decided_at", readonly=True)
    comment = fields.Text(readonly=True)
    policy_version = fields.Char(required=True, readonly=True)
    policy_revision = fields.Char(related="policy_version", readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("dev_internal_approval"):
            raise AccessError("Approvals may be created only by exact plan actions.")
        for vals in vals_list:
            plan = self.env["dev.work.plan"].browse(vals.get("plan_id")).exists()
            if (
                not plan
                or plan.work_item_id.id != vals.get("work_item_id")
                or plan.revision != vals.get("plan_revision")
                or plan.content_hash != vals.get("plan_hash")
            ):
                raise ValidationError("Approval must match the exact plan revision and hash.")
        return super().create(vals_list)

    def write(self, vals):
        raise AccessError("Approvals are immutable.")

    def unlink(self):
        raise AccessError("Approvals are immutable.")


class DevWorkCheckpoint(models.Model):
    _name = "dev.work.checkpoint"
    _description = "Immutable Development Work Checkpoint"
    _order = "captured_at desc, id desc"

    work_item_id = fields.Many2one(
        "dev.work.item", required=True, ondelete="restrict", readonly=True, index=True
    )
    session_id = fields.Many2one(
        "dev.session", ondelete="restrict", readonly=True, index=True
    )
    execution_workspace_id = fields.Many2one(
        "dev.execution.workspace", ondelete="restrict", readonly=True, index=True
    )
    supersedes_id = fields.Many2one(
        "dev.work.checkpoint", ondelete="restrict", readonly=True
    )
    trigger = fields.Selection(
        [
            ("pause", "Pause"),
            ("milestone", "Milestone"),
            ("client_review", "Client Review"),
            ("machine_switch", "Machine Switch"),
            ("agent_handoff", "Agent Handoff"),
            ("manual", "Manual"),
        ],
        required=True,
        readonly=True,
    )
    captured_at = fields.Datetime(
        required=True, default=fields.Datetime.now, readonly=True, index=True
    )
    timestamp = fields.Datetime(related="captured_at", readonly=True)
    actor_id = fields.Many2one(
        "res.users",
        required=True,
        default=lambda self: self.env.user,
        ondelete="restrict",
        readonly=True,
    )
    lifecycle_phase = fields.Selection(
        LIFECYCLE_SELECTION, required=True, readonly=True
    )
    approved_plan_id = fields.Many2one(
        "dev.work.plan", ondelete="restrict", readonly=True
    )
    last_completed_step_id = fields.Many2one(
        "dev.work.plan.step", ondelete="restrict", readonly=True
    )
    current_step_id = fields.Many2one(
        "dev.work.plan.step", ondelete="restrict", readonly=True
    )
    current_plan_step_id = fields.Many2one(
        "dev.work.plan.step", related="current_step_id", readonly=True
    )
    next_recommended_step = fields.Text(required=True, readonly=True)
    remaining_step_keys = fields.Char(readonly=True)
    remaining_step_references = fields.Char(
        related="remaining_step_keys", readonly=True
    )
    blockers = fields.Text(readonly=True)
    decisions_made = fields.Text(readonly=True)
    pending_decisions = fields.Text(readonly=True)
    last_agent_note = fields.Text(readonly=True)
    repository_id = fields.Many2one("dev.repository", ondelete="restrict", readonly=True)
    working_directory = fields.Char(readonly=True)
    branch = fields.Char(readonly=True)
    git_head = fields.Char(readonly=True)
    full_head = fields.Char(related="git_head", readonly=True)
    base_head = fields.Char(readonly=True)
    dirty_summary = fields.Char(readonly=True)
    dirty_digest = fields.Char(readonly=True)
    ahead_count = fields.Integer(readonly=True)
    behind_count = fields.Integer(readonly=True)
    files_touched_summary = fields.Text(readonly=True)
    tests_run = fields.Integer(readonly=True)
    tests_passed = fields.Integer(readonly=True)
    tests_failed = fields.Integer(readonly=True)
    tests_skipped = fields.Integer(readonly=True)
    test_commands_summary = fields.Text(readonly=True)
    sanitized_test_commands = fields.Text(
        related="test_commands_summary", readonly=True
    )
    test_duration_seconds = fields.Float(readonly=True)
    duration_seconds = fields.Float(
        related="test_duration_seconds", readonly=True
    )
    test_evidence_references = fields.Text(readonly=True)
    evidence_references = fields.Text(
        related="test_evidence_references", readonly=True
    )
    environment_id = fields.Many2one(
        "dev.environment", ondelete="restrict", readonly=True
    )
    machine_id = fields.Many2one("dev.machine", ondelete="restrict", readonly=True)
    client_id = fields.Many2one("dev.client", ondelete="restrict", readonly=True)
    manifest_revision = fields.Char(readonly=True)
    op_work_package_id = fields.Integer(readonly=True)
    op_work_package_reference = fields.Char(
        compute="_compute_reference_labels"
    )
    odoo_task_id = fields.Many2one("project.task", ondelete="restrict", readonly=True)
    odoo_task_reference = fields.Char(compute="_compute_reference_labels")
    cursor_thread_reference = fields.Char(readonly=True)
    cursor_thread_id = fields.Char(related="cursor_thread_reference", readonly=True)
    cursor_run_reference = fields.Char(readonly=True)
    run_reference = fields.Char(related="cursor_run_reference", readonly=True)
    snapshot_hash = fields.Char(required=True, readonly=True, copy=False, index=True)
    schema_version = fields.Char(
        default="dev-work-checkpoint.v1", required=True, readonly=True
    )

    @api.depends("op_work_package_id", "odoo_task_id")
    def _compute_reference_labels(self):
        for record in self:
            record.op_work_package_reference = (
                "#%s" % record.op_work_package_id
                if record.op_work_package_id
                else False
            )
            record.odoo_task_reference = (
                record.odoo_task_id.display_name if record.odoo_task_id else False
            )

    def _snapshot_values(self, values=None):
        self.ensure_one()
        values = values or {}
        names = (
            "trigger",
            "lifecycle_phase",
            "next_recommended_step",
            "remaining_step_keys",
            "blockers",
            "decisions_made",
            "pending_decisions",
            "last_agent_note",
            "working_directory",
            "branch",
            "git_head",
            "base_head",
            "dirty_summary",
            "dirty_digest",
            "ahead_count",
            "behind_count",
            "files_touched_summary",
            "tests_run",
            "tests_passed",
            "tests_failed",
            "tests_skipped",
            "test_commands_summary",
            "test_duration_seconds",
            "test_evidence_references",
            "manifest_revision",
            "op_work_package_id",
            "cursor_thread_reference",
            "cursor_run_reference",
            "schema_version",
        )
        payload = {name: values.get(name, self[name]) or "" for name in names}
        payload.update(
            work_item_id=self.work_item_id.id,
            session_id=self.session_id.id or None,
            approved_plan_id=self.approved_plan_id.id or None,
            execution_workspace_id=self.execution_workspace_id.id or None,
            current_step_id=self.current_step_id.id or None,
        )
        return payload

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            work = self.env["dev.work.item"].browse(vals.get("work_item_id")).exists()
            if not work:
                raise ValidationError("Checkpoint requires a work item.")
            vals.setdefault("lifecycle_phase", work.current_phase)
            vals.setdefault("approved_plan_id", work.approved_plan_id.id)
            vals.setdefault("op_work_package_id", work.op_work_package_id)
            vals.setdefault("odoo_task_id", work.odoo_task_id.id)
            session = self.env["dev.session"].browse(vals.get("session_id")).exists()
            if session:
                if session.work_item_id != work:
                    raise ValidationError("Checkpoint session must belong to the work item.")
                vals.setdefault("repository_id", session.repository_id.id)
                vals.setdefault(
                    "execution_workspace_id", session.execution_workspace_id.id
                )
                vals.setdefault("working_directory", session.working_directory)
                vals.setdefault("branch", session.git_branch_snapshot)
                vals.setdefault("git_head", session.git_head_snapshot)
                vals.setdefault("dirty_summary", session.dirty_state_summary)
                vals.setdefault("environment_id", session.environment_id.id)
                vals.setdefault("machine_id", session.machine_id.id)
                vals.setdefault("client_id", session.client_id.id)
                vals.setdefault("manifest_revision", session.manifest_revision)
                vals.setdefault(
                    "cursor_thread_reference", session.cursor_agent_thread_id
                )
            for name, value in vals.items():
                field = self._fields.get(name)
                if field and field.type in ("char", "text"):
                    _clean_text(value, field.string or name, 4000)
            vals.setdefault("snapshot_hash", "pending")
        records = super().create(vals_list)
        for record in records:
            super(DevWorkCheckpoint, record).write(
                {"snapshot_hash": _canonical_hash(record._snapshot_values())}
            )
            record.work_item_id._refresh_context_revision()
        return records

    def write(self, vals):
        raise AccessError("Checkpoints are immutable; create a superseding checkpoint.")

    def unlink(self):
        raise AccessError("Checkpoints are immutable.")

    def action_new_revision(self):
        self.ensure_one()
        values = self.copy_data()[0]
        values.update(
            supersedes_id=self.id,
            captured_at=fields.Datetime.now(),
            actor_id=self.env.user.id,
            snapshot_hash="pending",
        )
        return self.create(values)


class DevCompletionReport(models.Model):
    _name = "dev.completion.report"
    _description = "Versioned Development Completion Report"
    _order = "work_item_id, revision desc"

    work_item_id = fields.Many2one(
        "dev.work.item", required=True, ondelete="cascade", index=True
    )
    revision = fields.Integer(required=True, readonly=True, copy=False)
    parent_revision_id = fields.Many2one(
        "dev.completion.report", ondelete="restrict", readonly=True, copy=False
    )
    content_hash = fields.Char(required=True, readonly=True, copy=False, index=True)
    status = fields.Selection(
        [
            ("draft", "Draft"),
            ("ready_review", "Ready for Review"),
            ("approved", "Approved"),
            ("superseded", "Superseded"),
        ],
        default="draft",
        required=True,
        index=True,
    )
    original_request_summary = fields.Text(required=True)
    original_request = fields.Text(
        related="original_request_summary", readonly=False
    )
    source_message_ids = fields.Many2many(
        "dev.work.source.message",
        related="work_item_id.source_message_ids",
        readonly=True,
    )
    implemented_summary = fields.Text(required=True)
    plan_id = fields.Many2one("dev.work.plan", required=True, ondelete="restrict")
    completed_steps_summary = fields.Text(required=True)
    completed_steps = fields.Text(
        related="completed_steps_summary", readonly=False
    )
    skipped_steps_summary = fields.Text()
    skipped_steps = fields.Text(related="skipped_steps_summary", readonly=False)
    changed_components_summary = fields.Text(required=True)
    modules_files_changed = fields.Text(
        related="changed_components_summary", readonly=False
    )
    repository_reference = fields.Char(required=True)
    repository_id = fields.Many2one(
        "dev.repository", related="plan_id.work_item_id.preferred_repository_id"
    )
    branch = fields.Char(required=True)
    commit_references = fields.Text()
    pull_request_references = fields.Text()
    commit_pr_references = fields.Text(
        compute="_compute_commit_pr_references",
        inverse="_inverse_commit_pr_references",
    )
    tests_summary = fields.Text(required=True)
    tests_and_results = fields.Text(related="tests_summary", readonly=False)
    uat_status = fields.Selection(
        [
            ("not_applicable", "Not Applicable"),
            ("not_run", "Not Run"),
            ("pending", "Pending"),
            ("passed", "Passed"),
            ("failed", "Failed"),
        ],
        default="not_run",
        required=True,
    )
    uat_evidence_references = fields.Text()
    uat_result = fields.Selection(
        related="uat_status", readonly=False, string="UAT Result (Compatibility)"
    )
    evidence_references = fields.Text(
        related="uat_evidence_references", readonly=False
    )
    known_limitations = fields.Text(required=True)
    rollback_notes = fields.Text(required=True)
    rollback_deployment_notes = fields.Text(
        related="rollback_notes", readonly=False
    )
    deployment_status = fields.Selection(
        [
            ("not_deployed", "Not Deployed"),
            ("test", "Test"),
            ("staging", "Staging"),
            ("production", "Production"),
        ],
        default="not_deployed",
        required=True,
    )
    production_status = fields.Selection(
        [
            ("not_applicable", "Not Applicable"),
            ("not_verified", "Not Verified"),
            ("verified", "Verified"),
            ("failed", "Failed"),
        ],
        default="not_verified",
        required=True,
    )
    test_deployment_status = fields.Selection(
        related="deployment_status",
        readonly=False,
        string="Test Deployment Status (Compatibility)",
    )
    status_evidence_references = fields.Text()
    follow_up_items = fields.Text()
    generated_by = fields.Selection(
        [("human", "Human"), ("automation", "Automation"), ("agent", "Agent")],
        default="human",
        required=True,
    )
    run_reference = fields.Char()
    reviewer_id = fields.Many2one("res.users", ondelete="restrict", readonly=True)
    approved_at = fields.Datetime(readonly=True)
    approval_date = fields.Datetime(related="approved_at", readonly=True)
    schema_version = fields.Char(default="dev-completion-report.v1", required=True)

    _revision_unique = models.Constraint(
        "unique(work_item_id, revision)", "Report revision must be unique per work item."
    )

    @api.depends("commit_references", "pull_request_references")
    def _compute_commit_pr_references(self):
        for record in self:
            parts = [
                value
                for value in (
                    record.commit_references,
                    record.pull_request_references,
                )
                if value
            ]
            record.commit_pr_references = "\n".join(parts)

    def _inverse_commit_pr_references(self):
        for record in self:
            record.commit_references = record.commit_pr_references
            record.pull_request_references = False

    def _hash_values(self, values=None):
        self.ensure_one()
        values = values or {}
        names = (
            "original_request_summary",
            "implemented_summary",
            "completed_steps_summary",
            "skipped_steps_summary",
            "changed_components_summary",
            "repository_reference",
            "branch",
            "commit_references",
            "pull_request_references",
            "tests_summary",
            "uat_status",
            "uat_evidence_references",
            "known_limitations",
            "rollback_notes",
            "deployment_status",
            "production_status",
            "status_evidence_references",
            "follow_up_items",
            "schema_version",
        )
        payload = {name: values.get(name, self[name]) or "" for name in names}
        payload["plan_hash"] = self.plan_id.content_hash
        return _canonical_hash(payload)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            _normalize_aliases(
                vals,
                {
                    "original_request": "original_request_summary",
                    "completed_steps": "completed_steps_summary",
                    "skipped_steps": "skipped_steps_summary",
                    "modules_files_changed": "changed_components_summary",
                    "tests_and_results": "tests_summary",
                    "uat_result": "uat_status",
                    "evidence_references": "uat_evidence_references",
                    "rollback_deployment_notes": "rollback_notes",
                    "test_deployment_status": "deployment_status",
                },
            )
            if "commit_pr_references" in vals:
                vals.setdefault("commit_references", vals.pop("commit_pr_references"))
            work = self.env["dev.work.item"].browse(vals.get("work_item_id")).exists()
            plan = self.env["dev.work.plan"].browse(vals.get("plan_id")).exists()
            if not work or not plan or plan.work_item_id != work:
                raise ValidationError("Report plan must belong to its work item.")
            if plan.status != "approved":
                raise ValidationError("Completion report requires an approved plan.")
            if not vals.get("repository_reference") and work.preferred_repository_id:
                vals["repository_reference"] = (
                    work.preferred_repository_id.git_remote
                    or work.preferred_repository_id.name
                )
            latest = self.search(
                [("work_item_id", "=", work.id)], order="revision desc", limit=1
            )
            vals["revision"] = latest.revision + 1 if latest else 1
            vals["content_hash"] = "pending"
            if vals.get("status") == "approved":
                raise ValidationError("Use the explicit report approval action.")
            for name, value in vals.items():
                field = self._fields.get(name)
                if field and field.type in ("char", "text"):
                    _clean_text(value, field.string or name)
        records = super().create(vals_list)
        for record in records:
            super(DevCompletionReport, record).write(
                {"content_hash": record._hash_values()}
            )
        return records

    def write(self, vals):
        vals = dict(vals)
        _normalize_aliases(
            vals,
            {
                "original_request": "original_request_summary",
                "completed_steps": "completed_steps_summary",
                "skipped_steps": "skipped_steps_summary",
                "modules_files_changed": "changed_components_summary",
                "tests_and_results": "tests_summary",
                "uat_result": "uat_status",
                "evidence_references": "uat_evidence_references",
                "rollback_deployment_notes": "rollback_notes",
                "test_deployment_status": "deployment_status",
            },
        )
        if "commit_pr_references" in vals:
            vals.setdefault("commit_references", vals.pop("commit_pr_references"))
        if any(record.status in ("approved", "superseded") for record in self):
            raise AccessError("Approved and superseded reports are immutable.")
        if {
            "revision",
            "parent_revision_id",
            "content_hash",
            "work_item_id",
            "reviewer_id",
            "approved_at",
        } & set(vals):
            raise AccessError("Protected report fields are immutable.")
        if vals.get("status") == "approved":
            raise AccessError("Use the explicit report approval action.")
        for name, value in vals.items():
            field = self._fields.get(name)
            if field and field.type in ("char", "text"):
                _clean_text(value, field.string or name)
        result = super().write(vals)
        for record in self:
            super(DevCompletionReport, record).write(
                {"content_hash": record._hash_values()}
            )
        return result

    def action_ready_review(self):
        self.ensure_one()
        if self.status != "draft":
            raise UserError("Only a Draft report can be submitted.")
        super(DevCompletionReport, self).write({"status": "ready_review"})
        return True

    def action_approve(self):
        self.ensure_one()
        _require_approver(self.env)
        if self.work_item_id.current_phase != "ready_for_review":
            raise UserError("Report approval requires the Ready for Review phase.")
        if self.status != "ready_review":
            raise UserError("Only a report ready for review can be approved.")
        if self.uat_status not in ("not_applicable", "passed"):
            raise UserError("Report approval requires passed or not-applicable UAT.")
        if not self.repository_reference or not self.branch:
            raise UserError("Report approval requires repository and Git branch references.")
        old = self.work_item_id.completion_report_ids.filtered(
            lambda r: r.status == "approved" and r != self
        )
        if old:
            super(DevCompletionReport, old).write({"status": "superseded"})
        super(DevCompletionReport, self).write(
            {
                "status": "approved",
                "reviewer_id": self.env.user.id,
                "approved_at": fields.Datetime.now(),
            }
        )
        self.work_item_id._refresh_context_revision()
        return True

    def action_new_revision(self):
        self.ensure_one()
        values = self.copy_data()[0]
        values.update(
            parent_revision_id=self.id,
            status="draft",
            content_hash=False,
            revision=0,
            reviewer_id=False,
            approved_at=False,
        )
        return self.create(values)


class DevWorkCommunication(models.Model):
    _name = "dev.work.communication"
    _description = "Reviewed Development Work Communication"
    _order = "write_date desc, id desc"

    work_item_id = fields.Many2one(
        "dev.work.item", required=True, ondelete="cascade", index=True
    )
    completion_report_id = fields.Many2one(
        "dev.completion.report", ondelete="restrict"
    )
    source_message_id = fields.Many2one(
        "dev.work.source.message", ondelete="restrict"
    )
    communication_type = fields.Selection(
        [("completion", "Completion"), ("progress", "Progress"), ("blocker", "Blocker")],
        required=True,
        default="completion",
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("in_review", "In Review"),
            ("approved", "Approved"),
            ("queued", "Queued"),
        ],
        default="draft",
        required=True,
        readonly=True,
        index=True,
    )
    review_status = fields.Selection(related="state", readonly=True)
    language_code = fields.Char(default="ar")
    language = fields.Char(related="language_code", readonly=False)
    body = fields.Text(required=True)
    draft_message = fields.Text(related="body", readonly=False)
    chatwoot_account_id = fields.Integer()
    chatwoot_inbox_id = fields.Integer()
    chatwoot_conversation_id = fields.Integer(index=True)
    reply_to_chatwoot_message_id = fields.Integer()
    destination_type = fields.Selection(
        [("group_jid", "WhatsApp Group"), ("individual_jid", "WhatsApp Individual")],
        required=True,
        default="group_jid",
    )
    destination_reference = fields.Char()
    group_jid = fields.Char(related="destination_reference", readonly=False)
    reviewed_by = fields.Many2one("res.users", ondelete="restrict", readonly=True)
    reviewed_by_id = fields.Many2one(
        "res.users", related="reviewed_by", readonly=True
    )
    reviewed_at = fields.Datetime(readonly=True)
    review_hash = fields.Char(readonly=True, copy=False, index=True)
    approved_by = fields.Many2one("res.users", ondelete="restrict", readonly=True)
    approved_at = fields.Datetime(readonly=True)
    approved_hash = fields.Char(readonly=True, copy=False, index=True)
    send_approved = fields.Boolean(readonly=True)
    queued_at = fields.Datetime(readonly=True)
    idempotency_key = fields.Char(readonly=True, copy=False, index=True)
    chatwoot_message_id = fields.Integer(readonly=True, copy=False)
    chatwoot_outbound_message_id = fields.Integer(
        related="chatwoot_message_id", readonly=True
    )
    evolution_message_id = fields.Char(readonly=True, copy=False)
    evolution_provider_message_id = fields.Char(
        related="evolution_message_id", readonly=True
    )
    delivery_summary = fields.Char(readonly=True, copy=False)
    delivery_status = fields.Selection(
        [
            ("not_queued", "Not Queued"),
            ("queued", "Queued"),
            (
                "delivery_pending_confirmation",
                "Delivery Pending Confirmation",
            ),
            ("handed_off", "Handed Off"),
            ("delivered", "Delivered"),
            ("failed", "Failed"),
            ("dead_letter", "Dead Letter"),
        ],
        default="not_queued",
        required=True,
        readonly=True,
    )
    error_state = fields.Char(readonly=True)

    _idempotency_unique = models.UniqueIndex(
        "(idempotency_key) WHERE idempotency_key IS NOT NULL",
        "Communication idempotency key must be unique.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            _normalize_aliases(
                vals,
                {
                    "language": "language_code",
                    "draft_message": "body",
                    "group_jid": "destination_reference",
                },
            )
            report = self.env["dev.completion.report"].browse(
                vals.get("completion_report_id")
            ).exists()
            work = self.env["dev.work.item"].browse(vals.get("work_item_id")).exists()
            if report and report.work_item_id != work:
                raise ValidationError("Communication report must belong to the work item.")
            source = self.env["dev.work.source.message"].browse(
                vals.get("source_message_id")
            ).exists()
            if source and work not in source.work_item_ids:
                raise ValidationError("Source message must belong to the work item.")
            _validate_text_values(self, vals, 4000)
            _clean_text(vals.get("body"), "Communication body", 4000)
            _clean_text(
                vals.get("destination_reference"), "Destination reference", 300
            )
            if vals.get("state", "draft") != "draft":
                raise ValidationError("Communications must be created as Draft.")
        return super().create(vals_list)

    def write(self, vals):
        vals = dict(vals)
        _normalize_aliases(
            vals,
            {
                "language": "language_code",
                "draft_message": "body",
                "group_jid": "destination_reference",
            },
        )
        protected = {
            "state",
            "reviewed_by",
            "reviewed_at",
            "review_hash",
            "approved_by",
            "approved_at",
            "approved_hash",
            "queued_at",
            "idempotency_key",
            "chatwoot_message_id",
            "evolution_message_id",
            "delivery_summary",
            "delivery_status",
            "error_state",
            "send_approved",
        }
        if protected & set(vals):
            raise AccessError("Communication audit fields change only through actions.")
        if any(record.state != "draft" for record in self) and {
            "body",
            "destination_type",
            "destination_reference",
            "chatwoot_account_id",
            "chatwoot_inbox_id",
            "chatwoot_conversation_id",
            "reply_to_chatwoot_message_id",
        } & set(vals):
            raise AccessError(
                "Communication content and destination are immutable after review starts."
            )
        _validate_text_values(self, vals, 4000)
        _clean_text(vals.get("body"), "Communication body", 4000)
        return super().write(vals)

    def _message_destination_hash(self):
        self.ensure_one()
        return _canonical_hash(
            {
                "body": self.body or "",
                "language": self.language_code or "",
                "account_id": self.chatwoot_account_id or None,
                "inbox_id": self.chatwoot_inbox_id or None,
                "conversation_id": self.chatwoot_conversation_id or None,
                "reply_to_message_id": self.reply_to_chatwoot_message_id or None,
                "destination_type": self.destination_type,
                "destination_reference": self.destination_reference or "",
                "source_message_id": self.source_message_id.id or None,
            }
        )

    def _integration_update(self, values):
        """Private audited write path used only by guarded service callbacks."""
        return super(DevWorkCommunication, self).write(values)

    def action_review(self):
        self.ensure_one()
        if self.state != "draft":
            raise UserError("Only a Draft communication can be reviewed.")
        if self.communication_type == "completion":
            if self.work_item_id.current_phase != "completed":
                raise UserError(
                    "Completion communication review requires completed lifecycle work."
                )
            if (
                not self.completion_report_id
                or self.completion_report_id.status != "approved"
            ):
                raise UserError(
                    "A completion communication requires an approved completion report."
                )
            if not self.source_message_id:
                raise UserError(
                    "Select the original source message before reviewing completion."
                )
            source = self.source_message_id
            expected = (
                source.chatwoot_account_id,
                source.chatwoot_inbox_id,
                source.chatwoot_conversation_id,
            )
            actual = (
                self.chatwoot_account_id,
                self.chatwoot_inbox_id,
                self.chatwoot_conversation_id,
            )
            if not all(expected) or actual != expected:
                raise UserError(
                    "The Chatwoot account, inbox, and conversation must exactly "
                    "match the original source message."
                )
            if source.group_jid and (
                self.destination_type != "group_jid"
                or self.destination_reference != source.group_jid
            ):
                raise UserError(
                    "The WhatsApp group destination must match the original source."
                )
        review_hash = self._message_destination_hash()
        super(DevWorkCommunication, self).write(
            {
                "state": "in_review",
                "reviewed_by": self.env.user.id,
                "reviewed_at": fields.Datetime.now(),
                "review_hash": review_hash,
            }
        )
        return True

    def action_submit_review(self):
        return self.action_review()

    def action_approve(self):
        self.ensure_one()
        _require_approver(self.env)
        if self.state != "in_review":
            raise UserError("Only a reviewed communication can be approved.")
        current_hash = self._message_destination_hash()
        if not self.review_hash or self.review_hash != current_hash:
            raise UserError("Communication changed after review; start review again.")
        super(DevWorkCommunication, self).write(
            {
                "state": "approved",
                "approved_by": self.env.user.id,
                "approved_at": fields.Datetime.now(),
                "send_approved": True,
                "approved_hash": current_hash,
            }
        )
        return True

    def action_queue(self):
        self.ensure_one()
        self.env.cr.execute(
            "SELECT id FROM dev_work_communication WHERE id = %s FOR UPDATE", [self.id]
        )
        self.invalidate_recordset()
        if self.state == "queued" and self.idempotency_key:
            existing = self.env["dev.external.outbox"].sudo().search(
                [("idempotency_key", "=", self.idempotency_key)], limit=1
            )
            if existing:
                return existing
        if self.state != "approved":
            raise UserError("Only an approved communication can be queued.")
        if (
            not self.approved_hash
            or self.approved_hash != self._message_destination_hash()
        ):
            raise UserError("Approved communication hash no longer matches.")
        if not (
            self.chatwoot_account_id
            and self.chatwoot_inbox_id
            and self.chatwoot_conversation_id
            and self.destination_reference
        ):
            raise UserError(
                "Chatwoot account, inbox, conversation, and destination are required."
            )
        payload = {
            "schema": "dev-hub.chatwoot-public-message.v1",
            "account_id": self.chatwoot_account_id,
            "inbox_id": self.chatwoot_inbox_id,
            "conversation_id": self.chatwoot_conversation_id,
            "reply_to_message_id": self.reply_to_chatwoot_message_id or None,
            "destination_type": self.destination_type,
            "destination_reference": self.destination_reference,
            "body": self.body,
            "communication_id": self.id,
            "idempotency_key": self.approved_hash,
        }
        key = "chatwoot:%s:%s:%s" % (
            self.chatwoot_account_id,
            self.chatwoot_conversation_id,
            _canonical_hash(payload)[:24],
        )
        outbox = self.work_item_id._queue_outbox(
            "chatwoot", "public_message", payload, key, communication=self
        )
        super(DevWorkCommunication, self).write(
            {
                "state": "queued",
                "queued_at": fields.Datetime.now(),
                "idempotency_key": key,
                "delivery_status": "queued",
            }
        )
        return outbox

    def record_delivery_references(
        self, chatwoot_message_id=None, evolution_message_id=None, summary=None
    ):
        self.ensure_one()
        if not self.env.is_superuser() and not self.env.user.has_group(
            "dev_session_hub.group_dev_hub_integration"
        ):
            raise AccessError("Only the guarded integration callback may record delivery.")
        if self.state != "queued":
            raise UserError("Delivery references require a queued communication.")
        super(DevWorkCommunication, self).write(
            {
                "chatwoot_message_id": chatwoot_message_id or False,
                "evolution_message_id": _clean_text(
                    evolution_message_id, "Evolution message ID", 300
                ),
                "delivery_summary": _clean_text(summary, "Delivery summary", 500),
                "delivery_status": (
                    "handed_off"
                    if chatwoot_message_id or evolution_message_id
                    else "queued"
                ),
            }
        )
        return True


class DevExternalOutbox(models.Model):
    _name = "dev.external.outbox"
    _description = "Sanitized Development External Outbox"
    _order = "next_attempt_at, id"

    work_item_id = fields.Many2one(
        "dev.work.item", required=True, ondelete="restrict", index=True
    )
    channel = fields.Selection(
        [("openproject", "OpenProject"), ("chatwoot", "Chatwoot")],
        required=True,
        index=True,
    )
    destination = fields.Selection(related="channel", readonly=True, store=True)
    operation = fields.Selection(
        [("milestone", "Milestone"), ("public_message", "Public Message")],
        required=True,
        index=True,
    )
    payload_json = fields.Text(required=True, readonly=True)
    payload_hash = fields.Char(required=True, readonly=True, index=True)
    idempotency_key = fields.Char(required=True, readonly=True, copy=False, index=True)
    state = fields.Selection(
        [
            ("pending", "Pending"),
            ("retry", "Retry"),
            ("dead_letter", "Dead Letter"),
            ("done", "Done"),
        ],
        default="pending",
        required=True,
        readonly=True,
        index=True,
    )
    attempt_count = fields.Integer(default=0, readonly=True)
    next_attempt_at = fields.Datetime(
        default=fields.Datetime.now, required=True, readonly=True, index=True
    )
    last_attempt_at = fields.Datetime(readonly=True)
    completed_at = fields.Datetime(readonly=True)
    last_error_code = fields.Char(readonly=True)
    last_error_summary = fields.Char(readonly=True)
    last_error = fields.Char(related="last_error_summary", readonly=True)
    external_reference = fields.Char(readonly=True)
    created_by = fields.Many2one(
        "res.users",
        required=True,
        default=lambda self: self.env.user,
        ondelete="restrict",
        readonly=True,
    )

    _idempotency_unique = models.Constraint(
        "unique(idempotency_key)", "Outbox idempotency key must be unique."
    )

    @api.model
    def _validate_intent_payload(self, channel, operation, payload):
        if (channel, operation) == ("chatwoot", "public_message"):
            allowed = {
                "schema",
                "account_id",
                "inbox_id",
                "conversation_id",
                "reply_to_message_id",
                "destination_type",
                "destination_reference",
                "body",
                "communication_id",
                "idempotency_key",
            }
            if set(payload) != allowed:
                raise ValidationError("Chatwoot outbox payload fields do not match v1.")
            if payload.get("schema") != "dev-hub.chatwoot-public-message.v1":
                raise ValidationError("Unsupported Chatwoot outbox schema.")
            for name in ("account_id", "inbox_id", "conversation_id", "communication_id"):
                value = payload.get(name)
                if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                    raise ValidationError("%s must be a positive integer." % name)
            reply_id = payload.get("reply_to_message_id")
            if reply_id is not None and (
                isinstance(reply_id, bool)
                or not isinstance(reply_id, int)
                or reply_id <= 0
            ):
                raise ValidationError("reply_to_message_id must be a positive integer.")
            if payload.get("destination_type") not in ("group_jid", "conversation"):
                raise ValidationError("Unsupported Chatwoot destination type.")
            _clean_text(payload.get("destination_reference"), "Destination", 300)
            _clean_text(payload.get("body"), "Communication body", 4000)
            _clean_text(payload.get("idempotency_key"), "Payload idempotency key", 300)
            return
        if (channel, operation) == ("openproject", "milestone"):
            required = {
                "schema",
                "backend_id",
                "work_package_id",
                "milestone",
                "summary",
            }
            optional = {"status_hint", "dev_hub_link"}
            if not required.issubset(payload) or set(payload) - required - optional:
                raise ValidationError("OpenProject milestone payload fields do not match v1.")
            if payload.get("schema") != "dev-hub.op-milestone.v1":
                raise ValidationError("Unsupported OpenProject outbox schema.")
            for name in ("backend_id", "work_package_id"):
                value = payload.get(name)
                if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                    raise ValidationError("%s must be a positive integer." % name)
            if payload.get("milestone") not in (
                "analysis_plan_ready",
                "material_blocker",
                "completion",
            ):
                raise ValidationError("Unsupported OpenProject milestone.")
            if payload.get("status_hint") not in (
                None,
                "new",
                "in_progress",
                "on_hold",
                "in_review",
                "closed",
            ):
                raise ValidationError("Unsupported OpenProject status hint.")
            _clean_text(payload.get("summary"), "OpenProject milestone summary", 2000)
            if payload.get("dev_hub_link"):
                _clean_text(payload["dev_hub_link"], "Dev Hub link", 500)
            return
        raise ValidationError("Unsupported external outbox action.")

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("dev_internal_outbox"):
            raise AccessError("External intents may be created only by guarded actions.")
        for vals in vals_list:
            if vals.get("state", "pending") != "pending":
                raise ValidationError("Outbox records must be created Pending.")
            payload = json.loads(_validated_json(vals.get("payload_json")))
            self._validate_intent_payload(
                vals.get("channel"), vals.get("operation"), payload
            )
            payload_json = _validated_json(payload)
            vals["payload_json"] = payload_json
            vals["payload_hash"] = hashlib.sha256(
                payload_json.encode("utf-8")
            ).hexdigest()
            _clean_text(vals.get("idempotency_key"), "Idempotency key", 300)
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.context.get("dev_outbox_action"):
            raise AccessError("Outbox records change only through status callbacks.")
        if {"payload_json", "payload_hash", "idempotency_key", "channel", "operation"} & set(
            vals
        ):
            raise AccessError("Outbox intent and idempotency are immutable.")
        return super().write(vals)

    def unlink(self):
        raise AccessError("Outbox audit records cannot be deleted.")

    def mark_retry(self, error_code, error_summary, next_attempt_at):
        self.ensure_one()
        if self.state not in ("pending", "retry"):
            raise UserError("Only pending or retry outbox records can retry.")
        self.with_context(dev_outbox_action=True).write(
            {
                "state": "retry",
                "attempt_count": self.attempt_count + 1,
                "last_attempt_at": fields.Datetime.now(),
                "next_attempt_at": next_attempt_at,
                "last_error_code": _clean_text(error_code, "Error code", 100),
                "last_error_summary": _clean_text(
                    error_summary, "Error summary", 1000
                ),
            }
        )
        return True

    def mark_dead_letter(self, error_code, error_summary):
        self.ensure_one()
        if self.state not in ("pending", "retry"):
            raise UserError("Only active outbox records can become dead letters.")
        self.with_context(dev_outbox_action=True).write(
            {
                "state": "dead_letter",
                "attempt_count": self.attempt_count + 1,
                "last_attempt_at": fields.Datetime.now(),
                "last_error_code": _clean_text(error_code, "Error code", 100),
                "last_error_summary": _clean_text(
                    error_summary, "Error summary", 1000
                ),
            }
        )
        return True

    def mark_done(self, external_reference=None):
        self.ensure_one()
        if self.state not in ("pending", "retry"):
            raise UserError("Only pending or retry outbox records can complete.")
        self.with_context(dev_outbox_action=True).write(
            {
                "state": "done",
                "attempt_count": self.attempt_count + 1,
                "last_attempt_at": fields.Datetime.now(),
                "completed_at": fields.Datetime.now(),
                "external_reference": _clean_text(
                    external_reference, "External reference", 500
                ),
                "last_error_code": False,
                "last_error_summary": False,
            }
        )
        return True
