# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class LinkedinCvVersion(models.Model):
    _name = "linkedin.cv.version"
    _description = "LinkedIn Job Hunt CV Version"
    _order = "is_default desc, id desc"
    _rec_name = "name"

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    account_id = fields.Many2one(
        "linkedin.account",
        string="Personal account",
        required=True,
        ondelete="cascade",
        index=True,
        domain="[('account_type', '=', 'personal')]",
    )
    attachment_id = fields.Many2one(
        "ir.attachment",
        string="PDF File",
        domain=[("mimetype", "=", "application/pdf")],
        required=True,
    )
    attachment_name = fields.Char(
        related="attachment_id.name", string="File Name", readonly=True
    )
    resume_id = fields.Many2one(
        "linkedin.resume",
        string="LinkedIn document upload",
        help="Optional link to a LinkedIn Documents API upload of this PDF.",
    )
    is_default = fields.Boolean(string="Default CV", default=False, index=True)
    notes = fields.Text(string="Notes")

    @api.constrains("account_id")
    def _check_personal_account(self):
        for rec in self:
            if rec.account_id.account_type != "personal":
                raise ValidationError(
                    _("CV versions can only belong to a personal LinkedIn account.")
                )

    @api.constrains("is_default", "account_id")
    def _check_single_default(self):
        for rec in self.filtered("is_default"):
            others = self.search(
                [
                    ("account_id", "=", rec.account_id.id),
                    ("is_default", "=", True),
                    ("id", "!=", rec.id),
                ]
            )
            if others:
                others.write({"is_default": False})

    def action_set_default(self):
        for rec in self:
            rec.is_default = True
        return True
