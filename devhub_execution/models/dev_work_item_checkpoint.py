# -*- coding: utf-8 -*-
from __future__ import annotations

from odoo import api, fields, models


class DevWorkItemCheckpoint(models.Model):
    _inherit = "dev.work.item"

    checkpoint_ids = fields.One2many("dev.work.checkpoint", "work_item_id")
    current_checkpoint_id = fields.Many2one(
        "dev.work.checkpoint", compute="_compute_checkpoint_artifacts", store=False
    )

    @api.depends("checkpoint_ids.captured_at")
    def _compute_checkpoint_artifacts(self):
        for record in self:
            cps = record.checkpoint_ids.sorted("captured_at", reverse=True)
            record.current_checkpoint_id = cps[:1]
