# -*- coding: utf-8 -*-

from odoo import fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    lead_engine_source_id = fields.Many2one(
        comodel_name="lead.engine.source",
        string="Lead Engine Source",
        index=True,
    )
    lead_engine_external_ref = fields.Char(index=True)
