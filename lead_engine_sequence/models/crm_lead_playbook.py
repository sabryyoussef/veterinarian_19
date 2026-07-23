# -*- coding: utf-8 -*-

from odoo import _, fields, models
from odoo.exceptions import UserError


class CrmLeadPlaybook(models.Model):
    _inherit = "crm.lead"

    playbook_run_ids = fields.One2many(
        comodel_name="lead.engine.playbook.run",
        inverse_name="lead_id",
        string="Playbook runs",
    )
    playbook_run_count = fields.Integer(compute="_compute_playbook_run_count")

    def _compute_playbook_run_count(self):
        for lead in self:
            lead.playbook_run_count = len(lead.playbook_run_ids)

    def action_le_start_source_playbook(self):
        """Manual admin/test start using the lead's source playbook (duplicates allowed)."""
        self.ensure_one()
        src = self.lead_engine_source_id
        if not src or not src.playbook_id:
            raise UserError(_("Set a playbook on the Lead Engine source to start one from the lead."))
        self.env["lead.engine.playbook.service"].start_playbook(
            self,
            src.playbook_id,
            force_duplicate=True,
        )
        return {
            "type": "ir.actions.act_window",
            "name": _("Playbook runs"),
            "res_model": "lead.engine.playbook.run",
            "domain": [("lead_id", "=", self.id)],
            "view_mode": "list,form",
            "target": "current",
        }

    def action_le_playbook_runs(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Playbook runs"),
            "res_model": "lead.engine.playbook.run",
            "domain": [("lead_id", "=", self.id)],
            "view_mode": "list,form",
            "target": "current",
        }

    def action_le_start_playbook_wizard(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Start playbook"),
            "res_model": "lead.engine.playbook.start.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_lead_id": self.id},
        }
