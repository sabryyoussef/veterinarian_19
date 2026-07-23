# -*- coding: utf-8 -*-
"""Evolution (and future provider) instance configuration for WhatsApp Hub."""
from urllib.parse import quote

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class WhatsappInstance(models.Model):
    _name = "whatsapp.instance"
    _description = "WhatsApp / Evolution Instance"
    _order = "sequence, id"

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    provider = fields.Selection(
        [("evolution", "Evolution API")],
        default="evolution",
        required=True,
    )
    api_url = fields.Char(
        string="API URL",
        required=True,
        help="Base Evolution API URL, e.g. http://127.0.0.1:8080",
    )
    api_key = fields.Char(string="API Key")
    instance_name = fields.Char(
        string="Provider Instance Name",
        required=True,
        help="Instance name as registered in Evolution Manager.",
    )
    purpose = fields.Selection(
        [
            ("clinic", "Clinic"),
            ("developer", "Developer / Partner Outreach"),
            ("other", "Other"),
        ],
        default="other",
        required=True,
        index=True,
    )
    is_default = fields.Boolean(string="Default Instance")
    web_url = fields.Char(string="Manager URL")
    # Link to legacy bridge model when present
    evolution_instance_id = fields.Integer(
        string="Legacy evolution.instance ID",
        help="Set when synced from integration_bridge_core.evolution.instance",
        index=True,
    )

    _instance_name_unique = models.Constraint(
        "unique(instance_name)",
        "Provider instance name must be unique.",
    )

    @api.constrains("is_default")
    def _check_single_default(self):
        for rec in self:
            if rec.is_default:
                others = self.search(
                    [("is_default", "=", True), ("id", "!=", rec.id)], limit=1
                )
                if others:
                    raise ValidationError(
                        "Only one WhatsApp instance can be marked as default."
                    )

    def get_config_dict(self):
        self.ensure_one()
        instance = self.instance_name or ""
        return {
            "url": (self.api_url or "").rstrip("/"),
            "key": self.api_key or "",
            "instance": instance,
            "instance_path": quote(instance, safe=""),
            "instance_id": self.id,
            "purpose": self.purpose,
        }

    @api.model
    def get_default_config(self):
        rec = self.search([("is_default", "=", True), ("active", "=", True)], limit=1)
        if not rec:
            rec = self.search([("active", "=", True)], limit=1)
        if rec:
            return rec.get_config_dict()
        # Fall back to evolution.instance if bridge_core installed
        Evo = self.env.get("evolution.instance")
        if Evo is not None:
            return Evo.get_default_config()
        ICP = self.env["ir.config_parameter"].sudo()
        instance = ICP.get_param("integration_bridge.evolution_instance", "sabry min")
        return {
            "url": ICP.get_param(
                "integration_bridge.evolution_url", "http://127.0.0.1:8080"
            ).rstrip("/"),
            "key": ICP.get_param("integration_bridge.evolution_key", ""),
            "instance": instance,
            "instance_path": quote(instance or "", safe=""),
            "instance_id": False,
            "purpose": False,
        }

    @api.model
    def get_config_for_purpose(self, purpose):
        rec = self.search(
            [("purpose", "=", purpose), ("active", "=", True)], limit=1
        )
        if rec:
            return rec.get_config_dict()
        Evo = self.env.get("evolution.instance")
        if Evo is not None:
            return Evo.get_config_for_purpose(purpose)
        return self.get_default_config()

    @api.model
    def sync_from_evolution_instance(self):
        """Import rows from evolution.instance when bridge_core is installed."""
        Evo = self.env.get("evolution.instance")
        if Evo is None:
            return 0
        count = 0
        for evo in Evo.sudo().search([]):
            existing = self.search(
                [
                    "|",
                    ("instance_name", "=", evo.instance_name),
                    ("evolution_instance_id", "=", evo.id),
                ],
                limit=1,
            )
            vals = {
                "name": evo.name,
                "sequence": evo.sequence,
                "active": evo.active,
                "api_url": evo.api_url,
                "api_key": evo.api_key,
                "instance_name": evo.instance_name,
                "purpose": evo.purpose,
                "is_default": evo.is_default,
                "web_url": evo.web_url,
                "evolution_instance_id": evo.id,
            }
            if existing:
                existing.write(vals)
            else:
                self.create(vals)
            count += 1
        return count
