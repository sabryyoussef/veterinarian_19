# -*- coding: utf-8 -*-
from odoo import fields, models


class SurveySurvey(models.Model):
    _inherit = "survey.survey"

    petspot_campaign_step_id = fields.Many2one(
        "petspot.campaign.step",
        string="Campaign Step",
        ondelete="set null",
    )


class SurveyQuestion(models.Model):
    _inherit = "survey.question"

    petspot_field_role = fields.Selection(
        [
            ("name", "Contact Name"),
            ("phone", "Phone / WhatsApp"),
            ("email", "Email"),
            ("pet_type", "Pet Type"),
        ],
        string="Campaign Field Role",
        help="Maps this question to CRM / reward deduplication fields.",
    )
