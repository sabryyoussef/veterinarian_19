# -*- coding: utf-8 -*-
"""Project and Work Item candidate retrieval for WhatsApp AI."""
from __future__ import annotations

from odoo import api, models

from odoo.addons.devhub_work.models.dev_project_alias import normalize_alias


class DevWhatsappAnalysisCandidates(models.AbstractModel):
    _name = "dev.whatsapp.analysis.candidates"
    _description = "WhatsApp AI project/WI candidate builders"

    @api.model
    def build_project_candidates(self, source, messages, limit=8):
        """Rank validated project candidates for Dify selection."""
        Project = self.env["dev.project"].sudo()
        Alias = self.env["dev.project.alias"].sudo()
        scored = {}  # project_id → dict

        def add(project, score, evidence, aliases_matched=None):
            if not project or not project.active:
                return
            entry = scored.setdefault(
                project.id,
                {
                    "project_id": project.id,
                    "project_name": project.name,
                    "project_code": project.code,
                    "aliases_matched": [],
                    "evidence": [],
                    "deterministic_score": 0.0,
                },
            )
            entry["deterministic_score"] = max(entry["deterministic_score"], float(score))
            for ev in evidence or []:
                if ev not in entry["evidence"]:
                    entry["evidence"].append(ev)
            for a in aliases_matched or []:
                if a not in entry["aliases_matched"]:
                    entry["aliases_matched"].append(a)

        # 1) Confirmed source mapping
        if source.dev_project_id and source.project_mapping_state == "confirmed":
            add(
                source.dev_project_id,
                0.98,
                [
                    {
                        "type": "group_mapping",
                        "value": "Confirmed WhatsApp source mapping",
                    }
                ],
            )
        elif source.dev_project_id and source.project_mapping_state == "inferred":
            add(
                source.dev_project_id,
                0.55,
                [{"type": "group_mapping", "value": "Inferred source mapping"}],
            )

        # 2–4) Alias matches in message bodies + group name
        blob = " ".join(
            [(source.name or "")]
            + [(m.body or "")[:500] for m in messages[:20]]
        )
        for alias in Alias.match_text(blob, limit=20):
            add(
                alias.dev_project_id,
                min(0.97, 0.6 + (alias.priority or 0) / 200.0),
                [
                    {
                        "type": "message_alias",
                        "value": "Matched alias %r (%s)" % (alias.name, alias.alias_type),
                    }
                ],
                aliases_matched=[alias.name],
            )

        # 6) Existing WI links on messages
        for msg in messages:
            for work in msg.work_item_ids[:3]:
                if work.dev_project_id:
                    add(
                        work.dev_project_id,
                        0.9,
                        [
                            {
                                "type": "work_item_link",
                                "value": "Message linked to WI %s" % work.id,
                            }
                        ],
                    )

        # Ambiguous / unmapped sources: do not boost source project unless aliases hit
        if source.project_mapping_state in ("ambiguous", "unmapped"):
            if source.dev_project_id and source.dev_project_id.id in scored:
                if scored[source.dev_project_id.id]["deterministic_score"] < 0.7:
                    # demote weak source-only signal
                    scored[source.dev_project_id.id]["deterministic_score"] = min(
                        scored[source.dev_project_id.id]["deterministic_score"], 0.4
                    )

        ranked = sorted(
            scored.values(),
            key=lambda r: r["deterministic_score"],
            reverse=True,
        )[:limit]
        requires_confirmation = False
        if not ranked:
            requires_confirmation = True
        elif ranked[0]["deterministic_score"] < 0.7:
            requires_confirmation = True
        elif len(ranked) > 1 and (
            ranked[0]["deterministic_score"] - ranked[1]["deterministic_score"] < 0.12
        ):
            requires_confirmation = True
        if source.project_mapping_state in ("ambiguous", "unmapped"):
            requires_confirmation = True
        return {
            "project_candidates": ranked,
            "requires_project_confirmation": requires_confirmation,
        }

    @api.model
    def build_work_item_candidates(self, project, messages, limit=8):
        """Rank WI candidates inside the selected project only."""
        if not project:
            return {"work_item_candidates": []}
        Work = self.env["dev.work.item"].sudo()
        terms = set()
        for msg in messages[:20]:
            body = (msg.body or "").lower()
            for token in body.replace("\n", " ").split():
                token = token.strip(".,:;()[]\"'")
                if len(token) >= 4:
                    terms.add(token)
            for work in msg.work_item_ids:
                if work.dev_project_id == project:
                    terms.add(str(work.id))
                    if work.name:
                        terms.add(work.name.lower())

        domain = [("dev_project_id", "=", project.id)]
        recent = Work.search(domain, order="write_date desc, id desc", limit=40)
        scored = []
        for work in recent:
            evidence = ["Same project"]
            matched = []
            score = 0.2
            title = (work.name or "").lower()
            for term in terms:
                if term.isdigit() and int(term) == work.id:
                    score = max(score, 0.99)
                    matched.append(term)
                    evidence.append("Explicit Work Item ID")
                elif term in title:
                    score = max(score, 0.75)
                    matched.append(term)
                    evidence.append("Title term match")
            for msg in messages:
                if work in msg.work_item_ids:
                    score = max(score, 0.95)
                    evidence.append("Shared source message link")
            if score < 0.35 and not matched:
                continue
            scored.append(
                {
                    "work_item_id": work.id,
                    "title": work.name,
                    "phase": work.current_phase,
                    "short_description": (getattr(work, "description", None) or "")[:240],
                    "matched_terms": matched[:8],
                    "relation_evidence": evidence[:6],
                    "deterministic_score": round(score, 3),
                }
            )
        scored.sort(key=lambda r: r["deterministic_score"], reverse=True)
        return {"work_item_candidates": scored[:limit]}
