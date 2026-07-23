# -*- coding: utf-8 -*-

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class LeadEngineIdentityMap(models.Model):
    _name = "lead.engine.identity.map"
    _description = "Lead Engine Identity Map"
    _order = "source_id, external_ref, id"

    source_id = fields.Many2one(
        comodel_name="lead.engine.source",
        required=True,
        ondelete="cascade",
        index=True,
    )
    company_id = fields.Many2one(
        related="source_id.company_id",
        store=True,
        readonly=True,
    )
    external_ref = fields.Char(index=True)
    lead_id = fields.Many2one(comodel_name="crm.lead", ondelete="set null", index=True)
    partner_id = fields.Many2one(comodel_name="res.partner", ondelete="set null")
    email = fields.Char()
    mobile = fields.Char()
    company_name = fields.Char()
    normalized_email = fields.Char(index=True)
    normalized_mobile = fields.Char(index=True)
    matched_by = fields.Selection(
        selection=[
            ("external_ref", "External ref"),
            ("email", "Email"),
            ("phone", "Phone"),
            ("manual", "Manual"),
            ("merge", "Merge"),
        ],
    )
    active = fields.Boolean(default=True)

    @api.constrains("source_id", "external_ref", "active")
    def _check_unique_active_external_ref(self):
        for rec in self:
            if not rec.active or not rec.external_ref:
                continue
            dup = self.search_count(
                [
                    ("source_id", "=", rec.source_id.id),
                    ("external_ref", "=", rec.external_ref),
                    ("active", "=", True),
                    ("id", "!=", rec.id),
                ]
            )
            if dup:
                raise ValidationError(
                    self.env._(
                        "An active identity map already exists for this source and external reference."
                    )
                )
