# -*- coding: utf-8 -*-
"""Multi-instance Evolution API configuration for single-DB clinic + developer coexistence."""
from urllib.parse import quote

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class EvolutionInstance(models.Model):
    _name = 'evolution.instance'
    _description = 'Evolution API Instance'
    _order = 'sequence, id'

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    api_url = fields.Char(
        string='API URL',
        required=True,
        help='Base Evolution API URL, e.g. http://127.0.0.1:8080',
    )
    api_key = fields.Char(string='API Key', required=True)
    instance_name = fields.Char(
        string='Evolution Instance Name',
        required=True,
        help='Instance name as registered in Evolution Manager (may contain spaces).',
    )
    purpose = fields.Selection(
        [
            ('clinic', 'Clinic'),
            ('developer', 'Developer / Partner Outreach'),
            ('other', 'Other'),
        ],
        string='Purpose',
        default='other',
        required=True,
        index=True,
    )
    is_default = fields.Boolean(
        string='Default Instance',
        help='Used when callers do not specify an instance (legacy ICP compatibility).',
    )
    web_url = fields.Char(string='Manager URL')

    _sql_constraints = [
        (
            'evolution_instance_name_uniq',
            'unique(instance_name)',
            'Evolution instance name must be unique.',
        ),
    ]

    @api.constrains('is_default')
    def _check_single_default(self):
        for rec in self:
            if rec.is_default:
                others = self.search([
                    ('is_default', '=', True),
                    ('id', '!=', rec.id),
                ], limit=1)
                if others:
                    raise ValidationError(
                        'Only one Evolution instance can be marked as default.'
                    )

    def get_config_dict(self):
        self.ensure_one()
        instance = self.instance_name or ''
        return {
            'url': (self.api_url or '').rstrip('/'),
            'key': self.api_key or '',
            'instance': instance,
            'instance_path': quote(instance, safe=''),
            'instance_id': self.id,
            'purpose': self.purpose,
        }

    @api.model
    def _table_ready(self):
        """False until module upgrade creates public.evolution_instance (Prod safe)."""
        self.env.cr.execute("SELECT to_regclass('public.evolution_instance')")
        return bool(self.env.cr.fetchone()[0])

    @api.model
    def _icp_fallback_config(self):
        ICP = self.env['ir.config_parameter'].sudo()
        instance = ICP.get_param('integration_bridge.evolution_instance', 'sabry min')
        return {
            'url': ICP.get_param(
                'integration_bridge.evolution_url', 'http://127.0.0.1:8080'
            ).rstrip('/'),
            'key': ICP.get_param('integration_bridge.evolution_key', ''),
            'instance': instance,
            'instance_path': quote(instance or '', safe=''),
            'instance_id': False,
            'purpose': False,
        }

    @api.model
    def get_default_config(self):
        """Resolve outbound Evolution config: default row, else ICP legacy trio."""
        if not self._table_ready():
            return self._icp_fallback_config()
        if not self.search_count([]):
            self.migrate_from_icp()
        inst = self.search([('is_default', '=', True), ('active', '=', True)], limit=1)
        if not inst:
            inst = self.search([('active', '=', True)], limit=1)
        if inst:
            return inst.get_config_dict()
        return self._icp_fallback_config()

    @api.model
    def get_config_for_purpose(self, purpose):
        if not self._table_ready():
            return self._icp_fallback_config()
        inst = self.search([
            ('purpose', '=', purpose),
            ('active', '=', True),
        ], limit=1)
        if inst:
            return inst.get_config_dict()
        return self.get_default_config()

    @api.model
    def get_config_by_instance_name(self, instance_name):
        if not instance_name:
            return self.get_default_config()
        if not self._table_ready():
            return self._icp_fallback_config()
        inst = self.search([
            ('instance_name', '=', instance_name),
            ('active', '=', True),
        ], limit=1)
        if inst:
            return inst.get_config_dict()
        return self.get_default_config()

    @api.model
    def migrate_from_icp(self):
        """Create a default instance from legacy ICP keys if none exist."""
        if not self._table_ready() or self.search_count([]):
            return self.browse()
        ICP = self.env['ir.config_parameter'].sudo()
        url = ICP.get_param('integration_bridge.evolution_url')
        key = ICP.get_param('integration_bridge.evolution_key')
        name = ICP.get_param('integration_bridge.evolution_instance')
        if not (url and key and name):
            return self.browse()
        return self.create({
            'name': f'Clinic ({name})',
            'api_url': url,
            'api_key': key,
            'instance_name': name,
            'web_url': ICP.get_param('integration_bridge.evolution_web_url', ''),
            'purpose': 'clinic',
            'is_default': True,
        })
