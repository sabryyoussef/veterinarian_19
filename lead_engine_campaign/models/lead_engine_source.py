# -*- coding: utf-8 -*-

from odoo import fields, models


class LeadEngineSource(models.Model):
    _inherit = "lead.engine.source"

    campaign_template_id = fields.Many2one(
        comodel_name="lead.engine.campaign.template",
        string="Campaign template",
        domain="[('active', '=', True)]",
        help="Default Lead Engine campaign template suggested for this source.",
    )