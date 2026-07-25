# -*- coding: utf-8 -*-
"""Project and Work Item candidate retrieval for WhatsApp AI."""
from __future__ import annotations

import re

from odoo import api, models

# Auto-generated Odoo/error boilerplate that must be stripped before judging
# whether a project alias is part of a genuine user request (current topic).
_ERROR_BOILERPLATE = re.compile(
    r"(RPC_ERROR|Odoo Server Error|Traceback \(most recent call last\)|"
    r"Occured on|Occurred on|See stack trace|handleError|_dispatch|assets_web|"
    r"حدث خطأ ما|إذا كنت حقا|إذا كنت حقاً|قم بمشاركة التقرير|خدمة الدعم|"
    r"خطأ في خادم أودو|حطأ في خادم|خطأ في خادم|File \"|line \d+, in )",
    re.I,
)
_MEDIA_ONLY = re.compile(
    r"^(?:\s*\[(?:image|audio|video|document|sticker|gif)\]\s*)+$", re.I
)
# Request / bug / imperative language signalling an actionable statement.
_REQUEST_LANG = re.compile(
    r"(عايز|عاوز|محتاج|محتاجين|ممكن|ياريت|يا ريت|برجاء|رجاء|لو سمحت|من فضلك|"
    r"please|need|needs|can you|could you|kindly|fix|add|install|update|upgrade|"
    r"deploy|check|review|implement|correct|integrat|investigat|analy|"
    r"مشكلة|مشاكل|خطأ|ايرور|error|errors|bug|لا يعمل|مش شغال|مش راضي|not work|"
    r"fails|failed|عطل|صحح|عدل|اعمل|نفذ|اضف|ثبت|اختبار|افتح|سجل)",
    re.I,
)
# Explicit repository / database / server / environment references that tie a
# statement to a concrete project deployment.
_ENV_CONTEXT = re.compile(
    r"(سيرفر|server|داتا ?بيز|داتا ?بايز|database|host|بيئة|environment|"
    r"repo|repository|erp\.|\.odoo\.com|\.edu|portal\.|https?://|بورت)",
    re.I,
)
_FUTURE_CONTEXT = re.compile(
    r"(once\b.*\bfinish\b.*\bwill\b|will\s+(?:later\s+)?(?:test|check|review)|"
    r"after\s+.*\bfinish\b|لاحق[ًاا]?|بعد\s+ما\s+(?:اخلص|نخلص|يخلص))",
    re.I,
)
_FUTURE_ALIAS_PREFIX = re.compile(
    r"(?:\bwill\s+(?:later\s+)?(?:test|check|review)\s+|"
    r"\blater\s+(?:test|check|review)\s+|لاحق[ًاا]?\s+)",
    re.I,
)

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
            "project_relevance_min_confidence": _f(
                "devhub_whatsapp.project_relevance_min_confidence", 0.50
            ),
            "media_dominant_ratio": _f(
                "devhub_whatsapp.media_dominant_ratio", 0.40
            ),
        }

    # ---- Deterministic text helpers for project relevance / actionability ----
    @api.model
    def _clean_user_text(self, body):
        """Strip auto-generated Odoo/error boilerplate, keep user prose."""
        if not body:
            return ""
        out = []
        for ln in str(body).splitlines():
            s = ln.strip()
            if not s or _ERROR_BOILERPLATE.search(s):
                continue
            out.append(s)
        return " ".join(out).strip()

    @api.model
    def _prose_token_count(self, text):
        return len([t for t in re.split(r"\s+", text or "") if t])

    @api.model
    def _message_is_media_only(self, msg):
        body = (msg.body or "").strip()
        if msg.media_kind and msg.media_kind != "none":
            stripped = re.sub(
                r"\[(image|audio|video|document|sticker|gif)\]",
                "",
                body,
                flags=re.I,
            ).strip()
            return len(stripped) < 3
        return bool(_MEDIA_ONLY.match(body))

    @api.model
    def _segment_actionability(self, messages):
        """Deterministic segment actionability: request/bug language + signals."""
        signals = []
        for m in messages[:20]:
            clean = self._clean_user_text(m.body or "")
            # Negated "no problem" / success-report language is not a request.
            if re.search(
                r"(مافيش\s+مشكلة|لا\s+مشكلة|no\s+problem|تم\s+اختبار.{0,40}بنجاح)",
                clean,
                re.I,
            ):
                continue
            hit = _REQUEST_LANG.search(clean)
            if hit and self._prose_token_count(clean) >= 3:
                signals.append(hit.group(0).lower())
        is_actionable = bool(signals)
        return {
            "is_actionable": is_actionable,
            "score": round(min(1.0, 0.4 + 0.2 * len(set(signals))), 3)
            if is_actionable
            else 0.0,
            "signals": sorted(set(signals))[:8],
        }

    @api.model
    def _has_strong_evidence(self, entry):
        for ev in entry.get("evidence") or []:
            etype = (ev.get("type") if isinstance(ev, dict) else None) or ""
            if etype in STRONG_EVIDENCE_TYPES:
                return True
        return False

    @api.model
    def _entry_has_direct(self, entry):
        return any(
            (ev.get("type") if isinstance(ev, dict) else None)
            == "direct_source_message_link"
            for ev in (entry.get("evidence") or [])
        )

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
        top_score = float(
            (top.get("score_breakdown") or {}).get("final_score")
            or top["deterministic_score"]
        )
        second_score = (
            float(
                (ranked[1].get("score_breakdown") or {}).get("final_score")
                or ranked[1]["deterministic_score"]
            )
            if len(ranked) > 1
            else 0.0
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
            "proposed_confidence": round(
                min(
                    1.0,
                    float(
                        (proposed.get("score_breakdown") or {}).get("final_score")
                        or proposed["deterministic_score"]
                    ),
                ),
                3,
            )
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

        # 2) Group-name aliases are only a weak mapping hint (context), never
        #    proof that the *current* actionable request is about that project.
        for alias in Alias.match_text(source.name or "", limit=20):
            if not alias.dev_project_id:
                continue
            ev_type = ALIAS_TYPE_TO_EVIDENCE.get(alias.alias_type, "message_alias")
            add(
                alias.dev_project_id,
                min(0.70, 0.5 + (alias.priority or 0) / 300.0),
                [{"type": ev_type, "value": "Group-name alias %r" % alias.name}],
                aliases_matched=[alias.name],
            )

        # 3–4) Per-message alias matches + deterministic project_relevance:
        #      does the alias appear as part of the *current* actionable topic,
        #      or only as an incidental/context/boilerplate mention?
        relevance = {}

        def rel(pid):
            return relevance.setdefault(
                pid,
                {
                    "strong_topic_hits": 0,
                    "env_hits": 0,
                    "standalone_hits": 0,
                    "context_hits": 0,
                    "max_alias_prose_tokens": 0,
                    "alias_msg_ids": set(),
                    "evidence": [],
                },
            )

        total_msgs = 0
        media_msgs = 0
        total_prose_tokens = 0
        for m in messages[:20]:
            total_msgs += 1
            body = m.body or ""
            if self._message_is_media_only(m):
                media_msgs += 1
            clean = self._clean_user_text(body)
            prose_tokens = self._prose_token_count(clean)
            total_prose_tokens += prose_tokens
            actionable = bool(_REQUEST_LANG.search(clean))
            env_ctx = bool(_ENV_CONTEXT.search(clean))
            clean_hits = {
                a.dev_project_id.id
                for a in Alias.match_text(clean, limit=20)
                if a.dev_project_id
            }
            for alias in Alias.match_text(body, limit=20):
                proj = alias.dev_project_id
                if not proj:
                    continue
                ev_type = ALIAS_TYPE_TO_EVIDENCE.get(alias.alias_type, "message_alias")
                add(
                    proj,
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
                info = rel(proj.id)
                info["alias_msg_ids"].add(m.id)
                in_clean = proj.id in clean_hits
                is_env_alias = alias.alias_type in (
                    "database",
                    "environment",
                    "repository",
                )
                alias_pos = clean.lower().find((alias.name or "").lower())
                future_prefix = _FUTURE_ALIAS_PREFIX.search(clean)
                future_ctx = bool(
                    _FUTURE_CONTEXT.search(clean)
                    and future_prefix
                    and alias_pos >= future_prefix.start()
                )
                if in_clean and prose_tokens <= 2:
                    info["standalone_hits"] += 1
                if in_clean and not future_ctx and prose_tokens >= 4:
                    info["max_alias_prose_tokens"] = max(
                        info["max_alias_prose_tokens"], prose_tokens
                    )
                if in_clean and not future_ctx and prose_tokens >= 4 and (
                    actionable or is_env_alias or env_ctx
                ):
                    info["strong_topic_hits"] += 1
                    info["evidence"].append(
                        "alias in actionable statement (msg %s)" % m.id
                    )
                elif (
                    in_clean
                    and not future_ctx
                    and (is_env_alias or env_ctx)
                    and prose_tokens >= 3
                ):
                    info["env_hits"] += 1
                    info["evidence"].append(
                        "alias near environment reference (msg %s)" % m.id
                    )
                else:
                    info["context_hits"] += 1

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

        # Attach deterministic project_relevance + score decomposition per entry
        media_ratio = (media_msgs / total_msgs) if total_msgs else 0.0
        media_dom = media_ratio >= thresholds["media_dominant_ratio"]
        distinct_alias_projects = len(
            [1 for e in scored.values() if e.get("aliases_matched")]
        )
        for entry in scored.values():
            info = relevance.get(entry["project_id"]) or {}
            has_direct = self._entry_has_direct(entry)
            strong = int(info.get("strong_topic_hits") or 0)
            env = int(info.get("env_hits") or 0)
            standalone = int(info.get("standalone_hits") or 0)
            context = int(info.get("context_hits") or 0)
            max_prose = int(info.get("max_alias_prose_tokens") or 0)
            # Current topic requires the alias to appear in at least one
            # substantive user statement (>=4 prose tokens), or be repeated
            # standalone, or be tied to a direct WI link / environment ref.
            # An alias seen only in a 2-token fragment and error boilerplate
            # (e.g. "في استا" + a pasted traceback) is NOT the current topic.
            is_current_topic = bool(
                has_direct
                or strong >= 1
                or env >= 1
                or standalone >= 3
                or max_prose >= 4
            )
            # A media-dominated, low-text segment where the alias is only a
            # short incidental caption / environment note (e.g. "installed in
            # asta test") must not commit a project.
            media_weak = bool(
                media_dom
                and not has_direct
                and max_prose < 8
                and total_prose_tokens < 40
            )
            if has_direct:
                confidence = 0.95
            elif strong >= 1 or env >= 1:
                confidence = 0.80
            elif standalone >= 3 or max_prose >= 8:
                confidence = 0.70
            elif max_prose >= 4:
                confidence = 0.60
            else:
                confidence = 0.20
            # Score decomposition is authoritative for ranking and policy.
            alias_score = round(min(0.97, entry["deterministic_score"]), 3)
            direct_link_score = 0.95 if has_direct else 0.0
            current_topic_score = round(
                0.5
                if strong >= 1
                else (
                    0.35
                    if (env or standalone >= 3 or max_prose >= 4)
                    else 0.0
                ),
                3,
            )
            context_score = round(min(0.1, 0.03 * context), 3)
            conflict_penalty = 0.0
            if distinct_alias_projects > 1 and not has_direct:
                conflict_penalty += 0.3
            if not is_current_topic:
                conflict_penalty += 0.3
            if media_weak:
                conflict_penalty += 0.3
            conflict_penalty = round(conflict_penalty, 3)
            final_score = round(
                max(
                    0.0,
                    max(alias_score, direct_link_score)
                    + current_topic_score
                    + context_score
                    - conflict_penalty,
                ),
                3,
            )
            entry["project_relevance"] = {
                "is_current_topic": is_current_topic,
                "confidence": round(confidence, 3),
                "media_weak": media_weak,
                "evidence": (info.get("evidence") or [])[:6],
            }
            entry["score_breakdown"] = {
                "alias_score": alias_score,
                "current_topic_score": current_topic_score,
                "direct_link_score": direct_link_score,
                "context_score": context_score,
                "conflict_penalty": conflict_penalty,
                "final_score": final_score,
            }

        ranked = sorted(
            scored.values(),
            key=lambda r: (
                (r.get("score_breakdown") or {}).get("final_score", 0.0),
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
            key=lambda r: (
                1 if _has_direct(r) else 0,
                (r.get("score_breakdown") or {}).get("final_score", 0.0),
            ),
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

        # Project relevance gate (ambiguous sources only): a project alias alone
        # is not enough — the current actionable topic must be about that
        # project. Direct WI links bypass this gate. Confirmed single-project
        # sources rely on their group mapping and are never gated here.
        ambiguous = source.project_mapping_state in ("ambiguous", "unmapped")
        if (
            ambiguous
            and not direct
            and policy.get("eligible_for_proposed_selection")
            and policy.get("proposed_project_id")
        ):
            proposed_entry = next(
                (
                    e
                    for e in ranked
                    if e["project_id"] == policy["proposed_project_id"]
                ),
                None,
            )
            prj = (proposed_entry or {}).get("project_relevance") or {}
            min_conf = thresholds["project_relevance_min_confidence"]
            gate_ok = (
                bool(prj.get("is_current_topic"))
                and not prj.get("media_weak")
                and float(prj.get("confidence") or 0.0) >= min_conf
            )
            if not gate_ok:
                reason = (
                    "media_incidental_reference"
                    if prj.get("media_weak")
                    else "alias_not_current_topic"
                )
                policy = dict(policy)
                policy["eligible_for_proposed_selection"] = False
                policy["proposed_project_id"] = None
                policy["proposed_project_name"] = None
                policy["proposed_project_code"] = None
                policy["proposed_confidence"] = 0.0
                policy["resolution_status"] = "unresolved"
                policy["selection_reason"] = reason
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
                        # Generic single-token title overlap is weak, inferred
                        # evidence — never enough on its own to claim an
                        # *existing* Work Item (only direct link / explicit id).
                        score = max(score, 0.45)
                        matched.append(term)
                        evidence.append(
                            {
                                "type": "inferred_title_match",
                                "value": "Weak title term overlap",
                            }
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
