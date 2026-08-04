# -*- coding: utf-8 -*-
from odoo import fields, models


class LinkedinJobRejection(models.Model):
    _name = "linkedin.job.rejection"
    _description = "Job Rejection Reason"
    _order = "create_date desc, id desc"

    job_id = fields.Many2one(
        "linkedin.job", required=True, ondelete="cascade", index=True
    )
    reason_code = fields.Char(required=True, index=True)
    reason_label = fields.Char(required=True)
    rule_id = fields.Many2one("linkedin.job.filter.rule", ondelete="set null")
    pipeline_stage = fields.Selection(
        [
            ("validate", "Validate"),
            ("dedupe", "Deduplicate"),
            ("hard_filter", "Hard Filter"),
            ("preflight", "Preflight"),
            ("manual", "Manual"),
        ],
        default="hard_filter",
        required=True,
        index=True,
    )
