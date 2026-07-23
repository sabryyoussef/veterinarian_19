# -*- coding: utf-8 -*-

from odoo import api, fields, models


class LeadEnginePlaybookStartWizard(models.TransientModel):
    _name = "lead.engine.playbook.start.wizard"
    _description = "Start Lead Engine playbook on a lead"

    lead_id = fields.Many2one(
        comodel_name="crm.lead",
        string="Lead",
        required=True,
        ondelete="cascade",
    )
    company_id = fields.Many2one(
        related="lead_id.company_id",
        comodel_name="res.company",
    )
    playbook_id = fields.Many2one(
        comodel_name="lead.engine.playbook",
        string="Playbook",
        required=True,
        domain="[('company_id', '=', company_id), ('active', '=', True)]",
    )
    allow_duplicate_lead = fields.Boolean(
        string="Allow start on duplicate lead",
        default=True,
        help="If the lead is marked as a duplicate, allow starting anyway (manual override).",
    )
    allow_duplicate_active_run = fields.Boolean(
        string="Allow overlapping run (same playbook already running)",
        default=False,
        help="By default, a lead cannot have two running runs for the same playbook. "
        "Enable only if you intentionally need a second concurrent run.",
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        ctx = self.env.context
        if ctx.get("active_model") == "crm.lead" and ctx.get("active_id"):
            res.setdefault("lead_id", ctx["active_id"])
        return res

    def action_start_playbook(self):
        self.ensure_one()
        svc = self.env["lead.engine.playbook.service"]
        svc.start_playbook(
            self.lead_id,
            self.playbook_id,
            force_duplicate=self.allow_duplicate_lead,
            allow_duplicate_active_run=self.allow_duplicate_active_run,
        )
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Playbook runs"),
            "res_model": "lead.engine.playbook.run",
            "domain": [("lead_id", "=", self.lead_id.id)],
            "view_mode": "list,form",
            "target": "current",
        }
