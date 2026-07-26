# -*- coding: utf-8 -*-
from odoo import fields, models


class DevWorkCheckpointExecution(models.Model):
    _inherit = "dev.work.checkpoint"

    execution_workspace_id = fields.Many2one(
        "dev.execution.workspace", ondelete="restrict", readonly=True, index=True
    )
