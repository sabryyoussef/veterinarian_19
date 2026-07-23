# -*- coding: utf-8 -*-
from __future__ import annotations

import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .openproject_api import OpenProjectClient

_logger = logging.getLogger(__name__)


class OpenprojectBackend(models.Model):
    _name = "openproject.backend"
    _description = "OpenProject Backend"
    _order = "sequence, name"

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    api_url = fields.Char(
        string="API Base URL",
        required=True,
        help="OpenProject API base, e.g. http://127.0.0.1:8081 or public HTTPS URL",
    )
    public_url = fields.Char(
        string="Public URL",
        help="Browser URL for work package links, e.g. https://master...:10081",
    )
    api_token = fields.Char(
        string="API Token",
        groups="base.group_system",
        help="OpenProject API key (Basic apikey:TOKEN). Do not commit secrets.",
    )
    host_header = fields.Char(
        string="Host Header",
        help="Optional Host header for reverse-proxy / Tailscale access",
    )
    verify_ssl = fields.Boolean(
        string="Verify SSL",
        default=True,
        help="Disable for internal/Tailscale certs (relaxed mode)",
    )
    enable_pull = fields.Boolean(
        string="Enable Pull",
        default=True,
        help="Allow OpenProject → Odoo pull (cron and Sync Now)",
    )
    enable_push = fields.Boolean(
        string="Enable Push",
        default=False,
        help="Allow Odoo → OpenProject create/update. Keep off until pull is proven.",
    )
    last_pull_at = fields.Datetime(
        string="Last Successful Pull",
        readonly=True,
        help="Updated only after a successful pull batch",
    )
    cron_interval_minutes = fields.Integer(
        string="Cron Interval (minutes)",
        default=15,
        help="Informational; actual schedule is on ir.cron",
    )
    default_type_href = fields.Char(
        string="Default Type Href",
        default="/api/v3/types/1",
        help="Used when creating work packages from Odoo",
    )
    default_priority_href = fields.Char(
        string="Default Priority Href",
        default="/api/v3/priorities/8",
    )

    last_test_date = fields.Datetime(readonly=True)
    last_test_state = fields.Selection(
        [("ok", "OK"), ("failed", "Failed")],
        readonly=True,
    )
    last_test_message = fields.Text(readonly=True)

    project_map_ids = fields.One2many(
        "openproject.project.map",
        "backend_id",
        string="Project Maps",
    )
    status_map_ids = fields.One2many(
        "openproject.status.map",
        "backend_id",
        string="Status Maps",
    )
    user_map_ids = fields.One2many(
        "openproject.user.map",
        "backend_id",
        string="User Maps",
    )
    log_ids = fields.One2many(
        "openproject.sync.log",
        "backend_id",
        string="Sync Logs",
    )
    log_count = fields.Integer(compute="_compute_log_count")

    @api.depends("log_ids")
    def _compute_log_count(self):
        for rec in self:
            rec.log_count = len(rec.log_ids)

    def _get_client(self) -> OpenProjectClient:
        self.ensure_one()
        if not self.api_token:
            raise UserError(_("API Token is required on backend “%s”.") % self.name)
        if not self.api_url:
            raise UserError(_("API Base URL is required on backend “%s”.") % self.name)
        return OpenProjectClient(
            base_url=self.api_url,
            token=self.api_token,
            host_header=self.host_header or "",
            verify_ssl=bool(self.verify_ssl),
        )

    def action_test_connection(self):
        self.ensure_one()
        Log = self.env["openproject.sync.log"]
        try:
            payload = self._get_client().test_connection()
            instance = (payload.get("_type") or "OK")
            msg = _("Connected: %s") % instance
            self.write(
                {
                    "last_test_date": fields.Datetime.now(),
                    "last_test_state": "ok",
                    "last_test_message": msg,
                }
            )
            Log.log(
                name="Test Connection",
                operation="test",
                direction="none",
                state="ok",
                message=msg,
                details=str(payload)[:2000],
                backend=self,
            )
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("OpenProject"),
                    "message": msg,
                    "type": "success",
                    "sticky": False,
                },
            }
        except Exception as e:
            msg = str(e)
            self.write(
                {
                    "last_test_date": fields.Datetime.now(),
                    "last_test_state": "failed",
                    "last_test_message": msg,
                }
            )
            Log.log(
                name="Test Connection Failed",
                operation="test",
                direction="none",
                state="error",
                message=msg,
                backend=self,
            )
            raise UserError(_("Connection failed: %s") % msg) from e

    def action_sync_now(self):
        self.ensure_one()
        if not self.enable_pull:
            raise UserError(_("Pull is disabled on backend “%s”.") % self.name)
        summary = self._pull_all_maps()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("OpenProject Sync"),
                "message": summary,
                "type": "success",
                "sticky": True,
            },
        }

    def action_full_sync_now(self):
        """Pull all mapped projects ignoring watermarks (full resync)."""
        self.ensure_one()
        if not self.enable_pull:
            raise UserError(_("Pull is disabled on backend “%s”.") % self.name)
        summary = self.with_context(op_force_full_pull=True)._pull_all_maps()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("OpenProject Full Sync"),
                "message": summary,
                "type": "success",
                "sticky": True,
            },
        }

    def action_refresh_project_classification(self):
        """Fetch OP project parents and backfill company classification (idempotent)."""
        from .openproject_api import OpenProjectClient
        from .openproject_classification import href_id, load_group_project_map

        updated = 0
        map_data = load_group_project_map()
        for backend in self:
            parent_by_id: dict[int, int | None] = {}
            name_by_id: dict[int, str] = {}
            try:
                client = backend._get_client()
                offset = 1
                while True:
                    payload = client.get(
                        "/api/v3/projects",
                        query={"offset": offset, "pageSize": 100},
                    )
                    elements = (payload.get("_embedded") or {}).get("elements") or []
                    for p in elements:
                        pid = int(p.get("id") or 0)
                        if not pid:
                            continue
                        parent = href_id(((p.get("_links") or {}).get("parent") or {}).get("href"))
                        parent_by_id[pid] = parent
                        name_by_id[pid] = p.get("name") or ""
                    total = payload.get("total") or 0
                    if not elements or offset + len(elements) > total:
                        break
                    offset += 100
            except Exception as e:
                _logger.warning(
                    "OP project list failed for backend %s; classifying from map JSON only: %s",
                    backend.name,
                    e,
                )

            def chain_for(pid: int) -> list[int]:
                out = []
                seen = set()
                cur = parent_by_id.get(pid)
                while cur and cur not in seen:
                    seen.add(cur)
                    out.append(cur)
                    cur = parent_by_id.get(cur)
                return out

            # Include archived/inactive maps (403 projects still need company labels)
            maps = backend.with_context(active_test=False).project_map_ids
            for pmap in maps:
                pid = pmap.op_project_id
                parent = parent_by_id.get(pid)
                # Keep existing parent if API did not return this project
                if pid not in parent_by_id:
                    parent = pmap.op_parent_project_id or None
                if pid in name_by_id and name_by_id[pid] and pmap.op_project_name != name_by_id[pid]:
                    pmap.op_project_name = name_by_id[pid]
                pmap.apply_classification(
                    parent_id=parent,
                    parent_chain=chain_for(pid) if pid in parent_by_id else None,
                    map_data=map_data,
                )
                updated += 1

            self.env["openproject.sync.log"].log(
                name="Classification refresh",
                operation="summary",
                direction="inbound",
                state="ok",
                message=_("Classified %s project maps") % len(maps),
                backend=backend,
            )
        return updated

    def action_refresh_classification_ui(self):
        self.ensure_one()
        n = self.action_refresh_project_classification()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("OpenProject Classification"),
                "message": _("Updated classification on %s project maps") % n,
                "type": "success",
                "sticky": False,
            },
        }

    def action_realign_tasks_wizard(self):
        """Open audit wizard to realign Odoo tasks to OP project ownership (test-safe)."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Realign Tasks to OP Projects"),
            "res_model": "openproject.task.realign.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_backend_id": self.id, "default_dry_run": True},
        }

    def action_open_public_url(self):
        self.ensure_one()
        url = (self.public_url or self.api_url or "").rstrip("/")
        if not url:
            raise UserError(_("No public URL configured."))
        return {
            "type": "ir.actions.act_url",
            "url": url,
            "target": "new",
        }

    def action_view_logs(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Sync Logs"),
            "res_model": "openproject.sync.log",
            "view_mode": "list,form",
            "domain": [("backend_id", "=", self.id)],
            "context": {"default_backend_id": self.id},
        }

    @api.model
    def _cron_pull_all(self):
        backends = self.search([("active", "=", True), ("enable_pull", "=", True)])
        for backend in backends:
            try:
                backend._pull_all_maps()
            except Exception as e:
                _logger.exception("OpenProject pull cron failed for %s", backend.name)
                self.env["openproject.sync.log"].log(
                    name="Cron Pull Failed",
                    operation="error",
                    direction="inbound",
                    state="error",
                    message=str(e),
                    backend=backend,
                )

    def _pull_all_maps(self) -> str:
        self.ensure_one()
        maps = self.project_map_ids.filtered(lambda m: m.active)
        totals = {
            "pulled": 0,
            "created": 0,
            "updated": 0,
            "skipped": 0,
            "warnings": 0,
            "errors": 0,
        }
        for pmap in maps:
            part = pmap.action_pull(raise_on_error=False)
            for key in totals:
                totals[key] += part.get(key, 0)

        summary = _(
            "Pull done — pulled:%(pulled)s created:%(created)s updated:%(updated)s "
            "skipped:%(skipped)s warnings:%(warnings)s errors:%(errors)s"
        ) % totals
        self.env["openproject.sync.log"].log(
            name="Pull Summary",
            operation="summary",
            direction="inbound",
            state="error" if totals["errors"] else ("warning" if totals["warnings"] else "ok"),
            message=summary,
            details=str(totals),
            backend=self,
        )
        return summary

    def work_package_url(self, wp_id: int) -> str:
        self.ensure_one()
        base = (self.public_url or self.api_url or "").rstrip("/")
        if not base or not wp_id:
            return ""
        return f"{base}/work_packages/{int(wp_id)}"
