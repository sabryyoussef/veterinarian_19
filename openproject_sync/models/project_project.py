# -*- coding: utf-8 -*-
from __future__ import annotations

import logging

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


class ProjectProject(models.Model):
    _inherit = "project.project"

    op_project_id = fields.Integer(
        string="OP Project ID",
        index=True,
        copy=False,
        help="OpenProject project id linked to this Odoo project",
    )
    op_parent_project_id = fields.Integer(
        string="OP Parent Project ID",
        index=True,
        copy=False,
    )
    op_company_project_id = fields.Integer(
        string="OP Company Project ID",
        index=True,
        copy=False,
        help="Top-level OpenProject company parent id (Edafa=20, Bright=15, …)",
    )
    op_company_key = fields.Char(
        string="OP Company Key",
        index=True,
        copy=False,
        help="edafa / bright / platform-ops / personal / testing",
    )
    op_company_name = fields.Char(
        string="OP Company",
        index=True,
        copy=False,
        help="Display name for group-by (Edafa, Bright, …)",
    )
    op_is_company_folder = fields.Boolean(
        string="OP Company Folder",
        default=False,
        index=True,
        copy=False,
        help="True for company parent projects (usually 0 tasks)",
    )
    op_is_work_project = fields.Boolean(
        string="OP Work Project",
        default=False,
        index=True,
        copy=False,
        help="True for WhatsApp / delivery projects where tasks live",
    )

    def action_op_sync_now(self):
        self.ensure_one()
        maps = self.env["openproject.project.map"].search(
            [
                ("odoo_project_id", "=", self.id),
                ("active", "=", True),
            ]
        )
        if not maps:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": "OpenProject",
                    "message": "No active OpenProject project map for this project.",
                    "type": "warning",
                    "sticky": False,
                },
            }
        totals = {
            "pulled": 0,
            "created": 0,
            "updated": 0,
            "skipped": 0,
            "warnings": 0,
            "errors": 0,
        }
        for pmap in maps:
            if not pmap.backend_id.enable_pull:
                continue
            part = pmap.action_pull(raise_on_error=False)
            for key in totals:
                totals[key] += part.get(key, 0)
        msg = (
            f"pulled:{totals['pulled']} created:{totals['created']} "
            f"updated:{totals['updated']} skipped:{totals['skipped']} "
            f"warnings:{totals['warnings']} errors:{totals['errors']}"
        )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "OpenProject Sync",
                "message": msg,
                "type": "success" if not totals["errors"] else "warning",
                "sticky": True,
            },
        }

    def _op_apply_classification(self, vals: dict):
        """Write classification fields onto this project (idempotent)."""
        self.ensure_one()
        write_vals = {
            "op_project_id": vals.get("op_project_id") or False,
            "op_parent_project_id": vals.get("op_parent_project_id") or False,
            "op_company_project_id": vals.get("op_company_project_id") or False,
            "op_company_key": vals.get("op_company_key") or False,
            "op_company_name": vals.get("op_company_name") or False,
            "op_is_company_folder": bool(vals.get("op_is_company_folder")),
            "op_is_work_project": bool(vals.get("op_is_work_project")),
        }
        need = any(self[k] != write_vals[k] for k in write_vals)
        if need:
            self.write(write_vals)

    @api.model
    def action_op_backfill_classification(self):
        """Idempotent backfill from project maps + OP API parents."""
        backends = self.env["openproject.backend"].search([("active", "=", True)])
        total = 0
        for backend in backends:
            total += backend.action_refresh_project_classification()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("OpenProject Classification"),
                "message": _("Updated classification on %s project maps") % total,
                "type": "success",
                "sticky": False,
            },
        }
