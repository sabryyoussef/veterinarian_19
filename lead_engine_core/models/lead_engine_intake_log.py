# -*- coding: utf-8 -*-

import uuid

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_TERMINAL_STATUSES = ("success", "error", "rejected")
_IMMUTABLE_FIELDS = {
    "source_id",
    "payload_raw",
    "normalized_payload",
    "received_at",
    "request_uuid",
}


class LeadEngineIntakeLog(models.Model):
    _name = "lead.engine.intake.log"
    _description = "Lead Engine Intake Log"
    _order = "received_at desc, id desc"

    source_id = fields.Many2one(
        comodel_name="lead.engine.source",
        required=True,
        ondelete="restrict",
        index=True,
    )
    company_id = fields.Many2one(
        related="source_id.company_id",
        store=True,
        readonly=True,
        index=True,
    )
    channel = fields.Selection(
        selection=[
            ("api", "API"),
            ("webhook", "Webhook"),
            ("form", "Form"),
            ("email", "Email"),
            ("ads", "Ads"),
            ("import", "Import"),
            ("other", "Other"),
        ],
        help="Channel at receipt time (may differ from source default).",
    )
    external_ref = fields.Char(
        index=True,
        help="Business key from the payload; used with the source for duplicate detection.",
    )
    request_uuid = fields.Char(
        default=lambda self: str(uuid.uuid4()),
        required=True,
        copy=False,
        index=True,
        help="Correlation id for support and tracing.",
    )
    payload_raw = fields.Text(
        help="Raw body as received (may be truncated per system settings).",
    )
    normalized_payload = fields.Json(
        help="Parsed canonical payload after validation.",
    )
    status = fields.Selection(
        selection=[
            ("pending", "Pending"),
            ("processing", "Processing"),
            ("success", "Success"),
            ("error", "Error"),
            ("rejected", "Rejected"),
        ],
        default="pending",
        required=True,
        index=True,
        help="Terminal rows are audit-only in the UI; the system updates rows via elevated access during intake.",
    )
    processing_stage = fields.Selection(
        selection=[
            ("received", "Received"),
            ("normalized", "Normalized"),
            ("deduped", "Deduped"),
            ("scored", "Scored"),
            ("assigned", "Assigned"),
            ("completed", "Completed"),
        ],
    )
    lead_id = fields.Many2one(comodel_name="crm.lead", index=True, ondelete="set null")
    duplicate_of_id = fields.Many2one(
        comodel_name="crm.lead",
        string="Duplicate of",
        index=True,
        ondelete="set null",
        help="When the intake resolved to a duplicate lead, points to the canonical master lead.",
    )
    error_message = fields.Text()
    received_at = fields.Datetime(required=True, default=fields.Datetime.now)
    processed_at = fields.Datetime(readonly=True)

    def write(self, vals):
        if self.env.context.get("lead_engine_log_unlock"):
            return super().write(vals)
        for rec in self:
            if rec.status in _TERMINAL_STATUSES:
                blocked = set(vals) & _IMMUTABLE_FIELDS
                if blocked:
                    raise UserError(
                        _("Cannot change immutable fields on a terminal intake log: %s")
                        % (", ".join(sorted(blocked)))
                    )
        return super().write(vals)

    def action_mark_processing(self):
        self.write({"status": "processing"})

    def action_mark_success(self, lead, duplicate_of=None, stage="completed"):
        vals = {
            "status": "success",
            "lead_id": lead.id,
            "duplicate_of_id": duplicate_of.id if duplicate_of else False,
            "processing_stage": stage,
            "processed_at": fields.Datetime.now(),
        }
        return self.write(vals)

    def action_mark_error(self, message, stage=None):
        vals = {
            "status": "error",
            "error_message": message,
            "processed_at": fields.Datetime.now(),
        }
        if stage:
            vals["processing_stage"] = stage
        return self.write(vals)

    def action_mark_rejected(self, message):
        return self.write(
            {
                "status": "rejected",
                "error_message": message,
                "processed_at": fields.Datetime.now(),
            }
        )
