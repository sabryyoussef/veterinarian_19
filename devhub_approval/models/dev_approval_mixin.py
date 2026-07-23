# -*- coding: utf-8 -*-
"""Reusable approval contract for Dev Hub capabilities."""
from __future__ import annotations

from odoo import api, fields, models
from odoo.exceptions import UserError


class DevApprovalMixin(models.AbstractModel):
    _name = "dev.approval.mixin"
    _description = "Dev Hub Approval Mixin"

    decision = fields.Selection(
        [("approved", "Approved"), ("rejected", "Rejected")],
        required=True,
        readonly=True,
    )
    approver_id = fields.Many2one("res.users", required=True, readonly=True, index=True)
    decided_at = fields.Datetime(required=True, readonly=True, index=True)
    binding_hash = fields.Char(readonly=True, index=True, copy=False)
    comment = fields.Text(readonly=True)

    def write(self, vals):
        raise UserError("Approval records are immutable.")

    def unlink(self):
        raise UserError("Approval records cannot be deleted.")
