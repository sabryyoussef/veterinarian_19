# -*- coding: utf-8 -*-
"""Project and Work Item candidate retrieval for WhatsApp AI."""
from __future__ import annotations

from odoo import api, models

STRONG_EVIDENCE_TYPES = frozenset(
    {
        "canonical_name",
        "message_alias",
        "arabic_alias",
        "english_alias",
        "repository_alias",
        "database_alias",
        "environment_alias",
        "work_item_link",
        "direct_source_message_link",
        "explicit_work_item_ref",
        "group_mapping",  # confirmed mapping only reaches high score
        "thread_confirmed",
    }
)
WEAK_EVIDENCE_TYPES = frozenset(
    {
        "inferred_mapping",
        "sender_only",
        "semantic",
        "customer_category",
        "stale_context",
    }
)
ALIAS_TYPE_TO_EVIDENCE = {
    "canonical": "canonical_name",
    "arabic_name": "arabic_alias",
    "english_name": "english_alias",
    "repository": "repository_alias",
    "database": "database_alias",
    "environment": "environment_alias",
    "abbreviation": "message_alias",
    "misspelling": "message_alias",
    "customer": "message_alias",
    "whatsapp_group": "message_alias",
}


class DevWhatsappAnalysisCandidates(models.AbstractModel):
    _name = "dev.whatsapp.analysis.candidates"
    _description = "WhatsApp AI project/WI candidate builders"

    @api.model
    def _candidate_thresholds(self):
        ICP = self.env["ir.config_parameter"].sudo()

        def _f(key, default):
            raw = ICP.get_param(key, str(default))
            try:
                return float(raw)
            except (TypeError, ValueError):
                return float(default)

        return {
            "unique_candidate_min_score": _f(
                "devhub_whatsapp.unique_candidate_min_score", 0.70
            ),
            "strong_candidate_min_score": _f(
                "devhub_whatsapp.strong_candidate_min_score", 0.85
            ),
            "candidate_score_margin": _f(
                "devhub_whatsapp.candidate_score_margin", 0.20
            ),
        }

    @api.model
    def _has_strong_evidence(self, entry):
        for ev in entry.get("evidence") or []:
            etype = (ev.get("type") if isinstance(ev, dict) else None) or ""
            if etype in STRONG_EVIDENCE_TYPES:
                return True
        return False

    @api.model
    def _compute_selection_policy(self, ranked, source, thresholds):
        """Odoo-authoritative proposed-selection rules.

        Ambiguous source still requires human confirmation, but a coherent
        segment with one strong candidate may propose that project.
        """
        unique_min = thresholds["unique_candidate_min_score"]
        strong_min = thresholds["strong_candidate_min_score"]
        margin = thresholds["candidate_score_margin"]
        ambiguous = source.project_mapping_state in ("ambiguous", "unmapped")

        requires_confirmation = bool(ambiguous) or not ranked
        proposed = None
        reason = "no_candidates"

        if not ranked:
            return {
                "eligible_for_proposed_selection": False,
                "proposed_project_id": None,
                "proposed_project_name": None,
                "proposed_project_code": None,
                "proposed_confidence": 0.0,
                "resolution_status": "unresolved",
                "selection_reason": reason,
                "requires_project_confirmation": True,
                "thresholds": thresholds,
            }

        top = ranked[0]
        top_score = float(top["deterministic_score"])
        second_score = (
            float(ranked[1]["deterministic_score"]) if len(ranked) > 1 else 0.0
        )
        strong = self._has_strong_evidence(top)

        if len(ranked) == 1:
            if top_score >= unique_min and strong:
                proposed = top
                reason = "unique_strong_candidate"
            elif top_score >= unique_min and not strong:
                reason = "unique_but_weak_evidence_only"
            else:
                reason = "unique_below_threshold"
        else:
            if (
                top_score >= strong_min
                and (top_score - second_score) >= margin
                and strong
            ):
                proposed = top
                reason = "dominant_strong_candidate"
            elif top_score - second_score < margin:
                reason = "candidates_too_close"
                requires_confirmation = True
            elif not strong:
                reason = "top_lacks_strong_evidence"
            else:
                reason = "top_below_strong_threshold"

        # Low absolute score always needs confirmation / no auto-propose
        if top_score < unique_min:
            requires_confirmation = True
            proposed = None
            if reason.startswith("unique") or reason.startswith("dominant"):
                reason = "top_below_threshold"

        # Confirmed single-project sources: confirmation not forced
        if not ambiguous and proposed and top_score >= 0.95:
            # Still confirm when mapping itself is not confirmed
            if source.project_mapping_state != "confirmed":
                requires_confirmation = True
            else:
                requires_confirmation = False
        elif ambiguous:
            requires_confirmation = True

        eligible = bool(proposed)
        return {
            "eligible_for_proposed_selection": eligible,
            "proposed_project_id": proposed["project_id"] if proposed else None,
            "proposed_project_name": proposed["project_name"] if proposed else None,
            "proposed_project_code": proposed.get("project_code") if proposed else None,
            "proposed_confidence": round(float(proposed["deterministic_score"]), 3)
            if proposed
            else 0.0,
            "resolution_status": "proposed" if eligible else "unresolved",
            "selection_reason": reason,
            "requires_project_confirmation": requires_confirmation,
            "thresholds": thresholds,
        }

    @api.model
    def build_project_candidates(self, source, messages, limit=8):
        """Rank validated project candidates for Dify selection."""
        Alias = self.env["dev.project.alias"].sudo()
        scored = {}  # project_id → dict
        thresholds = self._candidate_thresholds()

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
                    "has_strong_evidence": False,
                    "eligible_for_proposed_selection": False,
                },
            )
            entry["deterministic_score"] = max(entry["deterministic_score"], float(score))
            for ev in evidence or []:
                if ev not in entry["evidence"]:
                    entry["evidence"].append(ev)
                etype = (ev.get("type") if isinstance(ev, dict) else None) or ""
                if etype in STRONG_EVIDENCE_TYPES:
                    entry["has_strong_evidence"] = True
            for a in aliases_matched or []:
                if a not in entry["aliases_matched"]:
                    entry["aliases_matched"].append(a)

        # 1) Confirmed / inferred source mapping
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
                [
                    {
                        "type": "inferred_mapping",
                        "value": "Inferred source mapping (weak)",
                    }
                ],
            )

        # 2–4) Alias matches in message bodies + group name
        blob = " ".join(
            [(source.name or "")]
            + [(m.body or "")[:500] for m in messages[:20]]
        )
        for alias in Alias.match_text(blob, limit=20):
            ev_type = ALIAS_TYPE_TO_EVIDENCE.get(alias.alias_type, "message_alias")
            add(
                alias.dev_project_id,
                min(0.97, 0.6 + (alias.priority or 0) / 200.0),
                [
                    {
                        "type": ev_type,
                        "value": "Matched alias %r (%s)"
                        % (alias.name, alias.alias_type),
                    }
                ],
                aliases_matched=[alias.name],
            )

        # 5–6) Existing WI links on messages (direct source-message links)
        for msg in messages:
            for work in msg.work_item_ids[:5]:
                if work.dev_project_id:
                    add(
                        work.dev_project_id,
                        0.95,
                        [
                            {
                                "type": "direct_source_message_link",
                                "value": "Message linked to WI %s" % work.id,
                            }
                        ],
                    )

        # Ambiguous / unmapped: demote weak source-only signal
        if source.project_mapping_state in ("ambiguous", "unmapped"):
            if source.dev_project_id and source.dev_project_id.id in scored:
                if scored[source.dev_project_id.id]["deterministic_score"] < 0.7:
                    scored[source.dev_project_id.id]["deterministic_score"] = min(
                        scored[source.dev_project_id.id]["deterministic_score"], 0.4
                    )

        ranked = sorted(
            scored.values(),
            key=lambda r: (
                r["deterministic_score"],
                any(
                    (ev.get("type") if isinstance(ev, dict) else None)
                    == "direct_source_message_link"
                    for ev in (r.get("evidence") or [])
                ),
            ),
            reverse=True,
        )[:limit]
        for entry in ranked:
            entry["deterministic_score"] = round(entry["deterministic_score"], 3)
            entry["has_strong_evidence"] = self._has_strong_evidence(entry)

        # Prefer candidates with direct WI links over alias-only peers
        def _has_direct(entry):
            return any(
                (ev.get("type") if isinstance(ev, dict) else None)
                == "direct_source_message_link"
                for ev in (entry.get("evidence") or [])
            )

        ranked.sort(
            key=lambda r: (1 if _has_direct(r) else 0, r["deterministic_score"]),
            reverse=True,
        )

        policy = self._compute_selection_policy(ranked, source, thresholds)
        # Direct WI link forces proposed project even on ambiguous multi-candidate
        direct = next((c for c in ranked if _has_direct(c)), None)
        if direct:
            policy = dict(policy)
            policy["eligible_for_proposed_selection"] = True
            policy["proposed_project_id"] = direct["project_id"]
            policy["proposed_project_name"] = direct["project_name"]
            policy["proposed_project_code"] = direct.get("project_code")
            policy["proposed_confidence"] = max(
                float(direct["deterministic_score"]), 0.95
            )
            policy["resolution_status"] = "proposed"
            policy["selection_reason"] = "direct_source_message_link"
            policy["requires_project_confirmation"] = True
        elif (
            source.project_mapping_state in ("ambiguous", "unmapped")
            and policy.get("eligible_for_proposed_selection")
            and float(policy.get("proposed_confidence") or 0)
            < thresholds["strong_candidate_min_score"]
        ):
            # Ambiguous groups: require strong score for unique alias propose
            # to avoid committing incidental alias hits on noise segments.
            policy = dict(policy)
            policy["eligible_for_proposed_selection"] = False
            policy["proposed_project_id"] = None
            policy["proposed_project_name"] = None
            policy["proposed_project_code"] = None
            policy["proposed_confidence"] = 0.0
            policy["resolution_status"] = "unresolved"
            policy["selection_reason"] = "ambiguous_requires_strong_score"
            policy["requires_project_confirmation"] = True

        for entry in ranked:
            entry["eligible_for_proposed_selection"] = bool(
                policy["eligible_for_proposed_selection"]
                and entry["project_id"] == policy["proposed_project_id"]
            )

        return {
            "project_candidates": ranked,
            "requires_project_confirmation": policy["requires_project_confirmation"],
            "selection_policy": policy,
        }

    @api.model
    def build_work_item_candidates(self, project, messages, limit=8):
        """Rank WI candidates; boost direct source-message links."""
        Work = self.env["dev.work.item"].sudo()
        scored_map = {}

        def upsert(work, score, evidence, matched=None, direct_link=False):
            if not work or not work.active:
                return
            if (
                project
                and work.dev_project_id
                and work.dev_project_id != project
                and not direct_link
            ):
                # Never include foreign-project WIs when a project is selected,
                # except direct message links (authoritative).
                return
            entry = scored_map.setdefault(
                work.id,
                {
                    "work_item_id": work.id,
                    "title": work.name,
                    "project_id": work.dev_project_id.id if work.dev_project_id else None,
                    "phase": work.current_phase,
                    "short_description": (getattr(work, "description", None) or "")[
                        :240
                    ],
                    "matched_terms": [],
                    "evidence": [],
                    "relation_evidence": [],
                    "direct_message_link": False,
                    "deterministic_score": 0.0,
                },
            )
            entry["deterministic_score"] = max(entry["deterministic_score"], float(score))
            if direct_link:
                entry["direct_message_link"] = True
            for ev in evidence or []:
                if ev not in entry["evidence"]:
                    entry["evidence"].append(ev)
                if isinstance(ev, str) and ev not in entry["relation_evidence"]:
                    entry["relation_evidence"].append(ev)
                elif isinstance(ev, dict):
                    val = ev.get("value") or ev.get("type")
                    if val and val not in entry["relation_evidence"]:
                        entry["relation_evidence"].append(val)
            for term in matched or []:
                if term not in entry["matched_terms"]:
                    entry["matched_terms"].append(term)

        # Highest priority: direct message → WI links (always include, even if
        # provisional project differs — policy will align project to the WI)
        linked_works = self.env["dev.work.item"]
        for msg in messages:
            linked_works |= msg.work_item_ids
        for work in linked_works:
            upsert(
                work,
                1.0,
                [
                    {
                        "type": "direct_source_message_link",
                        "value": "Direct WhatsApp source-message link",
                    }
                ],
                matched=[str(work.id)],
                direct_link=True,
            )

        if not project and not scored_map:
            return {
                "work_item_candidates": [],
                "recommended_work_item_decision": None,
                "recommended_work_item_id": None,
            }

        terms = set()
        for msg in messages[:20]:
            body = (msg.body or "").lower()
            for token in body.replace("\n", " ").split():
                token = token.strip(".,:;()[]\"'")
                if len(token) >= 4:
                    terms.add(token)
            for work in msg.work_item_ids:
                if not project or work.dev_project_id == project:
                    terms.add(str(work.id))
                    if work.name:
                        terms.add(work.name.lower())

        if project:
            domain = [("dev_project_id", "=", project.id)]
            recent = Work.search(domain, order="write_date desc, id desc", limit=40)
            for work in recent:
                evidence = [{"type": "same_project", "value": "Same project"}]
                matched = []
                score = 0.2
                title = (work.name or "").lower()
                for term in terms:
                    if term.isdigit() and int(term) == work.id:
                        score = max(score, 0.99)
                        matched.append(term)
                        evidence.append(
                            {
                                "type": "explicit_work_item_ref",
                                "value": "Explicit Work Item ID",
                            }
                        )
                    elif term in title:
                        score = max(score, 0.75)
                        matched.append(term)
                        evidence.append(
                            {"type": "title_match", "value": "Title term match"}
                        )
                if work.id in scored_map:
                    # already boosted via direct link
                    continue
                if score < 0.35 and not matched:
                    continue
                upsert(work, score, evidence, matched=matched)

        scored = sorted(
            scored_map.values(),
            key=lambda r: r["deterministic_score"],
            reverse=True,
        )[:limit]
        for entry in scored:
            entry["deterministic_score"] = round(entry["deterministic_score"], 3)
            entry["matched_terms"] = entry["matched_terms"][:8]
            entry["evidence"] = entry["evidence"][:8]
            entry["relation_evidence"] = entry["relation_evidence"][:6]

        recommended_decision = None
        recommended_id = None
        if scored and scored[0].get("direct_message_link"):
            recommended_decision = "existing"
            recommended_id = scored[0]["work_item_id"]

        return {
            "work_item_candidates": scored,
            "recommended_work_item_decision": recommended_decision,
            "recommended_work_item_id": recommended_id,
        }
