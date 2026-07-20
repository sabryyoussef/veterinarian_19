# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import json
import logging
import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .openproject_api import OpenProjectAPIError, OpenProjectClient

_logger = logging.getLogger(__name__)

SYNC_FIELDS = frozenset(
    {
        "name",
        "description",
        "stage_id",
        "user_ids",
        "date_deadline",
        "parent_id",
        "priority",
    }
)

_PRIORITY_OP_TO_ODOO = {
    7: "0",
    8: "1",
    9: "2",
    10: "3",
}
_PRIORITY_ODOO_TO_OP = {
    "0": 7,
    "1": 8,
    "2": 9,
    "3": 10,
}


class ProjectTask(models.Model):
    _inherit = "project.task"

    op_backend_id = fields.Many2one(
        "openproject.backend",
        string="OpenProject Backend",
        index=True,
        ondelete="set null",
        copy=False,
    )
    op_project_id = fields.Integer(string="OP Project ID", index=True, copy=False)
    op_project_name = fields.Char(
        string="OP Project Name",
        copy=False,
        help="OpenProject project name for this work package (authoritative ownership).",
    )
    op_parent_work_package_id = fields.Integer(
        string="OP Parent WP ID",
        index=True,
        copy=False,
        help="Logical OpenProject parent work package (may be cross-project).",
    )
    op_parent_subject = fields.Char(
        string="OP Parent Subject",
        copy=False,
    )
    op_parent_op_project_id = fields.Integer(
        string="OP Parent Project ID",
        index=True,
        copy=False,
        help="OpenProject project id of the logical parent work package.",
    )
    op_cross_project_parent = fields.Boolean(
        string="Cross-Project OP Parent",
        copy=False,
        help="True when the OpenProject parent belongs to a different project than this task.",
    )
    op_work_package_id = fields.Integer(
        string="OP Work Package ID",
        index=True,
        copy=False,
    )
    op_lock_version = fields.Integer(string="OP Lock Version", copy=False)
    op_url = fields.Char(string="OpenProject URL", copy=False)
    op_last_sync = fields.Datetime(string="Last OP Sync", copy=False)
    op_sync_state = fields.Selection(
        [
            ("synced", "Synced"),
            ("error", "Error"),
            ("conflict", "Conflict"),
        ],
        string="OP Sync State",
        copy=False,
    )
    op_sync_hash = fields.Char(string="OP Sync Hash", copy=False, index=True)
    op_last_error = fields.Text(string="OP Last Error", copy=False)
    op_description_raw = fields.Text(string="OP Description (raw)", copy=False)

    # Uniqueness for linked WPs is enforced in init() with a partial unique index
    # so unlinked tasks (NULL op_work_package_id) are not constrained.

    def init(self):
        super().init()
        self.env.cr.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS openproject_sync_task_backend_wp_uniq
            ON project_task (op_backend_id, op_work_package_id)
            WHERE op_backend_id IS NOT NULL AND op_work_package_id IS NOT NULL
            """
        )

    def action_open_op_url(self):
        self.ensure_one()
        if not self.op_url:
            raise UserError(_("No OpenProject URL on this task."))
        return {
            "type": "ir.actions.act_url",
            "url": self.op_url,
            "target": "new",
        }

    # ------------------------------------------------------------------
    # Hash / description helpers
    # ------------------------------------------------------------------
    @api.model
    def _op_compute_sync_hash(self, vals: dict) -> str:
        payload = {
            "name": vals.get("name") or "",
            "description": vals.get("description") or "",
            "stage_id": vals.get("stage_id") or False,
            "user_ids": sorted(vals.get("user_ids") or []),
            "date_deadline": str(vals.get("date_deadline") or ""),
            "parent_id": vals.get("parent_id") or False,
            "priority": vals.get("priority") or "",
        }
        raw = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()

    def _op_current_sync_vals(self) -> dict:
        self.ensure_one()
        return {
            "name": self.name or "",
            "description": self.description or "",
            "stage_id": self.stage_id.id if self.stage_id else False,
            "user_ids": self.user_ids.ids,
            "date_deadline": self.date_deadline,
            "parent_id": self.parent_id.id if self.parent_id else False,
            "priority": self.priority or "",
        }

    @api.model
    def _op_description_to_odoo(self, raw: str) -> str:
        """Conservative v1: store plain text; escape HTML lightly."""
        text = raw or ""
        text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        text = text.replace("\n", "<br/>")
        return text

    @api.model
    def _op_description_from_odoo(self, html: str) -> str:
        """Conservative v1: strip tags to plain text for OP raw."""
        if not html:
            return ""
        text = re.sub(r"<br\s*/?>", "\n", html, flags=re.I)
        text = re.sub(r"</p\s*>", "\n", text, flags=re.I)
        text = re.sub(r"<[^>]+>", "", text)
        text = (
            text.replace("&lt;", "<")
            .replace("&gt;", ">")
            .replace("&amp;", "&")
            .replace("&nbsp;", " ")
        )
        return text.strip()

    # ------------------------------------------------------------------
    # Mapping helpers
    # ------------------------------------------------------------------
    @api.model
    def _op_resolve_stage(self, project_map, wp: dict) -> tuple:
        """Return (stage_id or False, warning_count)."""
        status_id = OpenProjectClient.wp_link_id(wp, "status")
        if not status_id:
            return False, 0
        smap = self.env["openproject.status.map"].search(
            [
                ("backend_id", "=", project_map.backend_id.id),
                ("op_status_id", "=", status_id),
                ("active", "=", True),
            ],
            limit=1,
        )
        if smap and smap.odoo_stage_id:
            return smap.odoo_stage_id.id, 0
        self.env["openproject.sync.log"].log(
            name=f"Unmapped status {status_id}",
            operation="warning",
            direction="inbound",
            state="warning",
            message=_("OP status %s not mapped; stage left unchanged") % status_id,
            backend=project_map.backend_id,
            project_map=project_map,
            op_work_package_id=wp.get("id"),
        )
        return False, 1

    @api.model
    def _op_resolve_assignee(self, project_map, wp: dict) -> tuple:
        """Return (user recordset, warning_count). Never auto-create users."""
        User = self.env["res.users"]
        assignee_id = OpenProjectClient.wp_link_id(wp, "assignee")
        if not assignee_id:
            return User, 0

        umap = self.env["openproject.user.map"].search(
            [
                ("backend_id", "=", project_map.backend_id.id),
                ("op_user_id", "=", assignee_id),
                ("active", "=", True),
            ],
            limit=1,
        )
        if umap and umap.odoo_user_id:
            return umap.odoo_user_id, 0

        # Try email from embedded or fetch
        email = (umap.op_user_email if umap else "") or ""
        if not email:
            links = (wp.get("_links") or {}).get("assignee") or {}
            title = links.get("title") or ""
            # Best-effort: if title looks like email
            if "@" in title:
                email = title.strip()

        if email:
            user = User.search(
                ["|", ("login", "=ilike", email), ("email", "=ilike", email)],
                limit=1,
            )
            if user:
                return user, 0

        self.env["openproject.sync.log"].log(
            name=f"Unmapped assignee {assignee_id}",
            operation="warning",
            direction="inbound",
            state="warning",
            message=_("OP user %s not mapped; assignee left empty") % assignee_id,
            backend=project_map.backend_id,
            project_map=project_map,
            op_work_package_id=wp.get("id"),
        )
        return User, 1

    @api.model
    def _op_priority_from_wp(self, wp: dict) -> str:
        pid = OpenProjectClient.wp_link_id(wp, "priority")
        return _PRIORITY_OP_TO_ODOO.get(pid or 0, "1")

    @api.model
    def _op_parse_date(self, value):
        if not value:
            return False
        # OP dueDate is often YYYY-MM-DD
        try:
            return fields.Date.to_date(str(value)[:10])
        except Exception:
            return False

    @api.model
    def _op_owner_map_for_wp(self, backend, real_op_project_id: int, fallback_map):
        """Resolve active project map for the WP's real OpenProject project."""
        if not real_op_project_id:
            return fallback_map
        found = self.env["openproject.project.map"].search(
            [
                ("backend_id", "=", backend.id),
                ("op_project_id", "=", real_op_project_id),
                ("active", "=", True),
            ],
            limit=1,
        )
        return found or fallback_map

    @api.model
    def _op_parent_metadata_from_wp(self, wp: dict) -> dict:
        parent_wp_id = OpenProjectClient.wp_link_id(wp, "parent")
        if not parent_wp_id:
            return {
                "op_parent_work_package_id": False,
                "op_parent_subject": False,
                "op_parent_op_project_id": False,
                "op_cross_project_parent": False,
            }
        links = (wp.get("_links") or {}).get("parent") or {}
        return {
            "op_parent_work_package_id": parent_wp_id,
            "op_parent_subject": links.get("title") or False,
            "op_parent_op_project_id": False,
            "op_cross_project_parent": False,
        }

    def _op_stage_vals_for_project_move(self, target_project):
        self.ensure_one()
        if not self.stage_id:
            return {}
        Stage = self.env["project.task.type"]
        current = self.stage_id
        if target_project in current.project_ids:
            return {}
        match = Stage.search(
            [
                ("project_ids", "in", target_project.id),
                ("name", "=ilike", current.name),
            ],
            limit=1,
        )
        if match:
            return {"stage_id": match.id}
        default_stage = target_project.type_ids[:1]
        if default_stage:
            return {"stage_id": default_stage.id}
        return {}

    def _op_stage_move_note(self, source_project, target_project):
        self.ensure_one()
        if not self.stage_id:
            return ""
        vals = self._op_stage_vals_for_project_move(target_project)
        if not vals:
            return _("Stage '%s' kept (valid on target project)") % self.stage_id.name
        new_stage = self.env["project.task.type"].browse(vals["stage_id"])
        return _("Stage '%s' → '%s'") % (self.stage_id.name, new_stage.name)

    @api.model
    def _op_parent_link_plan(self, parent_wp_id: int | bool, backend, owner_map):
        """Return how to apply OP parent on this Odoo task (same vs cross-project)."""
        Task = self.env["project.task"]
        if not parent_wp_id:
            return {
                "parent_action": "none",
                "parent_task": Task.browse(),
                "note": "",
            }
        parent_task = Task.search(
            [
                ("op_backend_id", "=", backend.id),
                ("op_work_package_id", "=", parent_wp_id),
            ],
            limit=1,
        )
        if not parent_task:
            return {
                "parent_action": "none",
                "parent_task": Task.browse(),
                "note": _("Parent WP %s not synced yet") % parent_wp_id,
            }
        child_project = owner_map.odoo_project_id
        if parent_task.project_id == child_project:
            return {
                "parent_action": "set",
                "parent_task": parent_task,
                "note": _("Same-project parent"),
            }
        return {
            "parent_action": "metadata_only",
            "parent_task": parent_task,
            "note": _(
                "Cross-project parent WP %(wp)s in %(proj)s — metadata only"
            )
            % {
                "wp": parent_wp_id,
                "proj": parent_task.project_id.display_name,
            },
        }

    def _op_apply_parent_link(self, parent_wp_id: int | bool, owner_map, wp: dict | None = None):
        """Apply parent relationship after project ownership is known."""
        self.ensure_one()
        backend = owner_map.backend_id
        meta = self._op_parent_metadata_from_wp(wp or {})
        if parent_wp_id:
            meta["op_parent_work_package_id"] = parent_wp_id
        if parent_wp_id and not meta.get("op_parent_subject"):
            parent_task = self.search(
                [
                    ("op_backend_id", "=", backend.id),
                    ("op_work_package_id", "=", parent_wp_id),
                ],
                limit=1,
            )
            if parent_task:
                meta["op_parent_subject"] = parent_task.name
                meta["op_parent_op_project_id"] = parent_task.op_project_id or False

        plan = self._op_parent_link_plan(parent_wp_id, backend, owner_map)
        parent_task = plan.get("parent_task")
        if parent_task and parent_task.op_project_id:
            meta["op_parent_op_project_id"] = parent_task.op_project_id
        meta["op_cross_project_parent"] = bool(
            parent_wp_id
            and parent_task
            and owner_map.odoo_project_id
            and parent_task.project_id != owner_map.odoo_project_id
        )

        vals = dict(meta)
        if plan["parent_action"] == "set" and parent_task:
            vals["parent_id"] = parent_task.id
        elif plan["parent_action"] in ("metadata_only", "clear_cross") and self.parent_id:
            if self.parent_id.project_id != self.project_id:
                vals["parent_id"] = False
        self.with_context(op_syncing=True).write(vals)
        return plan

    # ------------------------------------------------------------------
    # Pull upsert
    # ------------------------------------------------------------------
    @api.model
    def _op_upsert_from_wp(self, project_map, wp: dict, resolve_parent: bool = False):
        """Create/update task from OP WP. Returns (task, created, parent_wp_id, warnings).

        Ownership uses the WP's real ``_links.project`` (not the map being pulled),
        so the same WP listed under multiple OP project endpoints does not thrash
        between Odoo projects.
        """
        backend = project_map.backend_id
        wp_id = int(wp.get("id") or 0)
        if not wp_id:
            raise UserError(_("Work package missing id"))

        # Resolve owning OP project from the WP payload (authoritative).
        real_op_project_id = OpenProjectClient.wp_link_id(wp, "project") or project_map.op_project_id
        owner_map = self._op_owner_map_for_wp(backend, real_op_project_id, project_map)
        if owner_map.op_is_company_folder:
            self.env["openproject.sync.log"].log(
                name=f"Skip WP {wp_id} (company folder)",
                operation="skip",
                direction="inbound",
                state="warning",
                message=_("WP project %s is a company folder; skipped") % real_op_project_id,
                backend=backend,
                project_map=project_map,
                op_work_package_id=wp_id,
            )
            return self.browse(), False, None, 1
        if owner_map.op_project_id != real_op_project_id:
            self.env["openproject.sync.log"].log(
                name=f"Skip WP {wp_id} (project {real_op_project_id})",
                operation="skip",
                direction="inbound",
                state="warning",
                message=_(
                    "WP belongs to OP project %s which has no active map; skipped"
                )
                % real_op_project_id,
                backend=backend,
                project_map=project_map,
                op_work_package_id=wp_id,
            )
            return self.browse(), False, None, 1

        if not owner_map.odoo_project_id:
            owner_map._ensure_odoo_project()
        if not owner_map.odoo_project_id:
            return self.browse(), False, None, 1

        existing = self.search(
            [
                ("op_backend_id", "=", backend.id),
                ("op_work_package_id", "=", wp_id),
            ],
            limit=1,
        )

        raw_desc = OpenProjectClient.wp_description_raw(wp)
        stage_id, w1 = self._op_resolve_stage(owner_map, wp)
        users, w2 = self._op_resolve_assignee(owner_map, wp)
        warnings = w1 + w2
        parent_wp_id = OpenProjectClient.wp_link_id(wp, "parent")
        parent_meta = self._op_parent_metadata_from_wp(wp)
        if parent_wp_id:
            parent_links = (wp.get("_links") or {}).get("parent") or {}
            parent_meta["op_parent_subject"] = parent_links.get("title") or parent_meta.get(
                "op_parent_subject"
            )

        vals = {
            "name": (wp.get("subject") or f"WP {wp_id}")[:255],
            "description": self._op_description_to_odoo(raw_desc),
            "op_description_raw": raw_desc,
            "date_deadline": self._op_parse_date(wp.get("dueDate")),
            "priority": self._op_priority_from_wp(wp),
            "project_id": owner_map.odoo_project_id.id,
            "op_backend_id": backend.id,
            "op_project_id": real_op_project_id,
            "op_project_name": owner_map.op_project_name or False,
            "op_work_package_id": wp_id,
            "op_lock_version": wp.get("lockVersion") or 0,
            "op_url": backend.work_package_url(wp_id),
            "op_last_sync": fields.Datetime.now(),
            "op_sync_state": "synced",
            "op_last_error": False,
            **parent_meta,
        }
        if stage_id:
            vals["stage_id"] = stage_id
        if users:
            vals["user_ids"] = [(6, 0, users.ids)]
        elif not existing:
            vals["user_ids"] = [(5, 0, 0)]

        if resolve_parent and parent_wp_id:
            parent = self._op_find_or_fetch_parent(owner_map, parent_wp_id)
            plan = self._op_parent_link_plan(parent_wp_id, backend, owner_map)
            if plan["parent_action"] == "set" and parent:
                vals["parent_id"] = parent.id
            elif plan["parent_action"] == "metadata_only":
                vals["parent_id"] = False
            vals["op_cross_project_parent"] = plan["parent_action"] == "metadata_only"
            if parent:
                vals["op_parent_op_project_id"] = parent.op_project_id or False

        hash_vals = {
            "name": vals["name"],
            "description": vals.get("description") or "",
            "stage_id": vals.get("stage_id")
            or (existing.stage_id.id if existing and existing.stage_id else False),
            "user_ids": users.ids if users else (existing.user_ids.ids if existing else []),
            "date_deadline": vals.get("date_deadline"),
            "parent_id": vals.get("parent_id")
            or (existing.parent_id.id if existing and existing.parent_id else False),
            "priority": vals.get("priority") or "",
        }
        vals["op_sync_hash"] = self._op_compute_sync_hash(hash_vals)

        if existing:
            write_vals = self._op_inbound_write_vals_for_existing(existing, vals, raw_desc)
            # Always recompute hash from the would-be state (stage rematch updates hash)
            hash_vals["stage_id"] = write_vals.get(
                "stage_id", existing.stage_id.id if existing.stage_id else False
            )
            hash_vals["name"] = write_vals.get("name", existing.name)
            hash_vals["description"] = write_vals.get(
                "description", existing.description or ""
            )
            hash_vals["parent_id"] = write_vals.get(
                "parent_id",
                existing.parent_id.id if existing.parent_id else False,
            )
            hash_vals["priority"] = write_vals.get("priority", existing.priority or "")
            hash_vals["date_deadline"] = write_vals.get(
                "date_deadline", existing.date_deadline
            )
            if "user_ids" in write_vals:
                # [(6, 0, ids)]
                cmds = write_vals["user_ids"]
                hash_vals["user_ids"] = cmds[0][2] if cmds else []
            else:
                hash_vals["user_ids"] = existing.user_ids.ids
            write_vals["op_sync_hash"] = self._op_compute_sync_hash(hash_vals)
            existing.with_context(op_syncing=True).write(write_vals)
            return existing, False, parent_wp_id, warnings

        task = self.with_context(op_syncing=True).create(vals)
        return task, True, parent_wp_id, warnings

    @api.model
    def _op_inbound_write_vals_for_existing(self, existing, vals: dict, raw_desc: str) -> dict:
        """Build inbound write values for an existing task.

        Always re-applies mapped ``stage_id`` when it differs from the current
        stage (Status Mapping may change without an OP payload / hash change).
        Leaves name, description, parent, and project unchanged when content
        already matches OpenProject — prevents HTML thrash on remap pulls.
        """
        write_vals = {
            "op_lock_version": vals.get("op_lock_version"),
            "op_url": vals.get("op_url"),
            "op_last_sync": vals.get("op_last_sync"),
            "op_sync_state": vals.get("op_sync_state"),
            "op_last_error": vals.get("op_last_error"),
            "op_backend_id": vals.get("op_backend_id"),
            "op_work_package_id": vals.get("op_work_package_id"),
            "op_project_id": vals.get("op_project_id"),
            "op_project_name": vals.get("op_project_name"),
        }
        for meta in (
            "op_parent_work_package_id",
            "op_parent_subject",
            "op_parent_op_project_id",
            "op_cross_project_parent",
        ):
            if meta in vals:
                write_vals[meta] = vals[meta]

        # Stage rematch: status map is authoritative even when WP unchanged
        mapped_stage = vals.get("stage_id")
        if mapped_stage and (not existing.stage_id or existing.stage_id.id != mapped_stage):
            write_vals["stage_id"] = mapped_stage

        if vals.get("name") and existing.name != vals["name"]:
            write_vals["name"] = vals["name"]

        if (existing.op_description_raw or "") != (raw_desc or ""):
            write_vals["description"] = vals.get("description") or ""
            write_vals["op_description_raw"] = raw_desc

        if vals.get("project_id") and existing.project_id.id != vals["project_id"]:
            write_vals["project_id"] = vals["project_id"]

        if "parent_id" in vals:
            new_parent = vals.get("parent_id") or False
            cur_parent = existing.parent_id.id if existing.parent_id else False
            if new_parent != cur_parent:
                write_vals["parent_id"] = new_parent

        if "date_deadline" in vals and vals.get("date_deadline") != existing.date_deadline:
            write_vals["date_deadline"] = vals.get("date_deadline")
        if "priority" in vals and (vals.get("priority") or "") != (existing.priority or ""):
            write_vals["priority"] = vals.get("priority")
        if "user_ids" in vals:
            write_vals["user_ids"] = vals["user_ids"]

        return write_vals

    @api.model
    def _op_find_or_fetch_parent(self, project_map, parent_wp_id: int):
        backend = project_map.backend_id
        parent = self.search(
            [
                ("op_backend_id", "=", backend.id),
                ("op_work_package_id", "=", parent_wp_id),
            ],
            limit=1,
        )
        if parent:
            return parent

        # Fetch if parent belongs to a mapped project
        try:
            wp = backend._get_client().get_work_package(parent_wp_id)
        except OpenProjectAPIError as e:
            _logger.warning("Cannot fetch parent WP %s: %s", parent_wp_id, e)
            return self.browse()

        parent_project_id = OpenProjectClient.wp_link_id(wp, "project")
        pmap = self.env["openproject.project.map"].search(
            [
                ("backend_id", "=", backend.id),
                ("op_project_id", "=", parent_project_id or 0),
                ("active", "=", True),
            ],
            limit=1,
        )
        if not pmap:
            # Same map project?
            if parent_project_id == project_map.op_project_id:
                pmap = project_map
            else:
                return self.browse()

        if not pmap.odoo_project_id and not pmap.auto_create_project:
            return self.browse()
        pmap._ensure_odoo_project()
        parent, _created, _p, _w = self._op_upsert_from_wp(
            pmap, wp, resolve_parent=False
        )
        return parent

    # ------------------------------------------------------------------
    # Push create / update
    # ------------------------------------------------------------------
    def _op_get_project_map(self):
        self.ensure_one()
        if not self.project_id:
            return self.env["openproject.project.map"]
        domain = [
            ("odoo_project_id", "=", self.project_id.id),
            ("active", "=", True),
        ]
        if self.op_backend_id:
            domain.append(("backend_id", "=", self.op_backend_id.id))
        return self.env["openproject.project.map"].search(domain, limit=1)

    def _op_can_push_create(self) -> bool:
        self.ensure_one()
        if self.env.context.get("op_syncing"):
            return False
        if self.op_work_package_id:
            return False
        pmap = self._op_get_project_map()
        if not pmap:
            return False
        backend = pmap.backend_id
        if not backend.enable_push or not pmap.op_push_create:
            return False
        return True

    def _op_can_push_update(self, changed: set) -> bool:
        self.ensure_one()
        if self.env.context.get("op_syncing"):
            return False
        if not self.op_work_package_id or not self.op_backend_id:
            return False
        if not self.op_backend_id.enable_push:
            return False
        if not (changed & SYNC_FIELDS):
            return False
        return True

    def _op_build_create_body(self, project_map) -> dict:
        self.ensure_one()
        backend = project_map.backend_id
        raw = self.op_description_raw or self._op_description_from_odoo(self.description or "")
        body = {
            "subject": (self.name or "Task")[:255],
            "description": {"raw": raw, "format": "markdown"},
            "_links": {
                "project": {"href": f"/api/v3/projects/{project_map.op_project_id}"},
                "type": {"href": backend.default_type_href or "/api/v3/types/1"},
                "priority": {
                    "href": f"/api/v3/priorities/{_PRIORITY_ODOO_TO_OP.get(self.priority or '1', 8)}"
                },
            },
        }
        if self.date_deadline:
            body["dueDate"] = fields.Date.to_string(self.date_deadline)
        if self.parent_id and self.parent_id.op_work_package_id:
            body["_links"]["parent"] = {
                "href": f"/api/v3/work_packages/{self.parent_id.op_work_package_id}"
            }
        status_href = self._op_status_href_for_stage(project_map)
        if status_href:
            body["_links"]["status"] = {"href": status_href}
        assignee_href = self._op_assignee_href(project_map)
        if assignee_href:
            body["_links"]["assignee"] = {"href": assignee_href}
        return body

    def _op_build_patch_body(self, project_map) -> dict:
        self.ensure_one()
        raw = self.op_description_raw or self._op_description_from_odoo(self.description or "")
        body = {
            "lockVersion": self.op_lock_version or 0,
            "subject": (self.name or "Task")[:255],
            "description": {"raw": raw, "format": "markdown"},
            "_links": {
                "priority": {
                    "href": f"/api/v3/priorities/{_PRIORITY_ODOO_TO_OP.get(self.priority or '1', 8)}"
                },
            },
        }
        if self.date_deadline:
            body["dueDate"] = fields.Date.to_string(self.date_deadline)
        else:
            body["dueDate"] = None
        if self.parent_id and self.parent_id.op_work_package_id:
            body["_links"]["parent"] = {
                "href": f"/api/v3/work_packages/{self.parent_id.op_work_package_id}"
            }
        else:
            body["_links"]["parent"] = {"href": None}
        status_href = self._op_status_href_for_stage(project_map)
        if status_href:
            body["_links"]["status"] = {"href": status_href}
        assignee_href = self._op_assignee_href(project_map)
        if assignee_href:
            body["_links"]["assignee"] = {"href": assignee_href}
        else:
            body["_links"]["assignee"] = {"href": None}
        return body

    def _op_status_href_for_stage(self, project_map) -> str | None:
        self.ensure_one()
        if not self.stage_id:
            return None
        smap = self.env["openproject.status.map"].search(
            [
                ("backend_id", "=", project_map.backend_id.id),
                ("odoo_stage_id", "=", self.stage_id.id),
                ("active", "=", True),
            ],
            limit=1,
        )
        if not smap:
            return None
        if smap.op_status_href:
            return smap.op_status_href
        if smap.op_status_id:
            return f"/api/v3/statuses/{smap.op_status_id}"
        return None

    def _op_assignee_href(self, project_map) -> str | None:
        self.ensure_one()
        user = self.user_ids[:1]
        if not user:
            return None
        umap = self.env["openproject.user.map"].search(
            [
                ("backend_id", "=", project_map.backend_id.id),
                ("odoo_user_id", "=", user.id),
                ("active", "=", True),
            ],
            limit=1,
        )
        if umap and umap.op_user_id:
            return f"/api/v3/users/{umap.op_user_id}"
        return None

    def _op_push_create(self):
        self.ensure_one()
        Log = self.env["openproject.sync.log"]
        if not self._op_can_push_create():
            return
        pmap = self._op_get_project_map()
        backend = pmap.backend_id
        client = backend._get_client()
        try:
            wp = client.create_work_package(self._op_build_create_body(pmap))
            wp_id = int(wp.get("id"))
            sync_vals = self._op_current_sync_vals()
            self.with_context(op_syncing=True).write(
                {
                    "op_backend_id": backend.id,
                    "op_project_id": pmap.op_project_id,
                    "op_work_package_id": wp_id,
                    "op_lock_version": wp.get("lockVersion") or 0,
                    "op_url": backend.work_package_url(wp_id),
                    "op_last_sync": fields.Datetime.now(),
                    "op_sync_hash": self._op_compute_sync_hash(sync_vals),
                    "op_sync_state": "synced",
                    "op_last_error": False,
                    "op_description_raw": OpenProjectClient.wp_description_raw(wp)
                    or self.op_description_raw,
                }
            )
            Log.log(
                name=f"Push Create WP {wp_id}",
                operation="create",
                direction="outbound",
                state="ok",
                message=self.name,
                backend=backend,
                project_map=pmap,
                task=self,
                op_work_package_id=wp_id,
            )
        except Exception as e:
            self.with_context(op_syncing=True).write(
                {
                    "op_sync_state": "error",
                    "op_last_error": str(e),
                }
            )
            Log.log(
                name="Push Create Failed",
                operation="error",
                direction="outbound",
                state="error",
                message=str(e),
                backend=backend,
                project_map=pmap,
                task=self,
            )
            _logger.exception("OP push create failed for task %s", self.id)

    def _op_push_update(self):
        self.ensure_one()
        Log = self.env["openproject.sync.log"]
        pmap = self._op_get_project_map()
        if not pmap:
            Log.log(
                name="Push Update Skipped (no map)",
                operation="skip",
                direction="outbound",
                state="warning",
                message=_("No active project map"),
                task=self,
                op_work_package_id=self.op_work_package_id,
            )
            return

        backend = self.op_backend_id or pmap.backend_id
        if not backend.enable_push:
            return

        new_hash = self._op_compute_sync_hash(self._op_current_sync_vals())
        if new_hash == (self.op_sync_hash or ""):
            Log.log(
                name="Push Update Skipped (hash unchanged)",
                operation="skip",
                direction="outbound",
                state="ok",
                message=self.name,
                backend=backend,
                project_map=pmap,
                task=self,
                op_work_package_id=self.op_work_package_id,
            )
            return

        client = backend._get_client()
        try:
            wp = client.update_work_package(
                self.op_work_package_id, self._op_build_patch_body(pmap)
            )
            self.with_context(op_syncing=True).write(
                {
                    "op_lock_version": wp.get("lockVersion") or self.op_lock_version,
                    "op_last_sync": fields.Datetime.now(),
                    "op_sync_hash": new_hash,
                    "op_sync_state": "synced",
                    "op_last_error": False,
                    "op_url": backend.work_package_url(self.op_work_package_id),
                    "op_description_raw": OpenProjectClient.wp_description_raw(wp)
                    or self.op_description_raw,
                }
            )
            Log.log(
                name=f"Push Update WP {self.op_work_package_id}",
                operation="update",
                direction="outbound",
                state="ok",
                message=self.name,
                backend=backend,
                project_map=pmap,
                task=self,
                op_work_package_id=self.op_work_package_id,
            )
        except OpenProjectAPIError as e:
            if e.is_conflict:
                self._op_handle_conflict(pmap, e)
            else:
                self.with_context(op_syncing=True).write(
                    {
                        "op_sync_state": "error",
                        "op_last_error": str(e),
                    }
                )
                Log.log(
                    name="Push Update Failed",
                    operation="error",
                    direction="outbound",
                    state="error",
                    message=str(e),
                    details=e.body,
                    backend=backend,
                    project_map=pmap,
                    task=self,
                    op_work_package_id=self.op_work_package_id,
                )
        except Exception as e:
            self.with_context(op_syncing=True).write(
                {
                    "op_sync_state": "error",
                    "op_last_error": str(e),
                }
            )
            Log.log(
                name="Push Update Failed",
                operation="error",
                direction="outbound",
                state="error",
                message=str(e),
                backend=backend,
                project_map=pmap,
                task=self,
                op_work_package_id=self.op_work_package_id,
            )

    def _op_handle_conflict(self, project_map, error: OpenProjectAPIError):
        """v1: OpenProject wins — re-fetch and apply remote."""
        self.ensure_one()
        Log = self.env["openproject.sync.log"]
        backend = project_map.backend_id
        try:
            wp = backend._get_client().get_work_package(self.op_work_package_id)
            self._op_upsert_from_wp(project_map, wp, resolve_parent=True)
            self.with_context(op_syncing=True).write(
                {
                    "op_sync_state": "conflict",
                    "op_last_error": _(
                        "409 conflict on PATCH; remote OpenProject state applied. %s"
                    )
                    % str(error),
                }
            )
            Log.log(
                name=f"Conflict WP {self.op_work_package_id}",
                operation="conflict",
                direction="outbound",
                state="conflict",
                message=_("OpenProject wins; remote state applied to Odoo"),
                details=str(error),
                backend=backend,
                project_map=project_map,
                task=self,
                op_work_package_id=self.op_work_package_id,
            )
        except Exception as e:
            self.with_context(op_syncing=True).write(
                {
                    "op_sync_state": "conflict",
                    "op_last_error": f"409 conflict; re-fetch failed: {e}",
                }
            )
            Log.log(
                name="Conflict handling failed",
                operation="conflict",
                direction="outbound",
                state="error",
                message=str(e),
                backend=backend,
                project_map=project_map,
                task=self,
                op_work_package_id=self.op_work_package_id,
            )

    # ------------------------------------------------------------------
    # ORM hooks
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        tasks = super().create(vals_list)
        for task in tasks:
            if task._op_can_push_create():
                task._op_push_create()
        return tasks

    def write(self, vals):
        changed = set(vals.keys())
        res = super().write(vals)
        if self.env.context.get("op_syncing"):
            return res
        for task in self:
            if task._op_can_push_update(changed):
                task._op_push_update()
            elif task._op_can_push_create():
                # Task gained a mapped project after create, or push flags flipped
                task._op_push_create()
        return res
