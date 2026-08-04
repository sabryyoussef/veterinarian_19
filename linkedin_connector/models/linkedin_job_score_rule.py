# -*- coding: utf-8 -*-
from odoo import fields, models


class LinkedinJobScoreRule(models.Model):
    _name = "linkedin.job.score.rule"
    _description = "Configurable Job Score Rule"
    _order = "sequence, id"

    name = fields.Char(required=True)
    code = fields.Char(required=True, index=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    rule_type = fields.Selection(
        [("bonus", "Bonus"), ("penalty", "Penalty")],
        required=True,
        default="bonus",
    )
    category = fields.Selection(
        [
            ("role_fit", "Role fit"),
            ("technical_fit", "Technical fit"),
            ("location_fit", "Location fit"),
            ("remote_fit", "Remote fit"),
            ("authorization_fit", "Authorization fit"),
            ("salary_fit", "Salary fit"),
            ("source_quality", "Source quality"),
        ],
        required=True,
        default="role_fit",
    )
    match_scope = fields.Selection(
        [
            ("title", "Title"),
            ("blob", "Title+Description"),
            ("location", "Location"),
            ("remote_policy", "Remote policy"),
            ("visa", "Visa/sponsorship fields"),
            ("company", "Company"),
        ],
        default="blob",
        required=True,
    )
    pattern = fields.Char(help="Python regex (case-insensitive).")
    points = fields.Float(required=True)
    mutex_group = fields.Char(
        help="Only the first matching rule in a mutex group applies."
    )
    reason_label = fields.Char()

    _sql_constraints = [
        ("linkedin_job_score_rule_code_uniq", "unique(code)", "Score rule code must be unique."),
    ]


class LinkedinJobFilterRule(models.Model):
    _name = "linkedin.job.filter.rule"
    _description = "Configurable Job Hard Filter Rule"
    _order = "sequence, id"

    name = fields.Char(required=True)
    code = fields.Char(required=True, index=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    match_scope = fields.Selection(
        [
            ("title", "Title"),
            ("blob", "Title+Description"),
            ("location", "Location"),
            ("remote_policy", "Remote policy"),
            ("visa", "Visa/sponsorship fields"),
            ("apply_url", "Apply URL"),
            ("company", "Company"),
            ("expiry", "Expiry"),
        ],
        default="blob",
        required=True,
    )
    pattern = fields.Char(help="Python regex. Empty for structural checks keyed by code.")
    reason_code = fields.Char(required=True)
    reason_label = fields.Char(required=True)
    require_explicit = fields.Boolean(
        default=True,
        help="If set, unknown/missing data must NOT trigger this filter.",
    )

    _sql_constraints = [
        ("linkedin_job_filter_rule_code_uniq", "unique(code)", "Filter rule code must be unique."),
    ]
