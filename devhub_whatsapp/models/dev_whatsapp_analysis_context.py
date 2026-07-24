# -*- coding: utf-8 -*-
"""Project-scoped context package for WhatsApp AI technical analysis."""
from __future__ import annotations

from odoo import api, fields, models


class DevWhatsappAnalysisContext(models.AbstractModel):
    _name = "dev.whatsapp.analysis.context"
    _description = "WhatsApp AI project-scoped context builder"

    @api.model
    def build_project_context(self, project, messages, work_item_candidates=None, max_chars=12000):
        """Compact, traceable context. Never invents facts."""
        if not project:
            return {
                "project_summary": {},
                "evidence": [],
                "truncated": False,
                "char_count": 0,
            }
        evidence = []
        summary = {
            "project_id": project.id,
            "project_name": project.name,
            "project_code": project.code,
            "aliases": project.alias_ids.filtered("active").mapped("name")[:20],
            "openproject_reference": project.openproject_reference or False,
            "github_reference": project.github_reference or False,
            "agent_instruction_summary": (project.agent_instruction_summary or "")[:800],
        }
        evidence.append(
            {
                "source_type": "project_config",
                "reference": "dev.project:%s" % project.id,
                "summary": "Canonical project %s (%s)" % (project.name, project.code),
                "evidence_status": "confirmed",
                "project_id": project.id,
                "freshness": fields.Datetime.to_string(fields.Datetime.now()),
            }
        )

        repo = project.default_repository_id
        if repo:
            summary["repository"] = {
                "id": repo.id,
                "name": repo.name,
                "working_directory": repo.working_directory or False,
                "branch": getattr(repo, "current_branch_cache", None)
                or getattr(repo, "default_branch", None)
                or False,
            }
            evidence.append(
                {
                    "source_type": "code",
                    "reference": "dev.repository:%s" % repo.id,
                    "summary": "Default repository %s" % (repo.name or repo.id),
                    "evidence_status": "confirmed",
                    "project_id": project.id,
                    "freshness": fields.Datetime.to_string(fields.Datetime.now()),
                }
            )

        env = project.default_environment_id
        if env:
            summary["environment"] = {
                "id": env.id,
                "name": env.name,
                "environment_type": env.environment_type,
                "database_identifier": getattr(env, "database_identifier", False) or False,
                "url": env.url or False,
                "is_production": bool(getattr(env, "is_production", False)),
            }
            evidence.append(
                {
                    "source_type": "database",
                    "reference": "dev.environment:%s" % env.id,
                    "summary": "Default environment %s (%s)"
                    % (env.name, env.environment_type),
                    "evidence_status": "confirmed",
                    "project_id": project.id,
                    "freshness": fields.Datetime.to_string(fields.Datetime.now()),
                }
            )

        modules = []
        for r in project.repository_ids[:5]:
            modules.append({"repository_id": r.id, "name": r.name})
        summary["repositories"] = modules

        wi_brief = []
        for cand in (work_item_candidates or [])[:8]:
            wi_brief.append(
                {
                    "work_item_id": cand.get("work_item_id"),
                    "title": cand.get("title"),
                    "phase": cand.get("phase"),
                }
            )
            evidence.append(
                {
                    "source_type": "work_item",
                    "reference": "dev.work.item:%s" % cand.get("work_item_id"),
                    "summary": cand.get("title") or "",
                    "evidence_status": "confirmed",
                    "project_id": project.id,
                    "freshness": fields.Datetime.to_string(fields.Datetime.now()),
                }
            )
        summary["work_item_candidates_brief"] = wi_brief

        # Prior approved WA analyses for this project
        Analysis = self.env["dev.whatsapp.analysis"].sudo()
        prior = Analysis.search(
            [
                ("dev_project_id", "=", project.id),
                ("state", "in", ("applied", "awaiting_review", "succeeded")),
            ],
            order="id desc",
            limit=3,
        )
        prior_rows = []
        for a in prior:
            prior_rows.append(
                {
                    "analysis_id": a.id,
                    "summary": (a.summary or "")[:200],
                    "classification": a.classification,
                    "state": a.state,
                }
            )
            evidence.append(
                {
                    "source_type": "document",
                    "reference": "dev.whatsapp.analysis:%s" % a.id,
                    "summary": (a.summary or "")[:160],
                    "evidence_status": "inferred",
                    "project_id": project.id,
                    "freshness": fields.Datetime.to_string(a.completed_at or a.requested_at),
                }
            )
        summary["prior_analyses"] = prior_rows

        package = {
            "project_summary": summary,
            "evidence": evidence,
            "evidence_hierarchy_note": (
                "Priority: code/DB > project config > work items/analyses > "
                "docs > WhatsApp > Dify KB > general model knowledge. "
                "Do not present general knowledge as confirmed project evidence."
            ),
            "message_excerpt": [
                {
                    "id": m.id,
                    "body": (m.body or "")[:400],
                    "sender_jid": m.sender_jid,
                    "timestamp": fields.Datetime.to_string(m.message_timestamp)
                    if m.message_timestamp
                    else False,
                }
                for m in messages[:12]
            ],
        }
        import json

        raw = json.dumps(package, ensure_ascii=False, default=str)
        truncated = False
        if len(raw) > max_chars:
            truncated = True
            package["message_excerpt"] = package["message_excerpt"][:6]
            package["evidence"] = package["evidence"][:12]
            package["project_summary"]["prior_analyses"] = prior_rows[:1]
            raw = json.dumps(package, ensure_ascii=False, default=str)
        package["truncated"] = truncated
        package["char_count"] = len(raw)
        return package
