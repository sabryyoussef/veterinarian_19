# -*- coding: utf-8 -*-

from odoo import api, fields, models


class CrmLead(models.Model):
    _inherit = "crm.lead"

    lead_engine_source_id = fields.Many2one(
        comodel_name="lead.engine.source",
        string="Lead Engine Source",
        index=True,
        tracking=True,
    )
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
        string="Capture channel",
        index=True,
    )
    external_ref = fields.Char(index=True, tracking=True)
    lead_score = fields.Integer(
        string="Lead Engine Score",
        default=0,
        tracking=True,
    )
    lead_temperature = fields.Selection(
        selection=[
            ("cold", "Cold"),
            ("warm", "Warm"),
            ("hot", "Hot"),
        ],
    )
    duplicate_status = fields.Selection(
        selection=[
            ("unique", "Unique"),
            ("duplicate", "Duplicate"),
            ("merged_master", "Merged (master)"),
            ("merged_duplicate", "Merged (duplicate)"),
        ],
        default="unique",
        required=True,
    )
    duplicate_master_id = fields.Many2one(
        comodel_name="crm.lead",
        string="Duplicate of",
        index=True,
        ondelete="set null",
    )
    assignment_status = fields.Selection(
        selection=[
            ("unassigned", "Unassigned"),
            ("assigned", "Assigned"),
            ("rule_applied", "Rule applied"),
            ("manual", "Manual"),
        ],
        default="unassigned",
        required=True,
    )
    qualification_state = fields.Selection(
        selection=[
            ("new", "New"),
            ("working", "Working"),
            ("qualified", "Qualified"),
            ("disqualified", "Disqualified"),
        ],
        default="new",
        required=True,
        tracking=True,
    )
    first_response_deadline = fields.Datetime()
    last_engagement_at = fields.Datetime()

    def _prepare_customer_values(self, partner_name, is_company=False, parent_id=False):
        res = super()._prepare_customer_values(partner_name, is_company=is_company, parent_id=parent_id)
        if self.lead_engine_source_id:
            res["lead_engine_source_id"] = self.lead_engine_source_id.id
        if self.external_ref:
            res["lead_engine_external_ref"] = self.external_ref
        return res
