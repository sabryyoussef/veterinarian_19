# -*- coding: utf-8 -*-
from odoo import fields, models


class OpenprojectStatusMap(models.Model):
    _name = "openproject.status.map"
    _description = "OpenProject Status Map"
    _order = "op_status_name, id"
    _rec_name = "op_status_name"

    backend_id = fields.Many2one(
        "openproject.backend",
        required=True,
        ondelete="cascade",
        index=True,
    )
    op_status_id = fields.Integer(string="OP Status ID", index=True)
    op_status_href = fields.Char(string="OP Status Href")
    op_status_name = fields.Char(string="OP Status Name", required=True)
    odoo_stage_id = fields.Many2one(
        "project.task.type",
        string="Odoo Task Stage",
        ondelete="set null",
    )
    active = fields.Boolean(default=True)

    _uniq_backend_status = models.Constraint(
        "UNIQUE(backend_id, op_status_id)",
        "This OpenProject status is already mapped for this backend.",
    )
