# -*- coding: utf-8 -*-
from __future__ import annotations

from odoo import fields, models


class DevCompletionReportPlan(models.Model):
    _inherit = "dev.completion.report"

    plan_id = fields.Many2one("dev.work.plan", required=True, ondelete="restrict")
    repository_id = fields.Many2one(
        "dev.repository",
        related="work_item_id.preferred_repository_id",
        readonly=True,
    )
