# -*- coding: utf-8 -*-
from odoo import api, fields, models

_JOB_LEAD_CTX = {
    'default_type': 'lead',
    'search_default_type': 'lead',
    'search_default_job_outreach_smart': 1,
}
_JOB_OPP_CTX = {
    'default_type': 'opportunity',
    'show_user_team_stages': 1,
    'search_default_job_outreach_smart_opp': 1,
}
_STOCK_LEAD_CTX = {
    'default_type': 'lead',
    'search_default_type': 'lead',
}
_STOCK_OPP_CTX = {
    'default_type': 'opportunity',
    'show_user_team_stages': 1,
}


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    apply_job_outreach_crm_defaults = fields.Boolean(
        string='Apply Job Outreach CRM defaults',
        config_parameter='mail_gmail_connector.apply_job_outreach_crm_defaults',
        help='When enabled, CRM Leads/Pipeline menus open filtered to Job Outreach. '
             'Keep OFF on shared clinic + developer databases.',
    )

    def set_values(self):
        super().set_values()
        self._mail_gmail_apply_crm_action_contexts(
            bool(self.apply_job_outreach_crm_defaults)
        )

    @api.model
    def _mail_gmail_apply_crm_action_contexts(self, apply_job_defaults):
        """Toggle CRM window action contexts for Job Outreach filters."""
        Action = self.env['ir.actions.act_window'].sudo()
        leads = Action.search([('id', '=', self.env.ref('crm.crm_lead_all_leads').id)], limit=1)
        pipeline = Action.search(
            [('id', '=', self.env.ref('crm.crm_lead_action_pipeline').id)], limit=1
        )
        if leads:
            leads.write({'context': str(
                _JOB_LEAD_CTX if apply_job_defaults else _STOCK_LEAD_CTX
            )})
        if pipeline:
            pipeline.write({'context': str(
                _JOB_OPP_CTX if apply_job_defaults else _STOCK_OPP_CTX
            )})
