# -*- coding: utf-8 -*-
"""Multi-instance Evolution API configuration for single-DB clinic + developer coexistence."""
import logging
from urllib.parse import quote

import requests

from odoo import api, fields, models
from odoo.exceptions import ValidationError, UserError

_logger = logging.getLogger(__name__)


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

    def send_whatsapp_text(self, number, text, timeout=20):
        """
        One-shot Evolution text send for Hub (and other callers).

        Credentials stay on this model — never return api_key.
        Does not enqueue integration.outbound.queue (Hub owns business retries).

        Returns dict:
          ok, accepted, provider_message_id, http_status, error, temporary,
          response_excerpt (no secrets)
        """
        self.ensure_one()
        if not self.active:
            return {
                'ok': False,
                'accepted': False,
                'provider_message_id': False,
                'http_status': 0,
                'error': 'Evolution instance is inactive',
                'temporary': False,
                'response_excerpt': '',
            }
        number = (number or '').strip()
        text = (text or '').strip()
        if not number or not text:
            return {
                'ok': False,
                'accepted': False,
                'provider_message_id': False,
                'http_status': 0,
                'error': 'number and text are required',
                'temporary': False,
                'response_excerpt': '',
            }
        cfg = self.get_config_dict()
        url = (cfg.get('url') or '').rstrip('/')
        key = cfg.get('key') or ''
        inst_path = cfg.get('instance_path') or ''
        if not url or not key or not inst_path:
            return {
                'ok': False,
                'accepted': False,
                'provider_message_id': False,
                'http_status': 0,
                'error': 'Evolution instance not fully configured',
                'temporary': False,
                'response_excerpt': '',
            }
        endpoint = f"{url}/message/sendText/{inst_path}"
        try:
            resp = requests.post(
                endpoint,
                headers={'apikey': key, 'Content-Type': 'application/json'},
                json={'number': number, 'text': text, 'options': {'delay': 1000}},
                timeout=timeout,
            )
            evo_id = ''
            excerpt = (resp.text or '')[:500]
            try:
                data = resp.json()
                evo_id = (
                    (data.get('key') or {}).get('id')
                    or data.get('messageId')
                    or data.get('id')
                    or ''
                )
            except Exception:
                data = None
            if resp.status_code >= 500:
                return {
                    'ok': False,
                    'accepted': False,
                    'provider_message_id': evo_id or False,
                    'http_status': resp.status_code,
                    'error': f'HTTP {resp.status_code}',
                    'temporary': True,
                    'response_excerpt': excerpt,
                }
            if resp.status_code >= 400:
                return {
                    'ok': False,
                    'accepted': False,
                    'provider_message_id': False,
                    'http_status': resp.status_code,
                    'error': f'HTTP {resp.status_code}',
                    'temporary': False,
                    'response_excerpt': excerpt,
                }
            _logger.info(
                "[Evolution] send_whatsapp_text instance=%s number=%s http=%s evo_id=%s",
                self.instance_name,
                number[:24],
                resp.status_code,
                evo_id or '-',
            )
            return {
                'ok': True,
                'accepted': True,
                'provider_message_id': evo_id or False,
                'http_status': resp.status_code,
                'error': False,
                'temporary': False,
                'response_excerpt': excerpt,
            }
        except requests.Timeout as exc:
            return {
                'ok': False,
                'accepted': False,
                'provider_message_id': False,
                'http_status': 0,
                'error': 'timeout',
                'temporary': True,
                'response_excerpt': str(exc)[:200],
            }
        except requests.RequestException as exc:
            return {
                'ok': False,
                'accepted': False,
                'provider_message_id': False,
                'http_status': 0,
                'error': 'transport_error',
                'temporary': True,
                'response_excerpt': str(exc)[:200],
            }

    @api.model
    def send_whatsapp_text_for_purpose(self, number, text, purpose=None, instance_name=None):
        """Resolve instance then send. Never returns credentials."""
        if instance_name:
            cfg_inst = self.get_config_by_instance_name(instance_name)
            inst = self.browse(cfg_inst.get('instance_id') or 0)
            if not inst:
                inst = self.search([
                    ('instance_name', '=', instance_name),
                    ('active', '=', True),
                ], limit=1)
        elif purpose:
            cfg_inst = self.get_config_for_purpose(purpose)
            inst = self.browse(cfg_inst.get('instance_id') or 0)
            if not inst and cfg_inst.get('instance'):
                inst = self.search([
                    ('instance_name', '=', cfg_inst['instance']),
                    ('active', '=', True),
                ], limit=1)
        else:
            cfg_inst = self.get_default_config()
            inst = self.browse(cfg_inst.get('instance_id') or 0)
            if not inst:
                inst = self.search([('is_default', '=', True), ('active', '=', True)], limit=1)
            if not inst:
                inst = self.search([('active', '=', True)], limit=1)
        if not inst:
            # ICP-only fallback: ephemeral one-shot without persisted row
            cfg = self.get_default_config()
            if not (cfg.get('url') and cfg.get('key') and cfg.get('instance_path')):
                raise UserError('No Evolution instance configured in integration_bridge_core.')
            # Temporary browse-less send via helper
            return self._send_whatsapp_text_with_cfg(cfg, number, text)
        return inst.send_whatsapp_text(number, text)

    @api.model
    def _send_whatsapp_text_with_cfg(self, cfg, number, text, timeout=20):
        """ICP fallback send — cfg must already be resolved; key not logged."""
        url = (cfg.get('url') or '').rstrip('/')
        key = cfg.get('key') or ''
        inst_path = cfg.get('instance_path') or quote(cfg.get('instance') or '', safe='')
        endpoint = f"{url}/message/sendText/{inst_path}"
        try:
            resp = requests.post(
                endpoint,
                headers={'apikey': key, 'Content-Type': 'application/json'},
                json={'number': number, 'text': text},
                timeout=timeout,
            )
            evo_id = ''
            try:
                data = resp.json()
                evo_id = (data.get('key') or {}).get('id') or ''
            except Exception:
                pass
            ok = resp.ok
            return {
                'ok': ok,
                'accepted': ok,
                'provider_message_id': evo_id or False,
                'http_status': resp.status_code,
                'error': False if ok else f'HTTP {resp.status_code}',
                'temporary': resp.status_code >= 500,
                'response_excerpt': (resp.text or '')[:500],
            }
        except Exception as exc:
            return {
                'ok': False,
                'accepted': False,
                'provider_message_id': False,
                'http_status': 0,
                'error': 'transport_error',
                'temporary': True,
                'response_excerpt': str(exc)[:200],
            }
