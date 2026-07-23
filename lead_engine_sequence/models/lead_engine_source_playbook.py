# -*- coding: utf-8 -*-

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class LeadEngineSourcePlaybook(models.Model):
    _inherit = "lead.engine.source"

    playbook_id = fields.Many2one(
        comodel_name="lead.engine.playbook",
        string="Playbook",
        domain="[('company_id', '=', company_id), ('active', '=', True)]",
        help="When set and auto-start is enabled, this playbook starts after successful "
        "qualification on intake (if not blocked for duplicates).",
    )
    playbook_auto_start = fields.Boolean(
        string="Auto-start after qualification",
        default=False,
    )
    playbook_auto_start_duplicate = fields.Boolean(
        string="Auto-start on duplicate leads",
        default=False,
        help="If enabled, duplicate leads (same source + external_ref) also get the playbook. "
        "Default: duplicates are skipped.",
    )

    @api.constrains("playbook_id", "company_id")
    def _check_playbook_company(self):
        for rec in self:
            if rec.playbook_id and rec.playbook_id.company_id != rec.company_id:
                raise ValidationError(
                    self.env._("Playbook must belong to the same company as the source.")
                )
