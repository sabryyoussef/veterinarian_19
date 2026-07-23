# -*- coding: utf-8 -*-

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class LeadEngineScoreRule(models.Model):
    _name = "lead.engine.score.rule"
    _description = "Lead Engine Score Rule"
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
    rule_type = fields.Selection(
        selection=[
            ("always", "Always"),
            ("field", "Field condition"),
        ],
        required=True,
        default="always",
    )
    field_name = fields.Char(
        help="Technical name on crm.lead (allowlisted in pipeline).",
    )
    operator = fields.Selection(
        selection=[
            ("set", "Is set"),
            ("not_set", "Is not set"),
            ("eq", "="),
            ("ne", "!="),
            ("gt", ">"),
            ("gte", ">="),
            ("lt", "<"),
            ("lte", "<="),
            ("contains", "Contains"),
            ("in", "In"),
        ],
    )
    value = fields.Char()
    value_json = fields.Json(help="List operand for 'In' operator.")
    score_delta = fields.Integer(required=True, default=0)
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
    note = fields.Text()

    @api.constrains("rule_type", "field_name", "operator")
    def _check_field_rule(self):
        for rec in self:
            if rec.rule_type != "field":
                continue
            if not rec.field_name or not rec.operator:
                raise ValidationError(
                    self.env._("Field rules require both field name and operator.")
                )

    @api.constrains("score_delta")
    def _check_score_delta_non_negative(self):
        for rec in self:
            if rec.score_delta < 0:
                raise ValidationError(
                    self.env._(
                        "Score delta must be >= 0 (additive MVP; use multiple rules to tune totals)."
                    )
                )
