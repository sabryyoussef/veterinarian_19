# -*- coding: utf-8 -*-
from odoo import models, fields, api
import secrets


class IntegrationBridgeSettings(models.TransientModel):
    _name = 'integration.bridge.settings'
    _description = 'Integration Bridge Settings (Master Token)'

    master_token = fields.Char(
        string='Master Token',
        help='Secret token for authenticating all bridge API requests. Use in X-Bridge-Token header.'
    )

    ip_whitelist = fields.Char(
        string='IP Whitelist',
        help='Comma-separated IPs or CIDRs. Leave empty to allow all.'
    )

    @api.model
    def get_values(self):
        ICP = self.env['ir.config_parameter'].sudo()
        return {
            'master_token': ICP.get_param('integration_bridge.master_token', ''),
            'ip_whitelist': ICP.get_param('integration_bridge.ip_whitelist', ''),
        }

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        values = self.get_values()
        for f in fields_list:
            if f in values:
                res[f] = values[f]
        return res

    def set_values(self):
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('integration_bridge.master_token', (self.master_token or '').strip())
        ICP.set_param('integration_bridge.ip_whitelist', (self.ip_whitelist or '').strip())

    def action_save(self):
        self.ensure_one()
        self.set_values()
        return {'type': 'ir.actions.act_window_close'}

    def action_generate_token(self):
        self.ensure_one()
        self.master_token = secrets.token_urlsafe(32)
        return True
