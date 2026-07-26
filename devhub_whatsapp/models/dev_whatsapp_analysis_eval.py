# -*- coding: utf-8 -*-
"""Offline / regression evaluation scores for WhatsApp AI analyses."""
from __future__ import annotations

import json

from odoo import api, fields, models


SCORE_WEIGHTS = {
    "project": 15,
    "multitask": 20,
    "classification": 10,
    "paths": 20,
    "acceptance": 15,
    "questions": 10,
    "op_link": 10,
}


class DevWhatsappAnalysisEval(models.Model):
    _name = "dev.whatsapp.analysis.eval"
    _description = "WhatsApp AI Analysis Evaluation"
    _order = "id desc"

    name = fields.Char(compute="_compute_name", store=True)
    conversation_id = fields.Many2one(
        "whatsapp.conversation", ondelete="set null", index=True
    )
    source_message_ids = fields.Text(
        help="JSON list of whatsapp.message ids used in the evaluation sample."
    )
    prompt_version = fields.Char(index=True)
    raw_input = fields.Text()
    raw_output = fields.Text()
    normalized_output = fields.Text()
    baseline_analysis_id = fields.Many2one(
        "dev.whatsapp.analysis", ondelete="set null", index=True
    )
    after_analysis_id = fields.Many2one(
        "dev.whatsapp.analysis", ondelete="set null", index=True
    )
    cursor_reference = fields.Text(
        help="Cursor / human reference notes used as scoring ground truth."
    )
    score_project = fields.Float()
    score_multitask = fields.Float()
    score_classification = fields.Float()
    score_paths = fields.Float()
    score_acceptance = fields.Float()
    score_questions = fields.Float()
    score_op_link = fields.Float()
    total_score = fields.Float(index=True)
    notes = fields.Text()

    @api.depends("baseline_analysis_id", "after_analysis_id", "prompt_version")
    def _compute_name(self):
        for rec in self:
            base = rec.baseline_analysis_id.id or "?"
            after = rec.after_analysis_id.id or "?"
            rec.name = "Eval baseline#%s → #%s (%s)" % (
                base,
                after,
                rec.prompt_version or "n/a",
            )

    @api.model
    def _normalize_path_token(self, path):
        """Normalize a path for scoring: separators, slashes, case, basename."""
        raw = (path or "").strip().replace("\\", "/")
        while "//" in raw:
            raw = raw.replace("//", "/")
        raw = raw.lower().rstrip("/")
        # strip wrapping quotes common in tracebacks
        if len(raw) >= 2 and raw[0] in "'\"" and raw[-1] == raw[0]:
            raw = raw[1:-1]
        return raw

    @api.model
    def _paths_equivalent(self, expected, got):
        """True when paths match exactly, by basename-only, or by path suffix.

        Two different directory trees that only share a basename (e.g. two
        modules each with static/description/index.html) are NOT equivalent
        unless one side is basename-only (evaluation target like 'index.html').
        """
        a = self._normalize_path_token(expected)
        b = self._normalize_path_token(got)
        if not a or not b:
            return False
        if a == b:
            return True
        base_a = a.rsplit("/", 1)[-1]
        base_b = b.rsplit("/", 1)[-1]
        # Basename-only expected/got: match any path ending with that file name
        if a == base_a and base_a == base_b:
            return b == base_b or b.endswith("/" + base_a)
        if b == base_b and base_a == base_b:
            return a == base_a or a.endswith("/" + base_b)
        # Full paths: allow suffix containment with boundary
        if len(a) < len(b) and b.endswith(a) and b[-(len(a) + 1)] == "/":
            return True
        if len(b) < len(a) and a.endswith(b) and a[-(len(b) + 1)] == "/":
            return True
        return False

    @api.model
    def score_kafaat_comparison(self, baseline, after, cursor_notes):
        """Score after-analysis vs baseline + cursor notes (Kafaat comparison weights).

        Weights: project 15, multitask 20, classification 10, paths 20,
        acceptance 15, questions 10, op_link 10. Max total = 100.
        """
        notes = cursor_notes if isinstance(cursor_notes, dict) else {}
        if isinstance(cursor_notes, str) and cursor_notes.strip():
            try:
                notes = json.loads(cursor_notes) or {}
            except (TypeError, ValueError, json.JSONDecodeError):
                notes = {"raw": cursor_notes}

        def _load_json(text):
            try:
                return json.loads(text or "{}") or {}
            except (TypeError, ValueError, json.JSONDecodeError):
                return {}

        base_detail = _load_json(getattr(baseline, "analysis_detail_json", None))
        after_detail = _load_json(getattr(after, "analysis_detail_json", None))
        base_ev = _load_json(getattr(baseline, "technical_evidence_json", None))
        after_ev = _load_json(getattr(after, "technical_evidence_json", None))
        if not after_ev and isinstance(notes.get("technical_evidence"), dict):
            after_ev = notes["technical_evidence"]

        # project
        expected_project = (
            notes.get("project")
            or notes.get("expected_project")
            or (baseline.resolved_project_id.name if baseline and baseline.resolved_project_id else None)
            or (baseline.dev_project_id.name if baseline else None)
        )
        got_project = (
            after.resolved_project_id.name
            if after.resolved_project_id
            else (after.dev_project_id.name if after.dev_project_id else None)
        )
        score_project = (
            float(SCORE_WEIGHTS["project"])
            if expected_project
            and got_project
            and str(expected_project).strip().lower() in str(got_project).strip().lower()
            else (
                float(SCORE_WEIGHTS["project"]) * 0.5
                if got_project
                else 0.0
            )
        )

        # multitask
        expected_multi = bool(
            notes.get("contains_multiple_tasks")
            if "contains_multiple_tasks" in notes
            else (baseline.contains_multiple_tasks if baseline else False)
        )
        score_multitask = (
            float(SCORE_WEIGHTS["multitask"])
            if bool(after.contains_multiple_tasks) == expected_multi
            else 0.0
        )

        # classification
        expected_class = (
            notes.get("classification")
            or (baseline.classification if baseline else None)
        )
        score_classification = (
            float(SCORE_WEIGHTS["classification"])
            if expected_class and after.classification == expected_class
            else (
                float(SCORE_WEIGHTS["classification"]) * 0.5
                if after.classification
                else 0.0
            )
        )

        # paths — compare extracted paths to cursor expected paths (basename / suffix aware)
        expected_paths = {
            str(p).lower()
            for p in (notes.get("paths") or notes.get("detected_paths") or [])
        }
        if not expected_paths:
            expected_paths = {
                str(p).lower() for p in (base_ev.get("detected_paths") or [])
            }
        got_paths = {str(p).lower() for p in (after_ev.get("detected_paths") or [])}
        # Also merge affected_paths from analysis_detail
        for p in after_detail.get("affected_paths") or []:
            got_paths.add(str(p).lower())
        if expected_paths:
            matched = 0
            for exp in expected_paths:
                if any(self._paths_equivalent(exp, got) for got in got_paths):
                    matched += 1
            overlap = matched / float(len(expected_paths))
            score_paths = float(SCORE_WEIGHTS["paths"]) * overlap
        else:
            score_paths = float(SCORE_WEIGHTS["paths"]) if got_paths else 0.0

        # acceptance
        after_ac = after_detail.get("acceptance_criteria") or []
        expected_ac = notes.get("acceptance_criteria") or (
            base_detail.get("acceptance_criteria") or []
        )
        if expected_ac:
            score_acceptance = (
                float(SCORE_WEIGHTS["acceptance"])
                if isinstance(after_ac, list) and after_ac
                else 0.0
            )
        else:
            score_acceptance = (
                float(SCORE_WEIGHTS["acceptance"]) * 0.5
                if isinstance(after_ac, list) and after_ac
                else float(SCORE_WEIGHTS["acceptance"])
            )

        # questions / missing info
        try:
            after_missing = json.loads(after.missing_information_json or "[]") or []
        except (TypeError, ValueError, json.JSONDecodeError):
            after_missing = []
        expected_questions = notes.get("questions") or notes.get("missing_information")
        if expected_questions:
            score_questions = (
                float(SCORE_WEIGHTS["questions"])
                if after_missing
                else 0.0
            )
        else:
            score_questions = float(SCORE_WEIGHTS["questions"]) * (
                1.0 if after_missing is not None else 0.0
            )

        # op_link
        expected_op = notes.get("op_link") or notes.get("op_recommended_parent_id")
        got_op = after.op_recommended_parent_id or False
        if expected_op:
            score_op_link = (
                float(SCORE_WEIGHTS["op_link"])
                if got_op and str(expected_op) in str(got_op)
                else 0.0
            )
        else:
            score_op_link = float(SCORE_WEIGHTS["op_link"]) * (0.5 if got_op else 1.0)

        total = (
            score_project
            + score_multitask
            + score_classification
            + score_paths
            + score_acceptance
            + score_questions
            + score_op_link
        )
        vals = {
            "baseline_analysis_id": baseline.id if baseline else False,
            "after_analysis_id": after.id if after else False,
            "prompt_version": after.prompt_version if after else False,
            "conversation_id": (
                after.conversation_ids[:1].id if after and after.conversation_ids else False
            ),
            "source_message_ids": json.dumps(
                after.batch_message_ids.ids if after else []
            ),
            "raw_input": after.dify_request_json if after else False,
            "raw_output": after.raw_response_json if after else False,
            "normalized_output": after.validated_json if after else False,
            "cursor_reference": json.dumps(notes, ensure_ascii=False)
            if notes
            else False,
            "score_project": score_project,
            "score_multitask": score_multitask,
            "score_classification": score_classification,
            "score_paths": score_paths,
            "score_acceptance": score_acceptance,
            "score_questions": score_questions,
            "score_op_link": score_op_link,
            "total_score": total,
            "notes": "Kafaat comparison weights applied.",
        }
        return self.create(vals)
