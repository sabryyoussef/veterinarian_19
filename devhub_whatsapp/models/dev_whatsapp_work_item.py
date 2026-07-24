# -*- coding: utf-8 -*-
"""Link Work Items to WhatsApp AI analysis."""
from odoo import fields, models
from odoo.exceptions import UserError


class DevWorkItem(models.Model):
    _inherit = "dev.work.item"

    whatsapp_analysis_id = fields.Many2one(
        "dev.whatsapp.analysis",
        string="WhatsApp AI Analysis",
        ondelete="set null",
        index=True,
        copy=False,
    )

    def action_open_whatsapp_analysis(self):
        self.ensure_one()
        if not self.whatsapp_analysis_id:
            raise UserError("No WhatsApp AI analysis linked.")
        analysis = self.env["dev.whatsapp.analysis"].browse(self.whatsapp_analysis_id.id)
        analysis.check_access("read")
        return {
            "type": "ir.actions.act_window",
            "name": "WhatsApp AI Analysis",
            "res_model": "dev.whatsapp.analysis",
            "res_id": analysis.id,
            "view_mode": "form",
            "views": [(False, "form")],
            "target": "current",
        }
