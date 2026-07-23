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



