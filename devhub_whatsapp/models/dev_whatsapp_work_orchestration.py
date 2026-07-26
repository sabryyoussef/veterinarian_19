# -*- coding: utf-8 -*-
"""Pre-create work orchestration / dedup decisions for WhatsApp AI analyses."""
from __future__ import annotations

import json
import logging

from odoo import api, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class DevWhatsappWorkOrchestration(models.AbstractModel):
    _name = "dev.whatsapp.work.orchestration"
    _description = "WhatsApp Work Orchestration"

    @api.model
    def evaluate_before_create(self, analysis):
        """Return a decision dict and persist it on analysis.work_orchestration_json.

        Decisions:
        update_existing | create_child | create_one | create_multiple |
        request_review | ignore
        """
        analysis.ensure_one()
        source = analysis.source_id
        title = (analysis.work_title or "").strip()
        messages = analysis.work_message_ids or analysis.batch_message_ids
        project = analysis.resolved_project_id or analysis.dev_project_id

        # Review-only / ICP: never auto-create OpenProject
        icp = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("devhub_whatsapp.analysis_review_only", "False")
        )
        review_only = bool(source.analysis_review_only) or str(icp).lower() in (
            "1",
            "true",
            "yes",
        )
        op_create_allowed = bool(source.openproject_create_allowed) and not review_only

        decision = {
            "decision": "create_one",
            "review_only": review_only,
            "openproject_create_allowed": op_create_allowed,
            "dev_work_item_matches": [],
            "project_task_matches": [],
            "openproject_matches": [],
            "op_recommended_parent_id": False,
            "reasons": [],
            "force_allowed": False,
        }

        # Duplicate via already-linked source messages
        linked = messages.mapped("work_item_ids") if messages else self.env["dev.work.item"]
        if linked:
            decision["decision"] = "update_existing"
            decision["dev_work_item_matches"] = [
                {"id": w.id, "name": w.name, "reason": "source_message_link"}
                for w in linked[:10]
            ]
            decision["reasons"].append("messages_already_linked_to_work_item")
            self._persist(analysis, decision)
            return decision

        # Search existing Dev Hub work items by project + title
        Work = self.env["dev.work.item"].sudo()
        wi_matches = Work.browse()
        if project and title:
            domain = [
                ("dev_project_id", "=", project.id),
                ("name", "ilike", title[:80]),
            ]
            wi_matches = Work.search(domain, limit=10)
        # Also search by overlapping source messages
        if messages:
            SourceMsg = self.env["dev.work.source.message"].sudo()
            linked_src = SourceMsg.search(
                [("whatsapp_message_id", "in", messages.ids)]
            )
            wi_matches |= linked_src.mapped("work_item_ids")

        if wi_matches:
            decision["dev_work_item_matches"] = [
                {"id": w.id, "name": w.name, "reason": "title_or_source_overlap"}
                for w in wi_matches[:10]
            ]
            decision["decision"] = "update_existing"
            decision["reasons"].append("dev_work_item_title_or_source_match")

        # project.task when Odoo project is mapped
        Task = self.env["project.task"].sudo()
        odoo_project = source.odoo_project_id
        task_matches = Task.browse()
        if odoo_project and title and "project.task" in self.env:
            task_matches = Task.search(
                [
                    ("project_id", "=", odoo_project.id),
                    ("name", "ilike", title[:80]),
                ],
                limit=10,
            )
        if task_matches:
            decision["project_task_matches"] = [
                {"id": t.id, "name": t.name} for t in task_matches[:10]
            ]
            if decision["decision"] == "create_one":
                decision["decision"] = "request_review"
            decision["reasons"].append("project_task_title_match")

        # OpenProject helpers — only if available; never invent an API
        op_matches = []
        op_parent = False
        try:
            op_matches, op_parent = self._search_openproject(analysis, title)
        except Exception:  # noqa: BLE001 — helpers are optional
            _logger.debug("OpenProject search skipped", exc_info=True)
        decision["openproject_matches"] = op_matches
        decision["op_recommended_parent_id"] = op_parent or False
        if op_matches and decision["decision"] == "create_one":
            decision["decision"] = "request_review"
            decision["reasons"].append("openproject_candidate_match")

        # Multi-item analyses
        items = []
        try:
            items = json.loads(analysis.analysis_items_json or "[]") or []
        except (TypeError, ValueError, json.JSONDecodeError):
            items = []
        if len(items) > 1 and decision["decision"] == "create_one":
            decision["decision"] = "create_multiple"
            decision["reasons"].append("multiple_analysis_items")

        if review_only and decision["decision"] in (
            "create_one",
            "create_multiple",
            "create_child",
        ):
            decision["decision"] = "request_review"
            decision["reasons"].append("analysis_review_only")

        if not op_create_allowed:
            decision["reasons"].append("openproject_create_blocked")

        self._persist(analysis, decision)
        return decision

    @api.model
    def _search_openproject(self, analysis, title):
        """Best-effort OP search via existing helpers; else empty recommendation."""
        matches = []
        parent_id = False
        # Prefer project.openproject_reference style helpers if present
        project = analysis.resolved_project_id or analysis.dev_project_id
        if project and getattr(project, "openproject_reference", None):
            parent_id = str(project.openproject_reference)

        # Known optional models / helpers in this stack
        for model_name, method_name in (
            ("openproject.backend", "search_work_packages"),
            ("dev.openproject.sync", "search_work_packages"),
            ("devhub.openproject.api", "search_work_packages"),
        ):
            if model_name not in self.env:
                continue
            Model = self.env[model_name].sudo()
            if not hasattr(Model, method_name):
                continue
            try:
                result = getattr(Model, method_name)(title or "", project=project)
            except TypeError:
                try:
                    result = getattr(Model, method_name)(title or "")
                except Exception:  # noqa: BLE001
                    continue
            except Exception:  # noqa: BLE001
                continue
            if isinstance(result, list):
                for row in result[:10]:
                    if isinstance(row, dict):
                        matches.append(row)
                    else:
                        matches.append({"raw": str(row)[:200]})
            elif result:
                matches.append({"raw": str(result)[:200]})
            break
        return matches, parent_id

    @api.model
    def _persist(self, analysis, decision):
        vals = {
            "work_orchestration_json": json.dumps(
                decision, ensure_ascii=False, sort_keys=True, indent=2
            ),
            "op_recommended_parent_id": decision.get("op_recommended_parent_id") or False,
            "op_duplicate_candidates_json": json.dumps(
                decision.get("openproject_matches") or [],
                ensure_ascii=False,
            ),
            "odoo_task_candidates_json": json.dumps(
                decision.get("project_task_matches") or [],
                ensure_ascii=False,
            ),
        }
        analysis.sudo().write(vals)

    @api.model
    def assert_create_allowed(self, analysis, force=False):
        """Raise UserError when duplicate candidates or review-only block create."""
        decision = self.evaluate_before_create(analysis)
        if force and analysis.env.user.has_group("devhub_core.group_dev_hub_manager"):
            decision["force_allowed"] = True
            self._persist(analysis, decision)
            return decision
        if decision.get("review_only") and not force:
            raise UserError(
                "Work orchestration blocked create: analysis_review_only is enabled "
                "for this WhatsApp source (or ICP). No automatic Dev Hub / Odoo / "
                "OpenProject create is allowed. Approve manually after review."
            )
        blocking = decision["decision"] in ("update_existing", "request_review", "ignore")
        has_dupes = bool(
            decision.get("dev_work_item_matches")
            or decision.get("project_task_matches")
            or decision.get("openproject_matches")
        )
        if blocking and has_dupes and not force:
            raise UserError(
                "Work orchestration blocked create: %s. "
                "Duplicate / review candidates exist. "
                "Open the existing Work Item or re-run with manager force context "
                "(context key wa_orchestration_force=True)."
                % decision["decision"]
            )
        return decision
