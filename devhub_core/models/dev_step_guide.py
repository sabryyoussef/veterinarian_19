# -*- coding: utf-8 -*-
"""Shared step-guide helpers for Dev Hub single-step apps.

Each capability app shows instructions and blocks progress when a prior
step is missing — users are told what to complete first.
"""
from __future__ import annotations

from odoo import api, fields, models
from odoo.exceptions import UserError


class DevStepGuideMixin(models.AbstractModel):
    _name = "dev.step.guide.mixin"
    _description = "Dev Hub Step Guide Mixin"

    step_guide_state = fields.Selection(
        [
            ("ready", "Ready"),
            ("blocked", "Blocked"),
            ("done", "Done"),
            ("info", "Info"),
        ],
        compute="_compute_step_guide",
        string="Step status",
    )
    step_guide_title = fields.Char(compute="_compute_step_guide", string="Instructions")
    step_guide_message = fields.Text(compute="_compute_step_guide", string="What to do")
    step_guide_blocked = fields.Boolean(compute="_compute_step_guide")

    def _step_guide_payload(self):
        """Override in concrete models. Return dict with state/title/message."""
        return {
            "state": "info",
            "title": "Follow the governed Dev Hub path",
            "message": (
                "Work → Analysis → Plan → Approval → Session/Execution → "
                "Git → GitHub → Deploy. Complete the previous step before this one."
            ),
        }

    @api.depends()
    def _compute_step_guide(self):
        for record in self:
            payload = record._step_guide_payload() or {}
            state = payload.get("state") or "info"
            record.step_guide_state = state
            record.step_guide_title = payload.get("title") or ""
            record.step_guide_message = payload.get("message") or ""
            record.step_guide_blocked = state == "blocked"

    def _raise_complete_first(self, missing_items):
        """Raise a clear UserError listing what must be finished first."""
        items = [item for item in (missing_items or []) if item]
        if not items:
            return
        lines = "\n".join(f"• {item}" for item in items)
        raise UserError(
            "Complete these first before continuing this step:\n\n%s\n\n"
            "Open the matching Dev Hub app (Work / Analysis / Plan / …) "
            "and finish the missing step, then try again." % lines
        )
