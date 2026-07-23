# -*- coding: utf-8 -*-
from odoo import api, fields, models


class OpenprojectSyncLog(models.Model):
    _name = "openproject.sync.log"
    _description = "OpenProject Sync Log"
    _order = "create_date desc, id desc"

    name = fields.Char(required=True, index=True)
    backend_id = fields.Many2one(
        "openproject.backend",
        string="Backend",
        ondelete="cascade",
        index=True,
    )
    project_map_id = fields.Many2one(
        "openproject.project.map",
        string="Project Map",
        ondelete="set null",
        index=True,
    )
    task_id = fields.Many2one(
        "project.task",
        string="Task",
        ondelete="set null",
        index=True,
    )
    op_work_package_id = fields.Integer(string="OP Work Package ID", index=True)
    operation = fields.Selection(
        [
            ("pull", "Pull"),
            ("push", "Push"),
            ("create", "Create"),
            ("update", "Update"),
            ("skip", "Skip"),
            ("warning", "Warning"),
            ("error", "Error"),
            ("conflict", "Conflict"),
            ("test", "Test Connection"),
            ("summary", "Summary"),
        ],
        required=True,
        index=True,
        default="pull",
    )
    direction = fields.Selection(
        [
            ("inbound", "OP → Odoo"),
            ("outbound", "Odoo → OP"),
            ("none", "None"),
        ],
        default="none",
        required=True,
    )
    state = fields.Selection(
        [
            ("ok", "OK"),
            ("warning", "Warning"),
            ("error", "Error"),
            ("conflict", "Conflict"),
        ],
        default="ok",
        required=True,
        index=True,
    )
    message = fields.Text()
    details = fields.Text()

    @api.model
    def log(
        self,
        *,
        name: str,
        operation: str,
        direction: str = "none",
        state: str = "ok",
        message: str = "",
        details: str = "",
        backend=None,
        project_map=None,
        task=None,
        op_work_package_id: int | None = None,
    ):
        vals = {
            "name": (name or operation)[:255],
            "operation": operation,
            "direction": direction,
            "state": state,
            "message": message or False,
            "details": details or False,
            "op_work_package_id": op_work_package_id or False,
        }
        if backend:
            vals["backend_id"] = backend.id
        if project_map:
            vals["project_map_id"] = project_map.id
        if task:
            vals["task_id"] = task.id
        return self.sudo().create(vals)
