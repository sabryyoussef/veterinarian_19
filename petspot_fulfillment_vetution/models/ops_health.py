# -*- coding: utf-8 -*-
"""Ops health / freshness monitoring (read-only dashboard data)."""

from odoo import api, fields, models


class PetspotVetutionOpsHealth(models.Model):
    _name = "petspot.vetution.ops.health"
    _description = "Vetution Fulfillment Ops Health Snapshot"
    _order = "id desc"

    name = fields.Char(required=True, default="Health")
    captured_at = fields.Datetime(required=True, default=fields.Datetime.now)
    refresh_fail_count = fields.Integer()
    circuit_open_until = fields.Datetime()
    circuit_open = fields.Boolean()
    shadow_stale_count = fields.Integer()
    auto_quote_stale_risk_count = fields.Integer()
    mapping_pending_count = fields.Integer()
    allowlist_count = fields.Integer()
    shp139_blocked = fields.Boolean()
    note = fields.Text()
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    @api.model
    def capture(self):
        ICP = self.env["ir.config_parameter"].sudo()
        fail = int(ICP.get_param("petspot_fulfillment_vetution.refresh_fail_count", "0") or 0)
        open_until = ICP.get_param("petspot_fulfillment_vetution.circuit_open_until") or False
        now = fields.Datetime.now()
        circuit_open = bool(open_until and fields.Datetime.to_datetime(open_until) > now)
        Shadow = self.env["petspot.vetution.shadow.assessment"]
        stale = Shadow.search_count([("is_fresh", "=", False), ("active", "=", True)])
        Mapping = self.env["petspot.vetution.mapping.review"]
        pending = Mapping.search_count([("state", "=", "pending")])
        allow = self.env["petspot.vetution.automation.allowlist"].search_count([("active", "=", True)])
        prod139 = self.env["product.product"].search([("default_code", "=", "SHP-139-144")], limit=1)
        blocked139 = True
        if prod139 and prod139.vetution_size_id:
            blocked139 = not self.env["petspot.vetution.automation.allowlist"].is_product_allowed(
                prod139
            )
        return self.create(
            {
                "name": f"HEALTH/{now}",
                "refresh_fail_count": fail,
                "circuit_open_until": open_until or False,
                "circuit_open": circuit_open,
                "shadow_stale_count": stale,
                "mapping_pending_count": pending,
                "allowlist_count": allow,
                "shp139_blocked": blocked139,
                "note": "Read-only ops snapshot. Commercial automation stays OFF on Production.",
            }
        )
