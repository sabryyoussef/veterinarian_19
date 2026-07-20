# -*- coding: utf-8 -*-
from __future__ import annotations

import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .openproject_api import OpenProjectAPIError, OpenProjectClient
from .openproject_classification import (
    href_id,
    load_group_project_map,
    resolve_classification,
)

_logger = logging.getLogger(__name__)


class OpenprojectProjectMap(models.Model):
    _name = "openproject.project.map"
    _description = "OpenProject Project Map"
    _order = "op_company_name, op_project_name, id"
    _rec_name = "display_name"

    backend_id = fields.Many2one(
        "openproject.backend",
        required=True,
        ondelete="cascade",
        index=True,
    )
    op_project_id = fields.Integer(string="OP Project ID", required=True, index=True)
    op_project_name = fields.Char(string="OP Project Name")
    op_parent_project_id = fields.Integer(string="OP Parent Project ID", index=True)
    op_company_project_id = fields.Integer(string="OP Company Project ID", index=True)
    op_company_key = fields.Char(string="OP Company Key", index=True)
    op_company_name = fields.Char(string="OP Company", index=True)
    op_is_company_folder = fields.Boolean(string="Company Folder", default=False, index=True)
    op_is_work_project = fields.Boolean(string="Work Project", default=False, index=True)
    odoo_project_id = fields.Many2one(
        "project.project",
        string="Odoo Project",
        ondelete="restrict",
        index=True,
    )
    active = fields.Boolean(default=True)
    auto_create_project = fields.Boolean(
        string="Auto-create Odoo Project",
        default=False,
        help="If enabled and odoo_project_id is empty, create a project on first pull.",
    )
    op_push_create = fields.Boolean(
        string="Push Create to OpenProject",
        default=False,
        help="Allow creating OP work packages from new Odoo tasks in this project.",
    )
    last_pull_at = fields.Datetime(string="Last Successful Pull", readonly=True)
    display_name = fields.Char(compute="_compute_display_name", store=True)

    _uniq_backend_op_project = models.Constraint(
        "UNIQUE(backend_id, op_project_id)",
        "This OpenProject project is already mapped for this backend.",
    )

    @api.depends("op_project_id", "op_project_name", "odoo_project_id")
    def _compute_display_name(self):
        for rec in self:
            left = rec.op_project_name or f"OP#{rec.op_project_id}"
            right = rec.odoo_project_id.display_name if rec.odoo_project_id else "?"
            rec.display_name = f"{left} ↔ {right}"

    def action_sync_now(self):
        self.ensure_one()
        if not self.backend_id.enable_pull:
            raise UserError(_("Pull is disabled on backend “%s”.") % self.backend_id.name)
        stats = self.with_context(op_force_full_pull=True).action_pull(raise_on_error=True)
        msg = _(
            "pulled:%(pulled)s created:%(created)s updated:%(updated)s "
            "skipped:%(skipped)s warnings:%(warnings)s errors:%(errors)s"
        ) % stats
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("OpenProject Pull"),
                "message": msg,
                "type": "success" if not stats.get("errors") else "warning",
                "sticky": True,
            },
        }

    def action_pull(self, raise_on_error: bool = False) -> dict:
        self.ensure_one()
        Log = self.env["openproject.sync.log"]
        stats = {
            "pulled": 0,
            "created": 0,
            "updated": 0,
            "skipped": 0,
            "warnings": 0,
            "errors": 0,
        }
        if not self.active:
            stats["skipped"] += 1
            Log.log(
                name="Pull Skipped (inactive map)",
                operation="skip",
                direction="inbound",
                state="warning",
                message=_("Project map is inactive"),
                backend=self.backend_id,
                project_map=self,
            )
            return stats

        if not self.backend_id.enable_pull:
            stats["skipped"] += 1
            Log.log(
                name="Pull Skipped (pull disabled)",
                operation="skip",
                direction="inbound",
                state="warning",
                message=_("Backend pull disabled"),
                backend=self.backend_id,
                project_map=self,
            )
            return stats

        odoo_project = self._ensure_odoo_project()
        if not odoo_project:
            stats["errors"] += 1
            msg = _("No Odoo project mapped and auto_create_project is False")
            Log.log(
                name="Pull Error",
                operation="error",
                direction="inbound",
                state="error",
                message=msg,
                backend=self.backend_id,
                project_map=self,
            )
            if raise_on_error:
                raise UserError(msg)
            return stats

        # Keep classification fresh on every pull (idempotent; no task moves)
        try:
            self.apply_classification()
        except Exception as e:
            _logger.warning("Classification apply failed for map %s: %s", self.id, e)

        pull_started_at = fields.Datetime.now()
        updated_after = None
        # Use ONLY this map's watermark. Never fall back to backend.last_pull_at —
        # that would skip other projects' older WPs after the first map succeeds.
        force_full = bool(self.env.context.get("op_force_full_pull"))
        watermark = None if force_full else self.last_pull_at
        if watermark:
            # OpenProject expects ISO-8601; use UTC-ish string Odoo stores
            updated_after = fields.Datetime.to_string(watermark).replace(" ", "T") + "Z"

        client = self.backend_id._get_client()
        offset = 1
        page_size = 100
        collected: list[dict] = []

        try:
            while True:
                payload = client.list_project_work_packages(
                    self.op_project_id,
                    updated_after=updated_after,
                    offset=offset,
                    page_size=page_size,
                )
                elements = (payload.get("_embedded") or {}).get("elements") or []
                collected.extend(elements)
                total = payload.get("total") or len(elements)
                count = payload.get("count") or len(elements)
                if not elements or offset + count > total:
                    break
                offset += page_size
        except OpenProjectAPIError as e:
            stats["errors"] += 1
            Log.log(
                name="Pull API Error",
                operation="error",
                direction="inbound",
                state="error",
                message=str(e),
                details=e.body,
                backend=self.backend_id,
                project_map=self,
            )
            if raise_on_error:
                raise UserError(str(e)) from e
            return stats

        stats["pulled"] = len(collected)
        Task = self.env["project.task"]
        pending_parents: list[tuple] = []  # (task, parent_wp_id)

        for wp in collected:
            try:
                real_pid = OpenProjectClient.wp_link_id(wp, "project")
                pull_map = self
                if real_pid and real_pid != self.op_project_id:
                    owner = Task._op_owner_map_for_wp(self.backend_id, real_pid, self)
                    if owner and owner.op_project_id == real_pid and not owner.op_is_company_folder:
                        pull_map = owner
                    else:
                        stats["skipped"] += 1
                        Log.log(
                            name=f"Skip related WP {wp.get('id')}",
                            operation="skip",
                            direction="inbound",
                            state="ok",
                            message=_(
                                "WP primary project is %s, not map project %s"
                            )
                            % (real_pid, self.op_project_id),
                            backend=self.backend_id,
                            project_map=self,
                            op_work_package_id=wp.get("id"),
                        )
                        continue

                task, created, parent_wp_id, warnings = Task._op_upsert_from_wp(
                    pull_map, wp, resolve_parent=False
                )
                if not task:
                    stats["skipped"] += 1
                    stats["warnings"] += warnings
                    continue
                if created:
                    stats["created"] += 1
                else:
                    stats["updated"] += 1
                stats["warnings"] += warnings
                if parent_wp_id:
                    pending_parents.append((task, parent_wp_id))
                Log.log(
                    name=f"{'Create' if created else 'Update'} WP {wp.get('id')}",
                    operation="create" if created else "update",
                    direction="inbound",
                    state="warning" if warnings else "ok",
                    message=task.name,
                    backend=self.backend_id,
                    project_map=self,
                    task=task,
                    op_work_package_id=wp.get("id"),
                )
            except Exception as e:
                stats["errors"] += 1
                _logger.exception("Failed upsert WP %s", wp.get("id"))
                Log.log(
                    name=f"Upsert Error WP {wp.get('id')}",
                    operation="error",
                    direction="inbound",
                    state="error",
                    message=str(e),
                    backend=self.backend_id,
                    project_map=self,
                    op_work_package_id=wp.get("id"),
                )

        # Pass 2: parents (cross-project aware)
        for task, parent_wp_id in pending_parents:
            try:
                owner_map = self.env["openproject.project.map"].search(
                    [
                        ("backend_id", "=", task.op_backend_id.id),
                        ("op_project_id", "=", task.op_project_id),
                        ("active", "=", True),
                    ],
                    limit=1,
                ) or self
                plan = task._op_apply_parent_link(parent_wp_id, owner_map)
                if plan.get("parent_action") == "none" and parent_wp_id:
                    stats["warnings"] += 1
                    Log.log(
                        name=f"Parent missing WP {parent_wp_id}",
                        operation="warning",
                        direction="inbound",
                        state="warning",
                        message=plan.get("note")
                        or (_("Parent WP %s not found/mapped; left empty") % parent_wp_id),
                        backend=self.backend_id,
                        project_map=self,
                        task=task,
                        op_work_package_id=task.op_work_package_id,
                    )
            except Exception as e:
                stats["warnings"] += 1
                Log.log(
                    name="Parent resolve warning",
                    operation="warning",
                    direction="inbound",
                    state="warning",
                    message=str(e),
                    backend=self.backend_id,
                    project_map=self,
                    task=task,
                )

        # Update watermarks only after successful completion
        if stats["errors"] == 0:
            self.write({"last_pull_at": pull_started_at})
            self.backend_id.write({"last_pull_at": pull_started_at})

        Log.log(
            name="Pull Map Summary",
            operation="summary",
            direction="inbound",
            state="error" if stats["errors"] else ("warning" if stats["warnings"] else "ok"),
            message=str(stats),
            backend=self.backend_id,
            project_map=self,
        )
        Log.log(
            name="Pull",
            operation="pull",
            direction="inbound",
            state="error" if stats["errors"] else "ok",
            message=_("Pulled %s work packages") % stats["pulled"],
            details=str(stats),
            backend=self.backend_id,
            project_map=self,
        )
        return stats

    def _ensure_odoo_project(self):
        self.ensure_one()
        if self.odoo_project_id:
            self._apply_classification_to_odoo_project()
            return self.odoo_project_id
        if not self.auto_create_project:
            return self.env["project.project"]
        name = self.op_project_name or f"OpenProject {self.op_project_id}"
        if not str(name).startswith("OP:"):
            name = f"OP: {name}"
        project = self.env["project.project"].create({"name": name})
        self.odoo_project_id = project.id
        self._apply_classification_to_odoo_project()
        self.env["openproject.sync.log"].log(
            name="Auto-created Odoo project",
            operation="create",
            direction="inbound",
            state="ok",
            message=project.display_name,
            backend=self.backend_id,
            project_map=self,
        )
        return project

    def _classification_vals(self, parent_id=None, parent_chain=None, map_data=None):
        self.ensure_one()
        return resolve_classification(
            self.op_project_id,
            parent_id=parent_id if parent_id is not None else self.op_parent_project_id or None,
            parent_chain=parent_chain,
            map_data=map_data,
        )

    def apply_classification(self, parent_id=None, parent_chain=None, map_data=None):
        """Update map + linked Odoo project classification (idempotent)."""
        map_data = map_data or load_group_project_map()
        for rec in self:
            vals = rec._classification_vals(
                parent_id=parent_id,
                parent_chain=parent_chain,
                map_data=map_data,
            )
            # Prefer explicit parent_id argument when refreshing from API
            if parent_id is not None:
                vals["op_parent_project_id"] = int(parent_id) if parent_id else False
            map_write = {
                "op_parent_project_id": vals.get("op_parent_project_id") or False,
                "op_company_project_id": vals.get("op_company_project_id") or False,
                "op_company_key": vals.get("op_company_key") or False,
                "op_company_name": vals.get("op_company_name") or False,
                "op_is_company_folder": bool(vals.get("op_is_company_folder")),
                "op_is_work_project": bool(vals.get("op_is_work_project")),
            }
            changed = any(rec[k] != map_write[k] for k in map_write)
            if changed:
                rec.write(map_write)
            rec._apply_classification_to_odoo_project()
        return True

    def _apply_classification_to_odoo_project(self):
        self.ensure_one()
        if not self.odoo_project_id:
            return
        self.odoo_project_id._op_apply_classification(
            {
                "op_project_id": self.op_project_id,
                "op_parent_project_id": self.op_parent_project_id,
                "op_company_project_id": self.op_company_project_id,
                "op_company_key": self.op_company_key,
                "op_company_name": self.op_company_name,
                "op_is_company_folder": self.op_is_company_folder,
                "op_is_work_project": self.op_is_work_project,
            }
        )
