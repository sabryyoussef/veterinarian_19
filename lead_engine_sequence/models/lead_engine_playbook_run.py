# -*- coding: utf-8 -*-

import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class LeadEnginePlaybookRun(models.Model):
    _name = "lead.engine.playbook.run"
    _description = "Lead Engine Playbook Run"
    _order = "create_date desc, id desc"

    name = fields.Char(compute="_compute_name", store=True)
    playbook_id = fields.Many2one(
        comodel_name="lead.engine.playbook",
        required=True,
        ondelete="restrict",
    )
    lead_id = fields.Many2one(
        comodel_name="crm.lead",
        required=True,
        ondelete="cascade",
        index=True,
    )
    company_id = fields.Many2one(
        related="lead_id.company_id",
        store=True,
    )
    state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("running", "Running"),
            ("done", "Done"),
            ("cancelled", "Cancelled"),
            ("error", "Error"),
        ],
        default="draft",
        required=True,
        index=True,
    )
    started_at = fields.Datetime()
    completed_at = fields.Datetime()
    error_message = fields.Text()
    line_ids = fields.One2many(
        comodel_name="lead.engine.playbook.run.line",
        inverse_name="run_id",
        string="Lines",
    )
    pending_due_line_count = fields.Integer(
        string="Due pending steps",
        compute="_compute_pending_due_line_count",
        help="Pending lines whose scheduled time has passed (waiting on cron or manual process).",
    )

    @api.depends(
        "line_ids.state",
        "line_ids.scheduled_at",
        "state",
    )
    def _compute_pending_due_line_count(self):
        now = fields.Datetime.now()
        for run in self:
            if run.state != "running":
                run.pending_due_line_count = 0
                continue
            run.pending_due_line_count = len(
                run.line_ids.filtered(
                    lambda l: l.state == "pending" and l.scheduled_at <= now
                )
            )

    @api.depends("playbook_id", "lead_id")
    def _compute_name(self):
        for rec in self:
            pb = rec.playbook_id.name or ""
            lead = rec.lead_id.name or ""
            rec.name = f"{pb} — {lead}" if pb or lead else "Run"

    @api.model
    def cron_execute_due_playbook_steps(self):
        """Lean cron entry: process all due lines across running playbooks."""
        self.env["lead.engine.playbook.service"].execute_due_steps()
        return True

    def action_cancel_run(self):
        self.ensure_one()
        svc = self.env["lead.engine.playbook.service"]
        svc.cancel_run(self)
        return self._action_reload_form()

    def action_retry_run(self):
        self.ensure_one()
        svc = self.env["lead.engine.playbook.service"]
        svc.retry_errored_run(self)
        return self._action_reload_form()

    def action_process_due_steps(self):
        """Execute pending lines on this run that are already due (same as cron, scoped)."""
        self.ensure_one()
        if self.state != "running":
            raise UserError(_("Only running runs can process due steps."))
        self.env["lead.engine.playbook.service"].execute_due_steps(run=self)
        return self._action_reload_form()

    def _action_reload_form(self):
        self.invalidate_recordset()
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "current",
            "views": [(False, "form")],
        }

    def action_open_lead(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.lead_id.display_name,
            "res_model": "crm.lead",
            "res_id": self.lead_id.id,
            "view_mode": "form",
            "target": "current",
        }


class LeadEnginePlaybookRunLine(models.Model):
    _name = "lead.engine.playbook.run.line"
    _description = "Lead Engine Playbook Run Line"
    _order = "run_id, sequence, id"

    run_id = fields.Many2one(
        comodel_name="lead.engine.playbook.run",
        required=True,
        ondelete="cascade",
        index=True,
    )
    step_id = fields.Many2one(
        comodel_name="lead.engine.playbook.step",
        required=True,
        ondelete="restrict",
    )
    sequence = fields.Integer(required=True)
    state = fields.Selection(
        selection=[
            ("pending", "Pending"),
            ("due", "Due"),
            ("done", "Done"),
            ("skipped", "Skipped"),
            ("error", "Error"),
        ],
        default="pending",
        required=True,
        index=True,
    )
    scheduled_at = fields.Datetime(required=True)
    executed_at = fields.Datetime()
    error_message = fields.Text()
