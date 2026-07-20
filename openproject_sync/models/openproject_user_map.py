# -*- coding: utf-8 -*-
from odoo import fields, models


class OpenprojectUserMap(models.Model):
    _name = "openproject.user.map"
    _description = "OpenProject User Map"
    _order = "op_user_email, id"
    _rec_name = "op_user_email"

    backend_id = fields.Many2one(
        "openproject.backend",
        required=True,
        ondelete="cascade",
        index=True,
    )
    op_user_id = fields.Integer(string="OP User ID", index=True)
    op_user_email = fields.Char(string="OP User Email", index=True)
    odoo_user_id = fields.Many2one(
        "res.users",
        string="Odoo User",
        ondelete="set null",
    )
    active = fields.Boolean(default=True)

    _uniq_backend_op_user = models.Constraint(
        "UNIQUE(backend_id, op_user_id)",
        "This OpenProject user is already mapped for this backend.",
    )
