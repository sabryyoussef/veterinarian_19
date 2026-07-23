# -*- coding: utf-8 -*-
"""One-shot / repeatable realignment of Odoo tasks to OP project ownership (test-safe)."""
from __future__ import annotations

import json
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class OpenprojectTaskRealignLine(models.TransientModel):
    _name = "openproject.task.realign.line"
    _description = "OpenProject Task Realign Audit Line"
    _order = "task_id"

    wizard_id = fields.Many2one("openproject.task.realign.wizard", required=True, ondelete="cascade")
    task_id = fields.Many2one("project.task", string="Odoo Task", readonly=True)
    task_name = fields.Char(readonly=True)
    op_work_package_id = fields.Integer(readonly=True)
    op_project_id = fields.Integer(string="OP Project ID", readonly=True)
    op_project_name = fields.Char(readonly=True)
    current_project_id = fields.Many2one("project.project", readonly=True)
    target_project_id = fields.Many2one("project.project", readonly=True)
    current_parent_id = fields.Many2one("project.task", readonly=True)
    target_parent_id = fields.Many2one("project.task", readonly=True)
    parent_action = fields.Selection(
        [
            ("keep", "Keep parent"),
            ("set", "Set parent"),
            ("clear_cross", "Clear cross-project parent"),
            ("metadata_only", "Metadata only (cross-project)"),
            ("none", "No parent"),
        ],
        readonly=True,
    )
    stage_action = fields.Char(readonly=True)
    action = fields.Selection(
        [
            ("move", "Move project"),
            ("parent", "Parent only"),
            ("unchanged", "Unchanged"),
            ("skip", "Skipped"),
        ],
        readonly=True,
    )
    note = fields.Char(readonly=True)


class OpenprojectTaskRealignWizard(models.TransientModel):
    _name = "openproject.task.realign.wizard"
    _description = "Realign Odoo Tasks to OpenProject Projects"

    backend_id = fields.Many2one(
        "openproject.backend",
        required=True,
        default=lambda self: self.env["openproject.backend"].search([], limit=1),
    )
    dry_run = fields.Boolean(
        string="Dry Run",
        default=True,
        help="When enabled, only build the audit report — no writes.",
    )
    line_ids = fields.One2many("openproject.task.realign.line", "wizard_id", readonly=True)
    audit_json = fields.Text(readonly=True)
    summary = fields.Text(readonly=True)
    state = fields.Selection([("draft", "Draft"), ("done", "Done")], default="draft")

    def action_build_audit(self):
        self.ensure_one()
        lines = self._build_audit_lines()
        self.line_ids.unlink()
        self.write(
            {
                "line_ids": [(0, 0, line) for line in lines],
                "audit_json": json.dumps(lines, indent=2, default=str),
                "summary": self._format_summary(lines),
                "state": "done",
            }
        )
        return self._reopen_wizard()

    def action_apply(self):
        self.ensure_one()
        if self.dry_run:
            raise UserError(_("Disable Dry Run before applying changes."))
        if not self.line_ids:
            self.action_build_audit()
        Task = self.env["project.task"]
        applied = 0
        for line in self.line_ids:
            if line.action in ("unchanged", "skip"):
                continue
            task = line.task_id
            if not task or not task.op_work_package_id:
                continue
            owner_map = self.env["openproject.project.map"].search(
                [
                    ("backend_id", "=", self.backend_id.id),
                    ("op_project_id", "=", task.op_project_id),
                    ("active", "=", True),
                ],
                limit=1,
            )
            changed = False
            if line.action == "move" and line.target_project_id and task.project_id != line.target_project_id:
                vals = {"project_id": line.target_project_id.id}
                vals.update(task._op_stage_vals_for_project_move(line.target_project_id))
                task.with_context(op_syncing=True).write(vals)
                changed = True
            if line.parent_action != "none" and owner_map:
                before_parent = task.parent_id.id
                before_cross = task.op_cross_project_parent
                task._op_apply_parent_link(task.op_parent_work_package_id, owner_map)
                task.invalidate_recordset(["parent_id", "op_cross_project_parent"])
                if task.parent_id.id != before_parent or task.op_cross_project_parent != before_cross:
                    changed = True
            if changed:
                applied += 1
        self.summary = (self.summary or "") + _("\n\nApplied changes to %s task(s).") % applied
        return self._reopen_wizard()

    def _reopen_wizard(self):
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    def _format_summary(self, lines: list[dict]) -> str:
        counts = {"move": 0, "parent": 0, "unchanged": 0, "skip": 0}
        for line in lines:
            counts[line.get("action", "skip")] = counts.get(line.get("action", "skip"), 0) + 1
        return _(
            "Audit: move=%(move)s parent-only=%(parent)s unchanged=%(unchanged)s skipped=%(skip)s"
        ) % {
            "move": counts["move"],
            "parent": counts["parent"],
            "unchanged": counts["unchanged"],
            "skip": counts["skip"],
        }

    def _build_audit_lines(self) -> list[dict]:
        self.ensure_one()
        Task = self.env["project.task"]
        Map = self.env["openproject.project.map"]
        backend = self.backend_id
        maps = Map.search([("backend_id", "=", backend.id), ("active", "=", True)])
        op_to_map = {m.op_project_id: m for m in maps}
        folder_op_ids = {m.op_project_id for m in maps if m.op_is_company_folder}

        lines: list[dict] = []
        tasks = Task.search(
            [
                ("op_backend_id", "=", backend.id),
                ("op_work_package_id", "!=", False),
            ]
        )
        for task in tasks:
            op_pid = task.op_project_id
            if op_pid in folder_op_ids:
                lines.append(self._line_skip(task, _("Company folder project — skip")))
                continue
            owner_map = op_to_map.get(op_pid)
            if not owner_map or not owner_map.odoo_project_id:
                lines.append(self._line_skip(task, _("No active map for OP project %s") % op_pid))
                continue

            target_project = owner_map.odoo_project_id
            parent_info = task._op_parent_link_plan(task.op_parent_work_package_id, backend, owner_map)
            move = task.project_id != target_project
            parent_action = parent_info["parent_action"]
            parent_changed = (
                parent_action == "set"
                and task.parent_id != parent_info.get("parent_task")
            ) or (
                parent_action in ("clear_cross", "metadata_only", "none")
                and bool(task.parent_id)
            )

            if not move and not parent_changed:
                lines.append(
                    {
                        "task_id": task.id,
                        "task_name": task.name,
                        "op_work_package_id": task.op_work_package_id,
                        "op_project_id": op_pid,
                        "op_project_name": owner_map.op_project_name,
                        "current_project_id": task.project_id.id,
                        "target_project_id": target_project.id,
                        "current_parent_id": task.parent_id.id if task.parent_id else False,
                        "target_parent_id": parent_info.get("parent_task").id
                        if parent_info.get("parent_task")
                        else False,
                        "parent_action": parent_action,
                        "stage_action": "",
                        "action": "unchanged",
                        "note": _("Already aligned"),
                    }
                )
                continue

            stage_note = ""
            if move:
                stage_note = task._op_stage_move_note(task.project_id, target_project)

            action = "move" if move else "parent"
            lines.append(
                {
                    "task_id": task.id,
                    "task_name": task.name,
                    "op_work_package_id": task.op_work_package_id,
                    "op_project_id": op_pid,
                    "op_project_name": owner_map.op_project_name,
                    "current_project_id": task.project_id.id,
                    "target_project_id": target_project.id,
                    "current_parent_id": task.parent_id.id if task.parent_id else False,
                    "target_parent_id": parent_info.get("parent_task").id
                    if parent_info.get("parent_task")
                    else False,
                    "parent_action": parent_action,
                    "stage_action": stage_note,
                    "action": action,
                    "note": parent_info.get("note") or "",
                }
            )
        return lines

    def _line_skip(self, task, note: str) -> dict:
        return {
            "task_id": task.id,
            "task_name": task.name,
            "op_work_package_id": task.op_work_package_id,
            "op_project_id": task.op_project_id,
            "op_project_name": "",
            "current_project_id": task.project_id.id,
            "target_project_id": task.project_id.id,
            "current_parent_id": task.parent_id.id if task.parent_id else False,
            "target_parent_id": False,
            "parent_action": "none",
            "stage_action": "",
            "action": "skip",
            "note": note,
        }
