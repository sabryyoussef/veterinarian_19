# -*- coding: utf-8 -*-
from odoo import fields, models


class LinkedinJobSourceLink(models.Model):
    _name = "linkedin.job.source.link"
    _description = "Secondary Job Source Sighting"
    _order = "fetched_at desc, id desc"

    job_id = fields.Many2one(
        "linkedin.job", required=True, ondelete="cascade", index=True
    )
    connector_id = fields.Many2one(
        "linkedin.job.source.connector", ondelete="set null", index=True
    )
    external_id = fields.Char(index=True)
    source_url = fields.Char()
    fetched_at = fields.Datetime(default=fields.Datetime.now)
    note = fields.Char()
