# -*- coding: utf-8 -*-
"""Capability-aware Dev Hub workflow dashboard (orchestration only)."""
from __future__ import annotations

from odoo import api, fields, models


class DevWorkflowCapability(models.Model):
    _name = "dev.workflow.capability"
    _description = "Dev Hub Workflow Capability"
    _order = "sequence, id"

    name = fields.Char(required=True)
    technical_name = fields.Char(required=True, index=True)
    sequence = fields.Integer(default=10)
    model_hint = fields.Char(
        help="Optional model name used for soft discovery (e.g. dev.work.analysis)."
    )
    active = fields.Boolean(default=True)
    installed = fields.Boolean(compute="_compute_installed")

    @api.depends("model_hint", "technical_name")
    def _compute_installed(self):
        for record in self:
            if record.model_hint:
                record.installed = record.model_hint in self.env
            else:
                record.installed = True


class DevWorkflowBoard(models.Model):
    _name = "dev.workflow.board"
    _description = "Dev Hub Workflow Board"

    name = fields.Char(default="Dev Hub Workflow", required=True)
    capability_ids = fields.Many2many(
        "dev.workflow.capability",
        compute="_compute_capability_ids",
        string="Discovered Capabilities",
    )
    work_item_count = fields.Integer(compute="_compute_kpis")
    analysis_count = fields.Integer(compute="_compute_kpis")
    plan_count = fields.Integer(compute="_compute_kpis")
    awaiting_approval_count = fields.Integer(compute="_compute_kpis")
    execution_count = fields.Integer(compute="_compute_kpis")
    stage_summary = fields.Text(compute="_compute_kpis")
    how_to_use = fields.Text(compute="_compute_kpis")
    next_actions = fields.Text(compute="_compute_kpis")

    @api.depends()
    def _compute_capability_ids(self):
        caps = self.env["dev.workflow.capability"].search([])
        for board in self:
            board.capability_ids = caps

    @api.depends()
    def _compute_kpis(self):
        Work = self.env["dev.work.item"] if "dev.work.item" in self.env else None
        for board in self:
            board.work_item_count = Work.search_count([]) if Work is not None else 0
            board.analysis_count = (
                self.env["dev.work.analysis"].search_count([])
                if "dev.work.analysis" in self.env
                else 0
            )
            board.plan_count = (
                self.env["dev.work.plan"].search_count([])
                if "dev.work.plan" in self.env
                else 0
            )
            board.awaiting_approval_count = (
                Work.search_count([("lifecycle_phase", "=", "awaiting_plan_approval")])
                if Work is not None
                else 0
            )
            board.execution_count = (
                self.env["dev.execution.workspace"].search_count([])
                if "dev.execution.workspace" in self.env
                else 0
            )
            stages = []
            for cap in board.capability_ids.sorted("sequence"):
                if cap.installed:
                    stages.append(cap.name)
            board.stage_summary = " → ".join(stages) if stages else "Work"
            board.how_to_use = (
                "Each step is its own app icon (DH Work, DH Analysis, DH Plan, …).\n"
                "Open the app for the step you are on. If something is missing, the "
                "form shows a red banner: Complete these first — finish that step, then continue.\n"
                "Governed path: Work → Analysis → Plan → Approval → Session/Execution → "
                "Git → GitHub → Deploy."
            )
            actions = []
            if Work is not None:
                waiting = Work.search_count(
                    [("lifecycle_phase", "=", "awaiting_plan_approval")]
                )
                analyzing = Work.search_count([("lifecycle_phase", "=", "analyzing")])
                planning = Work.search_count([("lifecycle_phase", "=", "planning")])
                approved = Work.search_count([("lifecycle_phase", "=", "approved")])
                if analyzing:
                    actions.append(
                        "%s work item(s) in Analyzing — open DH Analysis and Accept."
                        % analyzing
                    )
                if planning:
                    actions.append(
                        "%s work item(s) in Planning — open DH Plan, complete fields/steps, Request Approval."
                        % planning
                    )
                if waiting:
                    actions.append(
                        "%s work item(s) awaiting plan approval — open DH Approval."
                        % waiting
                    )
                if approved:
                    actions.append(
                        "%s work item(s) approved — open DH Sessions / DH Execution."
                        % approved
                    )
            board.next_actions = (
                "\n".join("• %s" % line for line in actions)
                if actions
                else "• No gated work waiting right now. Open DH Work to start a new item."
            )

    @api.model
    def action_open_board(self):
        board = self.search([], limit=1)
        if not board:
            board = self.create({"name": "Dev Hub Workflow"})
        return {
            "type": "ir.actions.act_window",
            "name": "Workflow",
            "res_model": "dev.workflow.board",
            "view_mode": "form",
            "res_id": board.id,
            "target": "current",
        }
