# -*- coding: utf-8 -*-
from odoo import fields, models


class CrmLead(models.Model):
    _inherit = "crm.lead"

    petspot_campaign_id = fields.Many2one("petspot.campaign", index=True, copy=False)
