# -*- coding: utf-8 -*-
"""Work Item origin metadata + Dev Project Work Items relation."""
from odoo import fields, models


class DevWorkItem(models.Model):
    _inherit = "dev.work.item"

    source_type = fields.Selection(
        [
            ("manual", "Manual"),
            ("whatsapp", "WhatsApp (manual)"),
            ("whatsapp_ai", "WhatsApp (AI analysis)"),
            ("intake", "WhatsApp intake"),
            ("odoo_task", "Odoo task"),
            ("other", "Other"),
        ],
        default="manual",
        required=True,
        index=True,
        tracking=True,
    )
    origin_ai_whatsapp = fields.Boolean(
        default=False,
        index=True,
        help="Created from an approved WhatsApp AI analysis (never by Dify/n8n directly).",
    )
    # Linked from devhub_whatsapp; stored here only as Integer-safe M2O when module installed.
    # Concrete Many2one is defined in devhub_whatsapp inherit to avoid circular deps at import.


class DevProject(models.Model):
    _inherit = "dev.project"

    work_item_ids = fields.One2many(
        "dev.work.item", "dev_project_id", string="Work Items"
    )
    work_item_count = fields.Integer(compute="_compute_work_item_count")

    def _compute_work_item_count(self):
        Work = self.env["dev.work.item"]
        for project in self:
            project.work_item_count = Work.search_count(
                [("dev_project_id", "=", project.id)]
            )
