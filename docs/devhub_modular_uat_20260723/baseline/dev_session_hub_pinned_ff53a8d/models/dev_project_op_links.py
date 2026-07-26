# -*- coding: utf-8 -*-
"""Dev Hub project ↔ OpenProject map links and task/work-item UI helpers."""
from __future__ import annotations

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError


class DevProject(models.Model):
    _inherit = "dev.project"

    openproject_map_ids = fields.Many2many(
        "openproject.project.map",
        "dev_project_openproject_map_rel",
        "dev_project_id",
        "openproject_map_id",
        string="OpenProject Maps",
        help="Explicit OpenProject project maps driving Odoo task / WP tabs. "
        "Do not rely on openproject_reference (label only).",
    )
    has_openproject_mapping = fields.Boolean(
        compute="_compute_openproject_task_links",
    )
    odoo_project_ids = fields.Many2many(
        "project.project",
        compute="_compute_openproject_task_links",
        string="Linked Odoo Projects",
    )
    primary_odoo_project_id = fields.Many2one(
        "project.project",
        compute="_compute_openproject_task_links",
        string="Primary Odoo Project",
    )
    mapped_task_ids = fields.Many2many(
        "project.task",
        compute="_compute_openproject_task_links",
        string="Mapped Odoo Tasks",
    )
    mapped_op_task_ids = fields.Many2many(
        "project.task",
        compute="_compute_openproject_task_links",
        string="Mapped OpenProject Work Packages",
    )

    @api.depends(
        "openproject_map_ids",
        "openproject_map_ids.odoo_project_id",
        "openproject_map_ids.op_project_id",
        "openproject_map_ids.active",
    )
    def _compute_openproject_task_links(self):
        Task = self.env["project.task"]
        for project in self:
            maps = project.openproject_map_ids
            odoo_projects = maps.mapped("odoo_project_id")
            project.odoo_project_ids = odoo_projects
            project.has_openproject_mapping = bool(maps)
            distinct = odoo_projects
            project.primary_odoo_project_id = (
                distinct[:1] if len(distinct) == 1 else distinct.browse()
            )
            if not odoo_projects:
                project.mapped_task_ids = Task
                project.mapped_op_task_ids = Task
                continue
            op_project_ids = [opid for opid in maps.mapped("op_project_id") if opid]
            domain = [("project_id", "in", odoo_projects.ids)]
            tasks = Task.search(domain)
            project.mapped_task_ids = tasks
            if op_project_ids:
                project.mapped_op_task_ids = tasks.filtered(
                    lambda t: t.op_work_package_id
                    and (
                        t.op_project_id in op_project_ids
                        or t.project_id in odoo_projects
                    )
                )
            else:
                project.mapped_op_task_ids = tasks.filtered(
                    lambda t: bool(t.op_work_package_id)
                )

    def action_open_primary_odoo_project(self):
        self.ensure_one()
        if not self.primary_odoo_project_id:
            if not self.odoo_project_ids:
                raise UserError(
                    _("No Odoo project is linked. Add an OpenProject map first.")
                )
            return {
                "type": "ir.actions.act_window",
                "name": _("Linked Odoo Projects"),
                "res_model": "project.project",
                "view_mode": "list,form",
                "domain": [("id", "in", self.odoo_project_ids.ids)],
                "target": "current",
            }
        return {
            "type": "ir.actions.act_window",
            "res_model": "project.project",
            "res_id": self.primary_odoo_project_id.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_pull_openproject_maps(self):
        """Pull/refresh all active linked maps. Never expose API tokens to the client."""
        self.ensure_one()
        if not self.env.user.has_group("dev_session_hub.group_dev_hub_manager"):
            raise AccessError(_("Only Dev Hub managers can pull OpenProject maps."))
        maps = self.openproject_map_ids.filtered("active")
        if not maps:
            raise UserError(_("No active OpenProject maps are linked to this project."))
        totals = {
            "pulled": 0,
            "created": 0,
            "updated": 0,
            "skipped": 0,
            "warnings": 0,
            "errors": 0,
            "maps": 0,
        }
        messages = []
        for pmap in maps:
            backend = pmap.backend_id
            if not backend or not backend.enable_pull:
                messages.append(
                    _("Map %(map)s: pull disabled on backend.")
                    % {"map": pmap.display_name}
                )
                totals["errors"] += 1
                continue
            try:
                # sudo only for token-bearing client inside openproject_sync pull
                stats = pmap.sudo().with_context(op_force_full_pull=True).action_pull(
                    raise_on_error=False
                )
                totals["maps"] += 1
                for key in (
                    "pulled",
                    "created",
                    "updated",
                    "skipped",
                    "warnings",
                    "errors",
                ):
                    totals[key] += int(stats.get(key) or 0)
                messages.append(
                    _(
                        "%(map)s → pulled:%(pulled)s created:%(created)s "
                        "updated:%(updated)s errors:%(errors)s"
                    )
                    % {
                        "map": pmap.display_name,
                        "pulled": stats.get("pulled", 0),
                        "created": stats.get("created", 0),
                        "updated": stats.get("updated", 0),
                        "errors": stats.get("errors", 0),
                    }
                )
            except Exception as exc:  # noqa: BLE001 — surface per-map failure
                totals["errors"] += 1
                messages.append(
                    _("Map %(map)s failed: %(err)s")
                    % {"map": pmap.display_name, "err": str(exc)[:300]}
                )
        # Invalidate computed task lists for the open form
        self.invalidate_recordset(
            ["mapped_task_ids", "mapped_op_task_ids", "odoo_project_ids"]
        )
        notif_type = "success" if not totals["errors"] else "warning"
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("OpenProject Pull"),
                "message": "\n".join(messages)
                or _(
                    "pulled:%(pulled)s created:%(created)s updated:%(updated)s "
                    "errors:%(errors)s"
                )
                % totals,
                "type": notif_type,
                "sticky": True,
            },
        }

    def action_ensure_work_item_for_task(self):
        """Idempotently create or open a work item for the task in context."""
        self.ensure_one()
        task_id = self.env.context.get("default_task_id") or self.env.context.get(
            "active_id"
        )
        # When called from a task row button, active_model is project.task
        if self.env.context.get("active_model") == "project.task":
            task_id = self.env.context.get("active_id")
        task = self.env["project.task"].browse(task_id).exists()
        if not task:
            raise UserError(_("No Odoo task was provided."))
        return self._ensure_work_item_for_task(task)

    def _ensure_work_item_for_task(self, task):
        """Create or open work item; never duplicate."""
        self.ensure_one()
        Work = self.env["dev.work.item"]
        existing = Work.search([("odoo_task_id", "=", task.id)], limit=1)
        if not existing and task.op_backend_id and task.op_work_package_id:
            existing = Work.search(
                [
                    ("op_backend_id", "=", task.op_backend_id.id),
                    ("op_work_package_id", "=", task.op_work_package_id),
                ],
                limit=1,
            )
        if existing:
            if existing.dev_project_id and existing.dev_project_id != self:
                raise UserError(
                    _(
                        "Task %(task)s is already linked to Dev Hub project %(code)s."
                    )
                    % {
                        "task": task.display_name,
                        "code": existing.dev_project_id.code,
                    }
                )
            return {
                "type": "ir.actions.act_window",
                "res_model": "dev.work.item",
                "res_id": existing.id,
                "view_mode": "form",
                "target": "current",
            }

        mapped_projects = self.openproject_map_ids.mapped("odoo_project_id")
        if mapped_projects and task.project_id not in mapped_projects:
            raise UserError(
                _("Task %(task)s is outside this Dev Hub project's mapped Odoo projects.")
                % {"task": task.display_name}
            )

        Msg = self.env["dev.work.source.message"]
        provider_mid = "op-import-task-%s" % task.id
        if task.op_work_package_id:
            provider_mid = "op-import-wp-%s" % task.op_work_package_id
        src = Msg.search(
            [("provider", "=", "manual"), ("provider_message_id", "=", provider_mid)],
            limit=1,
        )
        if not src:
            src_vals = {
                "provider": "manual",
                "provider_message_id": provider_mid,
                "message_timestamp": fields.Datetime.now(),
                "text_snapshot": _(
                    "Imported from Odoo task %(task)s (OpenProject WP #%(wp)s) "
                    "for Dev Hub project %(code)s."
                )
                % {
                    "task": task.display_name,
                    "wp": task.op_work_package_id or "n/a",
                    "code": self.code,
                },
            }
            if "source_url" in Msg._fields and task.op_url:
                src_vals["source_url"] = task.op_url
            src = Msg.create(src_vals)

        vals = {
            "name": task.name,
            "dev_project_id": self.id,
            "odoo_project_id": task.project_id.id,
            "odoo_task_id": task.id,
            "responsible_user_id": self.owner_id.id or self.env.user.id,
            "source_message_ids": [(4, src.id)],
        }
        if self.default_repository_id:
            vals["preferred_repository_id"] = self.default_repository_id.id
        if self.default_environment_id:
            vals["preferred_environment_id"] = self.default_environment_id.id
        if task.op_backend_id:
            vals["op_backend_id"] = task.op_backend_id.id
        if task.op_work_package_id:
            vals["op_work_package_id"] = task.op_work_package_id
        if task.op_url:
            vals["op_url"] = task.op_url
        work = Work.create(vals)
        return {
            "type": "ir.actions.act_window",
            "res_model": "dev.work.item",
            "res_id": work.id,
            "view_mode": "form",
            "target": "current",
        }


class ProjectTask(models.Model):
    _inherit = "project.task"

    dev_work_item_id = fields.Many2one(
        "dev.work.item",
        string="Dev Hub Work Item",
        compute="_compute_dev_work_item_id",
        search="_search_dev_work_item_id",
    )

    def _compute_dev_work_item_id(self):
        Work = self.env["dev.work.item"]
        for task in self:
            work = Work.search([("odoo_task_id", "=", task.id)], limit=1)
            task.dev_work_item_id = work

    def _search_dev_work_item_id(self, operator, value):
        Work = self.env["dev.work.item"]
        if operator in ("=", "!=") and isinstance(value, bool):
            linked = Work.search([("odoo_task_id", "!=", False)]).mapped("odoo_task_id").ids
            if (operator == "=" and value) or (operator == "!=" and not value):
                return [("id", "in", linked)]
            return [("id", "not in", linked)]
        works = Work.search([("id", operator, value)])
        return [("id", "in", works.mapped("odoo_task_id").ids)]

    def action_dev_hub_open_work_item(self):
        self.ensure_one()
        if not self.dev_work_item_id:
            raise UserError(_("No Dev Hub work item is linked to this task."))
        return {
            "type": "ir.actions.act_window",
            "res_model": "dev.work.item",
            "res_id": self.dev_work_item_id.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_dev_hub_ensure_work_item(self):
        self.ensure_one()
        dev_project = self.env["dev.project"].browse(
            self.env.context.get("dev_project_id")
        ).exists()
        if not dev_project:
            maps = self.env["openproject.project.map"].search(
                [("odoo_project_id", "=", self.project_id.id)]
            )
            dev_project = self.env["dev.project"].search(
                [("openproject_map_ids", "in", maps.ids)], limit=1
            )
        if not dev_project:
            raise UserError(
                _(
                    "No Dev Hub project maps this task's Odoo project. "
                    "Link an OpenProject map on the Dev Hub project first."
                )
            )
        return dev_project._ensure_work_item_for_task(self)
