# -*- coding: utf-8 -*-

from odoo import fields, models


class LeadEngineAssignmentRule(models.Model):
    _name = "lead.engine.assignment.rule"
    _description = "Lead Engine Assignment Rule"
    _order = "sequence, id"

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10, required=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        comodel_name="res.company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    source_id = fields.Many2one(comodel_name="lead.engine.source", ondelete="set null")
    le_channel = fields.Selection(
        selection=[
            ("api", "API"),
            ("webhook", "Webhook"),
            ("form", "Form"),
            ("email", "Email"),
            ("ads", "Ads"),
            ("import", "Import"),
            ("other", "Other"),
        ],
    )
    min_score = fields.Integer()
    max_score = fields.Integer()
    team_id = fields.Many2one(comodel_name="crm.team", ondelete="set null")
    user_id = fields.Many2one(
        comodel_name="res.users",
        domain="[('share', '=', False)]",
        ondelete="set null",
    )
    domain_expression = fields.Char(
        default="[]",
        help="Odoo domain on crm.lead, evaluated with safe_eval. Invalid domains are treated as non-matching "
        "(check server logs). Prefer testing rule order on a copy database.",
    )
    stop_processing = fields.Boolean(
        default=False,
        help="Reserved: MVP assignment uses first matching rule with a user or team only; "
        "later rules are ignored.",
    )
    note = fields.Text()
