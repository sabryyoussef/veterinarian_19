# -*- coding: utf-8 -*-
"""Lead Engine qualification pipeline (Sprint 3).

**Call order** (``run_qualification_pipeline`` / ``apply``)::

    1. evaluate_duplicate_state  → duplicate_status, duplicate_master_id only
    2. recompute_score           → lead_score only (if source.auto_score)
    3. apply_assignment          → user_id, team_id, assignment_status only
    4. _upsert_identity_map       → identity.map rows
    5. finalize_qualification_state → qualification_state only

Each step is side-effect scoped; do not rely on hidden cross-writes between fields
except the intentional order above (e.g. assignment reads lead_score and duplicate_status).
"""

import logging

from odoo import models
from odoo.tools import email_normalize
from odoo.tools.safe_eval import safe_eval

_logger = logging.getLogger(__name__)

_SCORE_MIN = 0
_SCORE_MAX = 1000

_ALLOWED_LEAD_FIELDS = frozenset(
    {
        "name",
        "contact_name",
        "email_from",
        "phone",
        "mobile",
        "partner_name",
        "type",
        "le_channel",
        "lead_engine_source_id",
    }
)


class LeadEngineQualificationPipeline(models.AbstractModel):
    _name = "lead.engine.qualification.pipeline"
    _description = "Lead Engine Qualification Pipeline"

    # -------------------------------------------------------------------------
    # Orchestration
    # -------------------------------------------------------------------------

    def apply(self, lead):
        """Backward-compatible alias for :meth:`run_qualification_pipeline`."""
        return self.run_qualification_pipeline(lead)

    def run_qualification_pipeline(self, leads):
        """Run the full pipeline for each lead (order: dedupe → score → assign → map → qualify)."""
        for lead in leads.sudo():
            lead.ensure_one()
            self.evaluate_duplicate_state(lead)
            self.recompute_score(lead)
            self.apply_assignment(lead)
            self._upsert_identity_map(lead)
            self.finalize_qualification_state(lead)
        return leads

    # -------------------------------------------------------------------------
    # D — Duplicate state (duplicate_status, duplicate_master_id)
    # -------------------------------------------------------------------------

    def evaluate_duplicate_state(self, leads):
        """Recompute duplicate markers from ``(lead_engine_source_id, external_ref)``.

        Master is the oldest sibling by ``create_date``, ``id``. Writes only
        ``duplicate_status`` and ``duplicate_master_id``. Does not touch score,
        assignment, or qualification_state.
        """
        for lead in leads.sudo():
            lead.ensure_one()
            self._evaluate_duplicate_state_one(lead)

    def _evaluate_duplicate_state_one(self, lead):
        if not lead.external_ref or not lead.lead_engine_source_id:
            lead.write(
                {
                    "duplicate_status": "unique",
                    "duplicate_master_id": False,
                }
            )
            return
        siblings = self.env["crm.lead"].search(
            [
                ("lead_engine_source_id", "=", lead.lead_engine_source_id.id),
                ("external_ref", "=", lead.external_ref),
            ],
            order="create_date asc, id asc",
        )
        if len(siblings) <= 1:
            lead.write(
                {
                    "duplicate_status": "unique",
                    "duplicate_master_id": False,
                }
            )
            return
        master = siblings[0]
        if lead == master:
            lead.write(
                {
                    "duplicate_status": "unique",
                    "duplicate_master_id": False,
                }
            )
            return
        lead.write(
            {
                "duplicate_status": "duplicate",
                "duplicate_master_id": master.id,
            }
        )

    # -------------------------------------------------------------------------
    # A — Scoring (lead_score)
    # -------------------------------------------------------------------------

    def recompute_score(self, leads):
        """Additive score from active rules, ordered by ``sequence, id``.

        Rules are filtered by company, optional ``source_id`` / ``le_channel``.
        If the lead has no source or ``auto_score`` is off on the source, the
        score field is **not** written (preserves existing / manual values).

        Result is clamped to [0, 1000].
        """
        for lead in leads.sudo():
            lead.ensure_one()
            self._recompute_score_one(lead)

    def _recompute_score_one(self, lead):
        source = lead.lead_engine_source_id
        if not source or not source.auto_score:
            return
        total = 0
        company = lead.company_id or self.env.company
        Rule = self.env["lead.engine.score.rule"]
        rules = Rule.search(
            [
                ("active", "=", True),
                "|",
                ("company_id", "=", False),
                ("company_id", "=", company.id),
            ],
            order="sequence, id",
        )
        for rule in rules:
            if rule.company_id and rule.company_id != company:
                continue
            if rule.source_id and rule.source_id != lead.lead_engine_source_id:
                continue
            if rule.le_channel and rule.le_channel != lead.le_channel:
                continue
            if self._score_rule_matches(lead, rule):
                total += rule.score_delta
        total = max(_SCORE_MIN, min(_SCORE_MAX, total))
        lead.write({"lead_score": total})

    def _score_rule_matches(self, lead, rule):
        if rule.rule_type == "always":
            return True
        if rule.rule_type == "field":
            if rule.field_name not in _ALLOWED_LEAD_FIELDS:
                _logger.warning(
                    "Ignoring score rule %s: field %s not allowlisted",
                    rule.id,
                    rule.field_name,
                )
                return False
            return self._compare_field(lead, rule)
        return False

    def _compare_field(self, lead, rule):
        field_name = rule.field_name
        raw = getattr(lead, field_name, None)
        if field_name.endswith("_id") or field_name == "lead_engine_source_id":
            left = raw.id if raw else False
            try:
                right = int(rule.value) if rule.value not in (None, "") else False
            except (TypeError, ValueError):
                right = False
        else:
            left = (raw or "").strip() if isinstance(raw, str) else raw
            right = rule.value

        op = rule.operator
        if op == "set":
            return bool(raw)
        if op == "not_set":
            return not bool(raw)
        if op == "eq":
            return left == right
        if op == "ne":
            return left != right
        if op in ("gt", "gte", "lt", "lte"):
            try:
                lf = float(left) if left is not None else 0.0
                rf = float(right)
            except (TypeError, ValueError):
                return False
            if op == "gt":
                return lf > rf
            if op == "gte":
                return lf >= rf
            if op == "lt":
                return lf < rf
            return lf <= rf
        if op == "contains":
            return bool(left) and str(right) in str(left)
        if op == "in":
            options = rule.value_json if isinstance(rule.value_json, list) else []
            return str(left) in {str(x) for x in options}
        return False

    # -------------------------------------------------------------------------
    # B — Assignment (user_id, team_id, assignment_status)
    # -------------------------------------------------------------------------

    def apply_assignment(self, leads):
        """Apply the first matching assignment rule (sequence, id), then optional source defaults.

        **MVP contract:** the first active rule whose domain, source/channel/score
        filters match **and** defines at least one of ``user_id`` / ``team_id``
        wins; no merging from later rules. Does not implement dedupe or scoring.

        Duplicate leads: only ``assignment_status`` is set to ``unassigned``;
        ``user_id`` / ``team_id`` are not cleared here.

        If ``auto_assign`` is off on the source, only ``assignment_status`` is
        derived from whether the lead already has user or team.
        """
        for lead in leads.sudo():
            lead.ensure_one()
            self._apply_assignment_one(lead)

    def _apply_assignment_one(self, lead):
        if lead.duplicate_status == "duplicate":
            lead.write({"assignment_status": "unassigned"})
            return
        source = lead.lead_engine_source_id
        if not source or not source.auto_assign:
            if lead.user_id or lead.team_id:
                lead.write({"assignment_status": "assigned"})
            else:
                lead.write({"assignment_status": "unassigned"})
            return
        company = lead.company_id or self.env.company
        Rule = self.env["lead.engine.assignment.rule"]
        rules = Rule.search(
            [
                ("active", "=", True),
                "|",
                ("company_id", "=", False),
                ("company_id", "=", company.id),
            ],
            order="sequence, id",
        )
        rule_applied = False
        for rule in rules:
            if rule.company_id and rule.company_id != company:
                continue
            if rule.source_id and rule.source_id != lead.lead_engine_source_id:
                continue
            if rule.le_channel and rule.le_channel != lead.le_channel:
                continue
            # Optional Integer fields use False when unset (not None).
            if rule.min_score not in (False, None) and lead.lead_score < rule.min_score:
                continue
            if rule.max_score not in (False, None) and lead.lead_score > rule.max_score:
                continue
            if not self._assignment_domain_matches(lead, rule.domain_expression):
                continue
            if not rule.team_id and not rule.user_id:
                continue
            vals = {}
            if rule.team_id:
                vals["team_id"] = rule.team_id.id
            if rule.user_id:
                vals["user_id"] = rule.user_id.id
            vals["assignment_status"] = "rule_applied"
            lead.write(vals)
            rule_applied = True
            break
        if not rule_applied and source:
            fallback = {}
            if source.default_team_id:
                fallback["team_id"] = source.default_team_id.id
            if source.default_user_id:
                fallback["user_id"] = source.default_user_id.id
            if fallback:
                fallback["assignment_status"] = "rule_applied"
                lead.write(fallback)
                rule_applied = True
        if not rule_applied:
            if lead.user_id or lead.team_id:
                lead.write({"assignment_status": "assigned"})
            else:
                lead.write({"assignment_status": "unassigned"})

    def _assignment_domain_matches(self, lead, domain_expression):
        try:
            domain = safe_eval(domain_expression or "[]")
        except (ValueError, SyntaxError, TypeError) as exc:
            _logger.warning("Invalid assignment domain %s: %s", domain_expression, exc)
            return False
        if not isinstance(domain, list):
            return False
        try:
            return bool(lead.filtered_domain(domain))
        except Exception as exc:  # pylint: disable=broad-except
            _logger.warning("Assignment domain failed for lead %s: %s", lead.id, exc)
            return False

    # -------------------------------------------------------------------------
    # Identity map
    # -------------------------------------------------------------------------

    def _upsert_identity_map(self, lead):
        lead = lead.sudo()
        lead.ensure_one()
        if not lead.lead_engine_source_id:
            return
        Map = self.env["lead.engine.identity.map"].sudo()
        norm_email = email_normalize(lead.email_from) if lead.email_from else False
        domain = [
            ("active", "=", True),
            ("source_id", "=", lead.lead_engine_source_id.id),
        ]
        if lead.external_ref:
            domain.append(("external_ref", "=", lead.external_ref))
        else:
            return
        existing = Map.search(domain, limit=1)
        vals = {
            "source_id": lead.lead_engine_source_id.id,
            "external_ref": lead.external_ref,
            "lead_id": lead.id,
            "partner_id": lead.partner_id.id if lead.partner_id else False,
            "email": lead.email_from or False,
            "mobile": getattr(lead, 'mobile', False) or lead.phone or False,
            "company_name": lead.partner_name or False,
            "normalized_email": norm_email or False,
            "normalized_mobile": False,
            "matched_by": "external_ref",
            "active": True,
        }
        if existing:
            existing.write(vals)
        else:
            Map.create(vals)

    # -------------------------------------------------------------------------
    # C — Qualification state (qualification_state only)
    # -------------------------------------------------------------------------

    def finalize_qualification_state(self, leads):
        """Set ``qualification_state`` from duplicate + assignment snapshot.

        Does not modify ``duplicate_status`` or ``assignment_status``.

        MVP transitions:

        - ``duplicate`` → ``qualification_state = new``
        - else if assigned (rule_applied or assigned) and (user_id or team_id) → ``working``
        - else → ``new``

        Values ``qualified`` / ``disqualified`` are **not** set by the pipeline.
        """
        for lead in leads.sudo():
            lead.ensure_one()
            self._finalize_qualification_state_one(lead)

    def _finalize_qualification_state_one(self, lead):
        if lead.duplicate_status == "duplicate":
            qstate = "new"
        elif lead.qualification_state in ("qualified", "disqualified"):
            return
        elif lead.assignment_status in ("rule_applied", "assigned") and (
            lead.user_id or lead.team_id
        ):
            qstate = "working"
        else:
            qstate = "new"
        if lead.qualification_state != qstate:
            lead.write({"qualification_state": qstate})
