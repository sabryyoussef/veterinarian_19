# -*- coding: utf-8 -*-

from odoo import api, fields, models


class LeadEngineSource(models.Model):
    _name = "lead.engine.source"
    _description = "Lead Engine Source Registry"
    _order = "sequence, name"

    name = fields.Char(
        required=True,
        help="Human-readable label in lists and on the CRM lead.",
    )
    code = fields.Char(
        required=True,
        help="Stable machine key: unique per company, used for HTTP intake routing and integrations.",
    )
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)
    channel = fields.Selection(
        selection=[
            ("api", "API"),
            ("webhook", "Webhook"),
            ("form", "Form"),
            ("email", "Email"),
            ("ads", "Ads"),
            ("import", "Import"),
            ("other", "Other"),
        ],
        default="other",
        required=True,
    )
    description = fields.Text()
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    default_team_id = fields.Many2one(
        comodel_name="crm.team",
        string="Default sales team",
        help="Fallback team when no assignment rule matches but auto-assign is enabled on this source.",
    )
    default_user_id = fields.Many2one(
        comodel_name="res.users",
        string="Default salesperson",
        domain="[('share', '=', False)]",
        help="Fallback salesperson when no assignment rule matches but auto-assign is enabled.",
    )
    auto_score = fields.Boolean(
        default=True,
        help="If off, pipeline scoring is skipped for this source’s leads (existing scores are left unchanged).",
    )
    auto_assign = fields.Boolean(
        default=True,
        help="If off, assignment rules and source defaults are skipped (existing owner/team are not cleared here).",
    )
    utm_source_id = fields.Many2one(comodel_name="utm.source", string="Linked UTM Source")
    utm_medium_id = fields.Many2one(comodel_name="utm.medium", string="Default UTM Medium")
    utm_campaign_id = fields.Many2one(comodel_name="utm.campaign", string="Default UTM Campaign")
    note = fields.Text()

    _lead_engine_source_code_company_uniq = models.Constraint(
        "UNIQUE(code, company_id)",
        "Source code must be unique per company.",
    )

    @api.model
    def get_by_code(self, code, company_id=None):
        """Resolve an active source by code for the given company (defaults to current company)."""
        cid = company_id if company_id is not None else self.env.company.id
        return self.search(
            [("code", "=", code), ("company_id", "=", cid), ("active", "=", True)],
            limit=1,
        )
