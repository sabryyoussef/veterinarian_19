# -*- coding: utf-8 -*-
from __future__ import annotations

from odoo import fields, models


class DevWorkPlanAnalysisLink(models.Model):
    _inherit = "dev.work.plan"

    analysis_id = fields.Many2one("dev.work.analysis", ondelete="restrict")
