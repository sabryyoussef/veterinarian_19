# -*- coding: utf-8 -*-
from odoo import models, fields, api


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    chatwoot_bridge_token = fields.Char(
        string='Bridge API Token',
        help='Mirrors integration_bridge.master_token. Use X-Bridge-Token header.'
    )

    chatwoot_bridge_cors_origins = fields.Char(
        string='CORS Allowed Origins',
        default='*',
        help='Comma-separated origins or "*" for all'
    )

    @api.model
    def get_values(self):
        res = super().get_values()
        ICP = self.env['ir.config_parameter'].sudo()
        res.update(
            chatwoot_bridge_token=ICP.get_param(
                'integration_bridge.master_token', default=''),
            chatwoot_bridge_cors_origins=ICP.get_param(
                'chatwoot_bridge.cors_origins', default='*'),
        )
        return res

    def set_values(self):
        super().set_values()
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('integration_bridge.master_token',
                      self.chatwoot_bridge_token or '')
        ICP.set_param('chatwoot_bridge.cors_origins',
                      self.chatwoot_bridge_cors_origins or '*')
