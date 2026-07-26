# -*- coding: utf-8 -*-
from __future__ import annotations

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from odoo.addons.devhub_work.models.dev_work_utils import (
    MAX_TEXT,
    SECRET_PATTERN,
    FORBIDDEN_CONTENT,
    FORBIDDEN_JSON_KEYS,
    LIFECYCLE_SELECTION,
    LIFECYCLE_TRANSITIONS,
    _uuid,
    _canonical_hash,
    _clean_text,
    _clean_note_text,
    _bounded,
    _neutralize_forbidden,
    _context_text,
    _validate_text_values,
    _normalize_aliases,
    _validate_json_value,
    _validated_json,
    _require_approver,
    _require_importer,
)

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



